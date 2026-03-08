"""Player statistics and defensive matchup tools via nba_api."""

import json
import statistics
import time
from datetime import datetime

from agents import function_tool
from nba_api.stats.endpoints import (
    PlayerGameLog,
    PlayerDashboardByGeneralSplits,
    LeagueDashTeamStats,
)
from nba_api.stats.static import teams

from tools.parser_tools import get_current_season, compute_combo_value, is_combo_stat
from tools.cache import cached_api_call


def _rate_limit():
    """Sleep to avoid NBA.com rate limiting."""
    time.sleep(0.6)


def _get_game_log(player_id: int, season: str) -> list[dict]:
    """Get player game log with caching. Returns list of game dicts."""
    cache_key = f"PlayerGameLog:{player_id}:{season}"

    def fetch():
        _rate_limit()
        gl = PlayerGameLog(
            player_id=player_id,
            season=season,
            season_type_all_star="Regular Season",
        )
        return gl.get_normalized_dict()["PlayerGameLog"]

    return cached_api_call(cache_key, fetch, ttl=300)


def _extract_stat_values(games: list[dict], stat_column: str) -> list[float]:
    """Extract stat values from games, handling both single and combo stats."""
    values = []
    for game in games:
        val = compute_combo_value(game, stat_column)
        if val is not None:
            values.append(val)
    return values


@function_tool
def get_player_season_stats(player_id: int, stat_column: str, line: float = 0.0) -> str:
    """Get a player's season stats with averages, variance, hit rate, and trend.

    Args:
        player_id: NBA player ID
        stat_column: Stat column name (PTS, REB, AST, STL, BLK, FG3M, TOV, MIN, FGM, FTM) or combo (PRA, PR, PA, RA, STOCKS)
        line: The betting line to calculate hit rate against (default 0.0 = skip hit rate)
    """
    try:
        season = get_current_season()
        games = _get_game_log(player_id, season)

        if not games:
            return json.dumps({"error": f"No games found for player {player_id} in {season}"})

        stat_values = _extract_stat_values(games, stat_column)
        if not stat_values:
            return json.dumps({"error": f"No data for stat column {stat_column}"})

        season_avg = sum(stat_values) / len(stat_values)
        last5 = stat_values[:5]
        last10 = stat_values[:10]
        last5_avg = sum(last5) / len(last5) if last5 else 0
        last10_avg = sum(last10) / len(last10) if last10 else 0

        # Trend
        trend = "stable"
        if last5_avg > season_avg * 1.1:
            trend = "trending_up"
        elif last5_avg < season_avg * 0.9:
            trend = "trending_down"

        # Variance & consistency
        std_dev = round(statistics.stdev(stat_values), 1) if len(stat_values) > 1 else 0.0
        median = round(statistics.median(stat_values), 1)

        result = {
            "player_id": player_id,
            "season": season,
            "stat_column": stat_column,
            "is_combo_stat": is_combo_stat(stat_column),
            "games_played": len(stat_values),
            "season_avg": round(season_avg, 1),
            "median": median,
            "std_dev": std_dev,
            "last_5_avg": round(last5_avg, 1),
            "last_10_avg": round(last10_avg, 1),
            "last_5_values": [round(v, 1) for v in last5],
            "season_high": round(max(stat_values), 1),
            "season_low": round(min(stat_values), 1),
            "trend": trend,
        }

        # Hit rate (if line provided)
        if line > 0:
            hit_count = sum(1 for v in stat_values if v > line)
            hit_count_last10 = sum(1 for v in last10 if v > line)
            hit_count_last5 = sum(1 for v in last5 if v > line)
            result["hit_rate"] = {
                "line": line,
                "season_pct": round(hit_count / len(stat_values) * 100, 1),
                "season_hits": f"{hit_count}/{len(stat_values)}",
                "last_10_pct": round(hit_count_last10 / len(last10) * 100, 1) if last10 else 0,
                "last_10_hits": f"{hit_count_last10}/{len(last10)}",
                "last_5_pct": round(hit_count_last5 / len(last5) * 100, 1) if last5 else 0,
                "last_5_hits": f"{hit_count_last5}/{len(last5)}",
            }

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to get season stats: {str(e)}"})


