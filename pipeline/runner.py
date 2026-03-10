"""Pipeline runner — orchestrates predict, grade, improve, and status phases."""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from pipeline.config import (
    supabase,
    MAX_GAMES_PER_DAY,
    MIN_PREDICTIONS_FOR_IMPROVEMENT,
    IMPROVEMENT_INTERVAL_DAYS,
)
from pipeline.db import (
    insert_prediction,
    get_graded_predictions,
    get_performance_logs,
    get_active_instruction_version,
    get_latest_version_number,
    insert_instruction_version,
    get_monthly_credits_used,
)
from pipeline.odds_fetcher import (
    fetch_todays_events,
    select_events,
    fetch_player_props,
    CreditBudgetExceeded,
)
from pipeline.result_grader import grade_predictions

from bet_agents.orchestrator import run_prediction
from bet_agents.prediction_agent import PREDICTION_AGENT_INSTRUCTIONS


# US Eastern timezone offset (UTC-5 standard, UTC-4 DST)
ET = timezone(timedelta(hours=-5))


def _filter_top_props(props: list[dict], max_per_game: int = 5) -> list[dict]:
    """Keep the top N highest-line props per game per stat type.

    This focuses predictions on star players (higher lines) instead of
    running 90+ predictions for every bench player.
    Each game gets max_per_game players per stat type (points, rebounds, etc.).
    """
    from collections import defaultdict
    by_game_stat = defaultdict(list)
    for p in props:
        key = (p.get("event_id", ""), p.get("stat_type", ""))
        by_game_stat[key].append(p)

    filtered = []
    for key, group in by_game_stat.items():
        # Sort by line descending — highest lines = star players
        group.sort(key=lambda x: x.get("line", 0), reverse=True)
        filtered.extend(group[:max_per_game])

    return filtered


# ---------------------------------------------------------------------------
# Predict Phase
# ---------------------------------------------------------------------------

