"""Grade predictions by comparing to actual NBA box score results."""

from datetime import date, datetime, timedelta

from tools.stats_tools import _get_game_log
from tools.parser_tools import compute_combo_value, get_current_season, find_player
from pipeline.db import (
    get_pending_predictions,
    update_prediction_grade,
    insert_performance_log,
)


def _find_game_on_date(games: list[dict], target_date: date) -> dict | None:
    """Find a game in the game log matching the target date.

    nba_api game dates come in formats like 'MAR 07, 2026' or '2026-03-07T...'
    """
    target_str = target_date.strftime("%Y-%m-%d")
    target_str_alt = target_date.strftime("%b %d, %Y").upper()

    for game in games:
        game_date_raw = str(game.get("GAME_DATE", ""))

        # Try YYYY-MM-DD match (sometimes nba_api returns ISO-ish)
        if target_str in game_date_raw:
            return game

        # Try MMM DD, YYYY match
        try:
            parsed = datetime.strptime(game_date_raw, "%b %d, %Y")
            if parsed.strftime("%Y-%m-%d") == target_str:
                return game
        except ValueError:
            pass

        # Try uppercase match
        if target_str_alt in game_date_raw.upper():
            return game

    return None


def grade_predictions(target_date: date | None = None) -> dict:
    """Grade all pending predictions for the target date.

    Returns summary dict with counts of graded/hit/miss/push/no_data.
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    pending = get_pending_predictions(target_date)
    if not pending:
        print(f"  No pending predictions for {target_date}")
        return {"graded": 0, "hit": 0, "miss": 0, "push": 0, "no_data": 0}

    print(f"  Grading {len(pending)} predictions for {target_date}...")
    season = get_current_season()
    results = {"graded": 0, "hit": 0, "miss": 0, "push": 0, "no_data": 0}

    # Cache game logs by player_id to avoid redundant fetches
    game_log_cache = {}

    for pred in pending:
        player_id = pred.get("player_id")
        stat_column = pred["stat_column"]
        line = pred["line"]
        prediction_direction = pred["prediction"]

        # Resolve player_id if missing
        if not player_id:
            player = find_player(pred["player_name"])
            if player:
                player_id = player["id"]
            else:
                update_prediction_grade(pred["id"], status="no_data")
                results["no_data"] += 1
                continue

        # Get game log (cached per player)
        if player_id not in game_log_cache:
            try:
                game_log_cache[player_id] = _get_game_log(player_id, season)
            except Exception:
                game_log_cache[player_id] = []

        games = game_log_cache[player_id]
        game = _find_game_on_date(games, target_date)

        if not game:
            update_prediction_grade(pred["id"], status="no_data")
            results["no_data"] += 1
            continue

        # Compute actual value (handles combo stats)
        actual_value = compute_combo_value(game, stat_column)
        if actual_value is None:
            update_prediction_grade(pred["id"], status="no_data")
            results["no_data"] += 1
            continue

        # Grade: HIT, MISS, or PUSH
        if actual_value > line:
            actual_direction = "OVER"
        elif actual_value < line:
            actual_direction = "UNDER"
        else:
            update_prediction_grade(
                pred["id"], status="graded", actual_value=actual_value, result="PUSH"
            )
            results["push"] += 1
            results["graded"] += 1
            pn = pred["player_name"]
            print(f"    {pn} {line} {stat_column}: PUSH (actual={actual_value})")
            continue

        if prediction_direction == actual_direction:
            result = "HIT"
            results["hit"] += 1
        else:
            result = "MISS"
            results["miss"] += 1

        update_prediction_grade(
            pred["id"], status="graded", actual_value=actual_value, result=result
        )
        results["graded"] += 1
        pn = pred["player_name"]
        print(f"    {pn} {line} {stat_column}: {result} (pred={prediction_direction}, actual={actual_value})")

    # Insert performance log for the day
    if results["graded"] > 0:
        _insert_daily_log(target_date, results, pending)

    return results


def _insert_daily_log(target_date: date, results: dict, predictions: list[dict]):
    """Insert a daily performance log entry."""
    graded = [p for p in predictions if p.get("result") in ("HIT", "MISS", "PUSH")]
    total = results["hit"] + results["miss"]
    hit_rate = results["hit"] / total if total > 0 else 0

    # Confidence breakdown
    high_total = sum(1 for p in graded if p.get("confidence") == "HIGH" and p.get("result") in ("HIT", "MISS"))
    high_hits = sum(1 for p in graded if p.get("confidence") == "HIGH" and p.get("result") == "HIT")
    med_total = sum(1 for p in graded if p.get("confidence") == "MEDIUM" and p.get("result") in ("HIT", "MISS"))
    med_hits = sum(1 for p in graded if p.get("confidence") == "MEDIUM" and p.get("result") == "HIT")
    low_total = sum(1 for p in graded if p.get("confidence") == "LOW" and p.get("result") in ("HIT", "MISS"))
    low_hits = sum(1 for p in graded if p.get("confidence") == "LOW" and p.get("result") == "HIT")

    # Stat breakdown
    stat_breakdown = {}
    for p in graded:
        st = p.get("stat_type", "unknown")
        if st not in stat_breakdown:
            stat_breakdown[st] = {"total": 0, "hits": 0}
        if p.get("result") in ("HIT", "MISS"):
            stat_breakdown[st]["total"] += 1
            if p.get("result") == "HIT":
                stat_breakdown[st]["hits"] += 1

    # Error metrics
    errors = []
    for p in graded:
        if p.get("predicted_value") and p.get("actual_value") is not None:
            errors.append(p["predicted_value"] - p["actual_value"])

    over_preds = [p for p in graded if p.get("prediction") == "OVER" and p.get("result") in ("HIT", "MISS")]
    under_preds = [p for p in graded if p.get("prediction") == "UNDER" and p.get("result") in ("HIT", "MISS")]

    try:
        insert_performance_log({
            "period_start": target_date.isoformat(),
            "period_end": target_date.isoformat(),
            "period_type": "daily",
            "total_predictions": results["graded"],
            "hits": results["hit"],
            "misses": results["miss"],
            "pushes": results["push"],
            "hit_rate": round(hit_rate, 3),
            "high_conf_total": high_total,
            "high_conf_hits": high_hits,
            "medium_conf_total": med_total,
            "medium_conf_hits": med_hits,
            "low_conf_total": low_total,
            "low_conf_hits": low_hits,
            "stat_breakdown": stat_breakdown,
            "avg_predicted_value": round(sum(p.get("predicted_value", 0) for p in graded) / len(graded), 1) if graded else None,
            "avg_actual_value": round(sum(p.get("actual_value", 0) for p in graded if p.get("actual_value") is not None) / len(graded), 1) if graded else None,
            "avg_error": round(sum(errors) / len(errors), 2) if errors else None,
            "over_predictions": len(over_preds),
            "under_predictions": len(under_preds),
            "over_hit_rate": round(sum(1 for p in over_preds if p["result"] == "HIT") / len(over_preds), 3) if over_preds else None,
            "under_hit_rate": round(sum(1 for p in under_preds if p["result"] == "HIT") / len(under_preds), 3) if under_preds else None,
        })
    except Exception as e:
        print(f"  Warning: Failed to insert performance log: {e}")