@function_tool
def get_player_vs_team_stats(player_id: int, opponent_abbr: str, stat_column: str, line: float = 0.0) -> str:
    """Get a player's historical stats against a specific opponent team (last 3 seasons).

    Args:
        player_id: NBA player ID
        opponent_abbr: Opponent team abbreviation (e.g., 'LAL', 'BOS')
        stat_column: Stat column name (PTS, REB, AST, etc.) or combo (PRA, PR, PA, RA, STOCKS)
        line: The betting line to calculate vs-team hit rate (default 0.0 = skip)
    """
    try:
        current_season = get_current_season()
        year = int(current_season.split("-")[0])
        seasons = [
            f"{year}-{str(year + 1)[-2:]}",
            f"{year - 1}-{str(year)[-2:]}",
            f"{year - 2}-{str(year - 1)[-2:]}",
        ]

        all_matchup_games = []
        for season in seasons:
            try:
                games = _get_game_log(player_id, season)
                for game in games:
                    matchup = game.get("MATCHUP", "")
                    if opponent_abbr.upper() in matchup.upper():
                        val = compute_combo_value(game, stat_column)
                        if val is not None:
                            all_matchup_games.append({
                                "date": game["GAME_DATE"],
                                "value": round(val, 1),
                                "matchup": matchup,
                                "season": season,
                                "min": game.get("MIN", 0),
                            })
            except Exception:
                continue

        if not all_matchup_games:
            return json.dumps({
                "error": f"No matchup history found vs {opponent_abbr}",
                "player_id": player_id,
                "opponent": opponent_abbr,
            })

        values = [g["value"] for g in all_matchup_games]
        avg = sum(values) / len(values)

        result = {
            "player_id": player_id,
            "opponent": opponent_abbr,
            "stat_column": stat_column,
            "total_games": len(all_matchup_games),
            "avg_vs_team": round(avg, 1),
            "high_vs_team": round(max(values), 1),
            "low_vs_team": round(min(values), 1),
            "games": all_matchup_games[:6],
        }

        if line > 0:
            hit_count = sum(1 for v in values if v > line)
            result["hit_rate_vs_team"] = {
                "line": line,
                "pct": round(hit_count / len(values) * 100, 1),
                "hits": f"{hit_count}/{len(values)}",
            }

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to get vs team stats: {str(e)}"})