async def predict_phase() -> dict:
    """Fetch today's DraftKings props and run predictions.

    Steps:
    1. Fetch today's NBA events (0 credits)
    2. Select top N games by priority
    3. Fetch player props for each game (4 credits each)
    4. Run prediction pipeline for each prop
    5. Store predictions in Supabase

    Returns summary dict.
    """
    run_id = str(uuid.uuid4())
    today = date.today()
    print(f"\n{'='*60}")
    print(f"  PREDICT PHASE — {today} (run {run_id[:8]})")
    print(f"{'='*60}\n")

    # 1. Fetch events
    print("[1] Fetching today's NBA events...")
    try:
        events = await fetch_todays_events()
    except Exception as e:
        print(f"  ERROR fetching events: {e}")
        return {"error": str(e), "predictions": 0}

    if not events:
        print("  No NBA games today.")
        return {"predictions": 0, "games": 0}

    print(f"  Found {len(events)} games today")

    # 2. Select top games
    selected = select_events(events, max_games=MAX_GAMES_PER_DAY)
    print(f"  Selected {len(selected)} games for predictions:")
    for ev in selected:
        print(f"    {ev.get('away_team', '?')} @ {ev.get('home_team', '?')}")

    # 3. Fetch props for each game
    all_props = []
    for ev in selected:
        event_id = ev.get("id", "")
        print(f"\n[2] Fetching props for {ev.get('away_team', '?')} @ {ev.get('home_team', '?')}...")
        try:
            props = await fetch_player_props(event_id, ev)
            all_props.extend(props)
            print(f"  Got {len(props)} player props")
        except CreditBudgetExceeded as e:
            print(f"  BUDGET: {e}")
            break
        except Exception as e:
            print(f"  ERROR fetching props: {e}")
            continue

    if not all_props:
        print("\n  No props available to predict.")
        return {"predictions": 0, "games": len(selected)}

    # Filter to top props per game — pick highest-line players per stat type
    # This avoids predicting 95 bench player props and focuses on stars
    all_props = _filter_top_props(all_props, max_per_game=5)
    print(f"\n  Props to predict (after filtering top players): {len(all_props)}")

    # Get active instruction version
    active_version = get_active_instruction_version()
    version_id = active_version["id"] if active_version else None

    # 4. Run predictions
    predictions_stored = 0
    errors = 0

    # Resolve player IDs upfront for grading later
    from tools.parser_tools import find_player
    player_id_cache = {}

    for i, prop in enumerate(all_props, 1):
        player = prop["player_name"]
        stat = prop["stat_type"]
        line = prop["line"]
        prompt = f"{player} {line} {stat} over"

        # Resolve player_id (cached)
        if player not in player_id_cache:
            p = find_player(player)
            player_id_cache[player] = p["id"] if p else None

        print(f"\n[3] Prediction {i}/{len(all_props)}: {player} {line} {stat}...")
        try:
            result = await run_prediction(prompt)
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1
            continue

        if not result.get("prediction"):
            print(f"  SKIP: No prediction produced")
            errors += 1
            continue

        # Store in Supabase
        pred_data = {
            "game_date": today.isoformat(),
            "event_id": prop.get("event_id", ""),
            "player_name": player,
            "player_id": player_id_cache.get(player),
            "stat_type": prop["stat_type"],
            "stat_column": prop["stat_column"],
            "line": line,
            "prediction": result["prediction"],
            "confidence": result.get("confidence"),
            "confidence_pct": result.get("confidence_pct"),
            "predicted_value": result.get("predicted_value"),
            "reasoning": result.get("reasoning", ""),
            "over_odds": prop.get("over_odds"),
            "under_odds": prop.get("under_odds"),
            "market_key": prop.get("market_key", ""),
            "home_team": prop.get("home_team", ""),
            "away_team": prop.get("away_team", ""),
            "status": "pending",
            "pipeline_run_id": run_id,
            "instruction_version_id": version_id,
        }

        try:
            insert_prediction(pred_data)
            predictions_stored += 1
            print(f"  ✓ {result['prediction']} ({result.get('confidence', '?')}, {result.get('confidence_pct', '?')}%)")
        except Exception as e:
            print(f"  ERROR storing prediction: {e}")
            errors += 1

    print(f"\n{'='*60}")
    print(f"  PREDICT PHASE COMPLETE")
    print(f"  Stored: {predictions_stored} | Errors: {errors} | Total props: {len(all_props)}")
    print(f"{'='*60}\n")

    return {
        "predictions": predictions_stored,
        "errors": errors,
        "games": len(selected),
        "total_props": len(all_props),
        "run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Grade Phase
# ---------------------------------------------------------------------------

async def grade_phase(target_date: date | None = None) -> dict:
    """Grade predictions for a target date (defaults to yesterday).

    Returns grading summary dict.
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    print(f"\n{'='*60}")
    print(f"  GRADE PHASE — {target_date}")
    print(f"{'='*60}\n")

    results = grade_predictions(target_date)

    print(f"\n{'='*60}")
    print(f"  GRADE PHASE COMPLETE")
    print(f"  Graded: {results['graded']} | Hit: {results['hit']} | Miss: {results['miss']} | Push: {results['push']} | No Data: {results['no_data']}")
    if results["hit"] + results["miss"] > 0:
        rate = results["hit"] / (results["hit"] + results["miss"])
        print(f"  Hit Rate: {rate:.1%}")
    print(f"{'='*60}\n")

    return results


# ---------------------------------------------------------------------------
# Improve Phase
# ---------------------------------------------------------------------------

async def improve_phase() -> dict:
    """Analyze recent performance and self-improve prediction instructions.

    Only runs if:
    - At least MIN_PREDICTIONS_FOR_IMPROVEMENT graded predictions exist
    - Last improvement was at least IMPROVEMENT_INTERVAL_DAYS ago
    """
    print(f"\n{'='*60}")
    print(f"  IMPROVE PHASE")
    print(f"{'='*60}\n")

    # Check if enough data exists
    graded = get_graded_predictions(limit=200)
    if len(graded) < MIN_PREDICTIONS_FOR_IMPROVEMENT:
        print(f"  Not enough data: {len(graded)}/{MIN_PREDICTIONS_FOR_IMPROVEMENT} graded predictions")
        return {"improved": False, "reason": "insufficient_data"}

    # Check if improvement was run recently
    active = get_active_instruction_version()
    if active and active.get("created_at"):
        try:
            last_updated = datetime.fromisoformat(active["created_at"].replace("Z", "+00:00"))
            days_since = (datetime.now(timezone.utc) - last_updated).days
            if days_since < IMPROVEMENT_INTERVAL_DAYS:
                print(f"  Last improvement was {days_since} days ago (min {IMPROVEMENT_INTERVAL_DAYS})")
                return {"improved": False, "reason": "too_recent"}
        except (ValueError, TypeError):
            pass

    # Run self-improvement
    try:
        from pipeline.self_improver import run_self_improvement
        result = await run_self_improvement(graded)
        print(f"\n  Improvement result: {'Applied' if result.get('applied') else 'Skipped'}")
        return result
    except Exception as e:
        print(f"  ERROR during improvement: {e}")
        return {"improved": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Status Report
# ---------------------------------------------------------------------------

async def status_report():
    """Print a status report with accuracy metrics and credit usage."""
    print(f"\n{'='*60}")
    print(f"  PIPELINE STATUS REPORT — {date.today()}")
    print(f"{'='*60}\n")

    # Credit usage
    try:
        credits = get_monthly_credits_used()
        print(f"  Credits used this month: {credits}/480")
    except Exception as e:
        print(f"  Credits: unable to fetch ({e})")
        print("  Have you run the supabase_schema.sql in your Supabase Dashboard?")
        return

    # Active instruction version
    active = get_active_instruction_version()
    if active:
        print(f"  Active instruction version: v{active.get('version_number', '?')}")
        print(f"  Predictions on this version: {active.get('predictions_count', '?')}")
        print(f"  Hit rate on this version: {active.get('hit_rate', 'N/A')}")
    else:
        print("  No active instruction version (run 'seed' first)")

    # Recent performance
    logs = get_performance_logs("daily", limit=7)
    if logs:
        print(f"\n  Last {len(logs)} days performance:")
        print(f"  {'Date':<12} {'Total':<7} {'Hits':<6} {'Miss':<6} {'Rate':<7}")
        print(f"  {'-'*38}")
        for log in logs:
            total = log.get("total_predictions", 0)
            hits = log.get("hits", 0)
            misses = log.get("misses", 0)
            rate = log.get("hit_rate", 0)
            print(f"  {log.get('period_start', '?'):<12} {total:<7} {hits:<6} {misses:<6} {rate:<7.1%}")

        # Aggregate stats
        total_preds = sum(l.get("total_predictions", 0) for l in logs)
        total_hits = sum(l.get("hits", 0) for l in logs)
        total_misses = sum(l.get("misses", 0) for l in logs)
        if total_hits + total_misses > 0:
            overall_rate = total_hits / (total_hits + total_misses)
            print(f"\n  7-day overall: {total_preds} predictions, {overall_rate:.1%} hit rate")
    else:
        print("\n  No performance data yet. Run predict → grade cycle first.")

    # Stat breakdown from latest log
    if logs:
        latest = logs[0]
        breakdown = latest.get("stat_breakdown", {})
        if breakdown:
            print(f"\n  Stat breakdown (latest day):")
            for stat, data in breakdown.items():
                total = data.get("total", 0)
                hits = data.get("hits", 0)
                rate = hits / total if total > 0 else 0
                print(f"    {stat}: {hits}/{total} ({rate:.0%})")

    print(f"\n{'='*60}\n")


# ---------------------------------------------------------------------------
# Seed Instructions
# ---------------------------------------------------------------------------

async def seed_instructions():
    """Store the current PREDICTION_AGENT_INSTRUCTIONS as version 1."""
    print("\n  Seeding initial instruction version...")

    existing = get_active_instruction_version()
    if existing:
        print(f"  Active version already exists: v{existing.get('version_number', '?')}")
        return

    version_num = get_latest_version_number() + 1
    insert_instruction_version({
        "version_number": version_num,
        "instructions_text": PREDICTION_AGENT_INSTRUCTIONS,
        "extracted_params": _extract_params(PREDICTION_AGENT_INSTRUCTIONS),
        "change_reason": "Initial seed from base prediction agent instructions",
        "predictions_count": 0,
        "hit_rate": None,
    })
    print(f"  Seeded instruction version v{version_num}")


def _extract_params(instructions: str) -> dict:
    """Extract tunable parameters from instruction text."""
    return {
        "base_rate_weight": 40,
        "matchup_weight": 15,
        "recent_form_weight": 15,
        "defense_weight": 20,
        "context_weight": 10,
        "high_conf_min": 75,
        "high_conf_max": 90,
        "medium_conf_min": 55,
        "medium_conf_max": 74,
        "low_conf_min": 50,
        "low_conf_max": 54,
        "hit_rate_strong_over": 65,
        "hit_rate_strong_under": 35,
        "elite_defense_threshold": 108,
        "poor_defense_threshold": 112,
        "b2b_penalty_pct": 7.5,
    }


# ---------------------------------------------------------------------------
# Continuous Loop
# ---------------------------------------------------------------------------

async def run_loop():
    """Run the pipeline continuously on schedule.

    Schedule (US Eastern):
    - 4:00 PM ET → Predict phase (fetch today's props, run predictions)
    - 8:00 AM ET → Grade phase (grade yesterday's predictions)
    - 9:00 AM ET → Improve phase (every 3 days, self-tune instructions)

    The process runs forever, sleeping 15 minutes between checks.
    Use Ctrl+C to stop, or run in the background with nohup/screen/tmux.
    """
    print(f"\n{'='*60}")
    print(f"  PIPELINE LOOP STARTED — {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")
    print(f"  Schedule:")
    print(f"    4:00 PM ET  → Predict (fetch props + run predictions)")
    print(f"    8:00 AM ET  → Grade (check yesterday's results)")
    print(f"    9:00 AM ET  → Improve (every 3 days, self-tune)")
    print(f"  Press Ctrl+C to stop.")
    print(f"{'='*60}\n")

    last_predict_date = None
    last_grade_date = None
    last_improve_date = None

    while True:
        now = datetime.now(ET)
        today = now.date()
        hour = now.hour

        # Grade at 8 AM ET (08:00) — grade yesterday's predictions
        if hour >= 8 and last_grade_date != today:
            print(f"\n  [{now.strftime('%H:%M ET')}] Triggering grade phase...")
            try:
                await grade_phase()
            except Exception as e:
                print(f"  ERROR in grade phase: {e}")
            last_grade_date = today

        # Improve at 9 AM ET — runs every day but the 3-day interval
        # check inside improve_phase() controls actual frequency
        if hour >= 9 and last_improve_date != today:
            print(f"\n  [{now.strftime('%H:%M ET')}] Checking if improvement is due...")
            try:
                await improve_phase()
            except Exception as e:
                print(f"  ERROR in improve phase: {e}")
            last_improve_date = today

        # Predict at 4 PM ET (16:00) — fetch today's props
        if hour >= 16 and last_predict_date != today:
            print(f"\n  [{now.strftime('%H:%M ET')}] Triggering predict phase...")
            try:
                await predict_phase()
            except Exception as e:
                print(f"  ERROR in predict phase: {e}")
            last_predict_date = today

        # Sleep for 15 minutes before checking again
        await asyncio.sleep(900)