@function_tool
def get_player_recent_games(player_id: int) -> str:
    """Get a player's last 5 games with full box score details.

    Args:
        player_id: NBA player ID
    """
    try:
        season = get_current_season()
        games = _get_game_log(player_id, season)

        if not games:
            return json.dumps({"error": "No recent games found"})

        recent = []
        for game in games[:5]:
            recent.append({
                "date": game["GAME_DATE"],
                "matchup": game["MATCHUP"],
                "result": game["WL"],
                "min": game["MIN"],
                "pts": game["PTS"],
                "reb": game["REB"],
                "ast": game["AST"],
                "stl": game["STL"],
                "blk": game["BLK"],
                "fg3m": game["FG3M"],
                "tov": game["TOV"],
                "fgm": game["FGM"],
                "fga": game["FGA"],
                "ftm": game["FTM"],
                "fta": game["FTA"],
                "pra": game["PTS"] + game["REB"] + game["AST"],
                "stocks": game["STL"] + game["BLK"],
            })

        return json.dumps({
            "player_id": player_id,
            "recent_games": recent,
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to get recent games: {str(e)}"})


@function_tool
def get_player_home_away_splits(player_id: int, stat_column: str) -> str:
    """Get a player's home vs away performance splits.

    Args:
        player_id: NBA player ID
        stat_column: Stat column name (PTS, REB, AST, etc.) or combo (PRA, PR, PA, RA, STOCKS)
    """
    try:
        season = get_current_season()
        games = _get_game_log(player_id, season)

        if not games:
            return json.dumps({"error": "No games found"})

        home_values = []
        away_values = []
        for game in games:
            val = compute_combo_value(game, stat_column)
            if val is None:
                continue
            matchup = game.get("MATCHUP", "")
            if "vs." in matchup:
                home_values.append(val)
            elif "@" in matchup:
                away_values.append(val)

        home_avg = round(sum(home_values) / len(home_values), 1) if home_values else 0
        away_avg = round(sum(away_values) / len(away_values), 1) if away_values else 0

        return json.dumps({
            "player_id": player_id,
            "stat_column": stat_column,
            "home_avg": home_avg,
            "home_games": len(home_values),
            "away_avg": away_avg,
            "away_games": len(away_values),
            "home_away_diff": round(home_avg - away_avg, 1),
            "better_at": "home" if home_avg > away_avg else "away" if away_avg > home_avg else "neutral",
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to get home/away splits: {str(e)}"})


@function_tool
def get_player_advanced_stats(player_id: int) -> str:
    """Get a player's advanced dashboard stats including shooting splits and home/away.

    Args:
        player_id: NBA player ID
    """
    try:
        season = get_current_season()
        cache_key = f"PlayerDashboard:{player_id}:{season}"

        def fetch():
            _rate_limit()
            return PlayerDashboardByGeneralSplits(
                player_id=player_id,
                season=season,
            ).get_normalized_dict()

        data = cached_api_call(cache_key, fetch, ttl=300)

        overall = data.get("OverallPlayerDashboard", [])
        if not overall:
            return json.dumps({"error": "No advanced stats available", "player_id": player_id})

        row = overall[0]
        result = {
            "player_id": player_id,
            "games_played": row.get("GP", 0),
            "min_per_game": round(row.get("MIN", 0), 1),
            "pts": round(row.get("PTS", 0), 1),
            "reb": round(row.get("REB", 0), 1),
            "ast": round(row.get("AST", 0), 1),
            "fg_pct": round(row.get("FG_PCT", 0) * 100, 1),
            "fg3_pct": round(row.get("FG3_PCT", 0) * 100, 1),
            "ft_pct": round(row.get("FT_PCT", 0) * 100, 1),
            "plus_minus": round(row.get("PLUS_MINUS", 0), 1),
        }

        # Extract home/away splits if available
        location = data.get("LocationPlayerDashboard", [])
        for split in location:
            group = split.get("GROUP_VALUE", "")
            if group == "Home":
                result["home_pts"] = round(split.get("PTS", 0), 1)
                result["home_min"] = round(split.get("MIN", 0), 1)
            elif group == "Road":
                result["away_pts"] = round(split.get("PTS", 0), 1)
                result["away_min"] = round(split.get("MIN", 0), 1)

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Failed to get advanced stats: {str(e)}"})


@function_tool
def get_team_defensive_rating(team_abbreviation: str) -> str:
    """Get a team's defensive rating and defensive stats.

    Args:
        team_abbreviation: Team abbreviation (e.g., 'LAL', 'BOS')
    """
    try:
        all_teams = teams.get_teams()
        team = next(
            (t for t in all_teams if t["abbreviation"].upper() == team_abbreviation.upper()),
            None,
        )
        if not team:
            return json.dumps({"error": f"Team not found: {team_abbreviation}"})

        season = get_current_season()

        # Use LeagueDashTeamStats with Opponent measure type for opponent FG%
        cache_key = f"LeagueDashTeam:Opponent:{season}"

        def fetch():
            _rate_limit()
            return LeagueDashTeamStats(
                season=season,
                measure_type_detailed_defense="Opponent",
            ).get_normalized_dict()

        data = cached_api_call(cache_key, fetch, ttl=300)
        team_stats = data.get("LeagueDashTeamStats", [])

        for row in team_stats:
            if row.get("TEAM_ID") == team["id"]:
                return json.dumps({
                    "team": team_abbreviation,
                    "team_name": team["full_name"],
                    "games_played": row.get("GP", 0),
                    "wins": row.get("W", 0),
                    "losses": row.get("L", 0),
                    "opp_fg_pct": round(row.get("OPP_FG_PCT", 0) * 100, 1) if row.get("OPP_FG_PCT") else None,
                    "opp_fg3_pct": round(row.get("OPP_FG3_PCT", 0) * 100, 1) if row.get("OPP_FG3_PCT") else None,
                    "opp_pts": round(row.get("OPP_PTS", 0), 1) if row.get("OPP_PTS") else None,
                    "note": "Lower opponent FG% indicates better defense. Compare to league average (~46%).",
                })

        return json.dumps({"error": f"Defensive data not found for {team_abbreviation}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to get defensive rating: {str(e)}"})


@function_tool
def get_team_pace(team_abbreviation: str) -> str:
    """Get a team's pace (possessions per game) and related tempo stats.

    Higher pace = more possessions = more stat opportunities for all players.

    Args:
        team_abbreviation: Team abbreviation (e.g., 'LAL', 'BOS')
    """
    try:
        # Resolve team abbreviation to team ID
        all_teams = teams.get_teams()
        team = next(
            (t for t in all_teams if t["abbreviation"].upper() == team_abbreviation.upper()),
            None,
        )
        if not team:
            return json.dumps({"error": f"Team not found: {team_abbreviation}"})

        season = get_current_season()
        cache_key = f"LeagueDashTeam:Advanced:{season}"

        def fetch():
            _rate_limit()
            return LeagueDashTeamStats(
                season=season,
                measure_type_detailed_defense="Advanced",
            ).get_normalized_dict()

        data = cached_api_call(cache_key, fetch, ttl=300)
        team_stats = data.get("LeagueDashTeamStats", [])

        for row in team_stats:
            if row.get("TEAM_ID") == team["id"]:
                return json.dumps({
                    "team": team_abbreviation,
                    "team_name": team["full_name"],
                    "pace": round(row.get("PACE", 0), 1),
                    "off_rating": round(row.get("OFF_RATING", 0), 1),
                    "def_rating": round(row.get("DEF_RATING", 0), 1),
                    "net_rating": round(row.get("NET_RATING", 0), 1),
                    "note": "League average pace is ~100. Higher pace = more stat opportunities.",
                })

        return json.dumps({"error": f"Pace data not found for {team_abbreviation}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to get team pace: {str(e)}"})


@function_tool
def get_injury_report() -> str:
    """Get the current NBA injury report from basketball-reference."""
    try:
        from basketball_reference_scraper.injury_report import injury_report

        report = injury_report()

        if report.empty:
            return json.dumps({"injuries": [], "note": "No injuries reported or unable to fetch"})

        injuries = []
        for _, row in report.head(50).iterrows():
            injuries.append({
                "player": str(row.get("Player", "")),
                "team": str(row.get("Team", "")),
                "date": str(row.get("Date", "")),
                "status": str(row.get("Status", "")),
                "description": str(row.get("Description", "")),
            })

        return json.dumps({"injuries": injuries, "total": len(report)})
    except Exception as e:
        return json.dumps({"error": f"Failed to get injury report: {str(e)}", "injuries": []})
