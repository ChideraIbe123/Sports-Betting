"""Bet parsing and opponent lookup tools."""

import json
import re
import time
from datetime import datetime, timedelta

from agents import function_tool
from nba_api.stats.static import players, teams
from nba_api.stats.endpoints import ScoreboardV2


# Mapping of common stat terms to nba_api column names (or combo keys)
STAT_MAPPING = {
    "points": "PTS",
    "pts": "PTS",
    "point": "PTS",
    "rebounds": "REB",
    "rebs": "REB",
    "reb": "REB",
    "rebound": "REB",
    "assists": "AST",
    "ast": "AST",
    "assist": "AST",
    "steals": "STL",
    "stl": "STL",
    "steal": "STL",
    "blocks": "BLK",
    "blk": "BLK",
    "block": "BLK",
    "threes": "FG3M",
    "3pt": "FG3M",
    "3pts": "FG3M",
    "three pointers": "FG3M",
    "three pointer": "FG3M",
    "3-pointers": "FG3M",
    "3 pointers": "FG3M",
    "3s": "FG3M",
    "turnovers": "TOV",
    "tov": "TOV",
    "turnover": "TOV",
    "minutes": "MIN",
    "min": "MIN",
    "fg": "FGM",
    "field goals": "FGM",
    "ft": "FTM",
    "free throws": "FTM",
    # Combo stats
    "pra": "PRA",
    "points rebounds assists": "PRA",
    "pts rebs asts": "PRA",
    "pts+rebs+asts": "PRA",
    "pr": "PR",
    "points rebounds": "PR",
    "pts+rebs": "PR",
    "pa": "PA",
    "points assists": "PA",
    "pts+asts": "PA",
    "ra": "RA",
    "rebounds assists": "RA",
    "rebs+asts": "RA",
    "stocks": "STOCKS",
    "steals blocks": "STOCKS",
    "steals+blocks": "STOCKS",
    "stl+blk": "STOCKS",
}

# Combo stat definitions: which base columns to sum
COMBO_STATS = {
    "PRA": ["PTS", "REB", "AST"],
    "PR": ["PTS", "REB"],
    "PA": ["PTS", "AST"],
    "RA": ["REB", "AST"],
    "STOCKS": ["STL", "BLK"],
}


def is_combo_stat(stat_column: str) -> bool:
    """Check if a stat column is a combo stat."""
    return stat_column in COMBO_STATS


def get_combo_components(stat_column: str) -> list[str]:
    """Get the base columns for a combo stat."""
    return COMBO_STATS.get(stat_column, [stat_column])


def compute_combo_value(game: dict, stat_column: str) -> float | None:
    """Compute the value of a stat (single or combo) from a game dict."""
    if stat_column in COMBO_STATS:
        components = COMBO_STATS[stat_column]
        values = [game.get(col) for col in components]
        if any(v is None for v in values):
            return None
        return sum(float(v) for v in values)
    else:
        val = game.get(stat_column)
        return float(val) if val is not None else None


def get_current_season() -> str:
    """Get the current NBA season string (e.g., '2025-26')."""
    now = datetime.now()
    if now.month >= 10:
        return f"{now.year}-{str(now.year + 1)[-2:]}"
    else:
        return f"{now.year - 1}-{str(now.year)[-2:]}"


def find_player(name: str) -> dict | None:
    """Find an NBA player by name (fuzzy match)."""
    name_lower = name.lower().strip()

    # Try exact match first (escape name since nba_api treats it as regex)
    matches = players.find_players_by_full_name(re.escape(name))
    if matches:
        active = [p for p in matches if p["is_active"]]
        return active[0] if active else matches[0]

    # Try last name
    parts = name_lower.split()
    if parts:
        last_name = parts[-1]
        matches = players.find_players_by_last_name(re.escape(last_name))
        if matches:
            active = [p for p in matches if p["is_active"]]
            if active:
                # If first name was given, try to match it
                if len(parts) > 1:
                    first = parts[0]
                    for p in active:
                        if p["first_name"].lower().startswith(first):
                            return p
                return active[0]
            return matches[0]

    return None


def _parse_bet_prompt(prompt: str) -> dict:
    """Parse a betting prompt into structured data. Returns a dict (not JSON string)."""
    prompt = prompt.strip()

    # Extract over/under
    over_under = "over"
    prompt_lower = prompt.lower()
    if "under" in prompt_lower:
        over_under = "under"
        prompt = re.sub(r"\bunder\b", "", prompt, flags=re.IGNORECASE).strip()
    elif "over" in prompt_lower:
        prompt = re.sub(r"\bover\b", "", prompt, flags=re.IGNORECASE).strip()

    # Extract the line (number)
    line_match = re.search(r"(\d+\.?\d*)", prompt)
    if not line_match:
        return {"error": "Could not find a betting line (number) in the prompt"}
    line = float(line_match.group(1))
    prompt = prompt[:line_match.start()] + prompt[line_match.end():]

    # Extract stat type - try multi-word terms first (sorted by length desc)
    prompt_clean = prompt.strip().lower()
    stat_type = None
    stat_column = None
    sorted_terms = sorted(STAT_MAPPING.keys(), key=len, reverse=True)
    for term in sorted_terms:
        if term in prompt_clean:
            stat_type = term
            stat_column = STAT_MAPPING[term]
            prompt_clean = prompt_clean.replace(term, "").strip()
            prompt = re.sub(re.escape(term), "", prompt, flags=re.IGNORECASE).strip()
            break

    if not stat_column:
        return {"error": f"Could not identify stat type. Supported: {list(set(STAT_MAPPING.values()))}"}

    # Remaining text should be the player name
    player_name = re.sub(r"\s+", " ", prompt).strip()
    player_name = player_name.strip("- ,.+/")

    if not player_name:
        return {"error": "Could not identify player name in the prompt"}

    # Look up the player
    player = find_player(player_name)
    if not player:
        return {"error": f"Could not find NBA player: {player_name}"}

    return {
        "player_name": player["full_name"],
        "player_id": player["id"],
        "stat_type": stat_type,
        "stat_column": stat_column,
        "line": line,
        "over_under": over_under,
    }


def _check_back_to_back(team_id: int) -> bool:
    """Check if a team played yesterday (back-to-back)."""
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%m/%d/%Y")
        time.sleep(0.6)
        yesterday_sb = ScoreboardV2(game_date=yesterday)
        yesterday_games = yesterday_sb.get_normalized_dict().get("GameHeader", [])
        for game in yesterday_games:
            if team_id in (game["HOME_TEAM_ID"], game["VISITOR_TEAM_ID"]):
                return True
    except Exception:
        pass
    return False


def _find_today_opponent(player_name: str) -> dict:
    """Find today's opponent. Returns a dict (not JSON string)."""
    player = find_player(player_name)
    if not player:
        return {"error": f"Could not find player: {player_name}"}

    from nba_api.stats.endpoints import CommonPlayerInfo
    time.sleep(0.6)
    player_info = CommonPlayerInfo(player_id=player["id"])
    player_data = player_info.get_normalized_dict()
    team_id = player_data["CommonPlayerInfo"][0]["TEAM_ID"]
    team_abbr = player_data["CommonPlayerInfo"][0]["TEAM_ABBREVIATION"]
    team_name = player_data["CommonPlayerInfo"][0]["TEAM_NAME"]
    team_city = player_data["CommonPlayerInfo"][0]["TEAM_CITY"]

    # Check today's scoreboard
    today = datetime.now().strftime("%m/%d/%Y")
    time.sleep(0.6)
    scoreboard = ScoreboardV2(game_date=today)
    games = scoreboard.get_normalized_dict()

    game_header = games.get("GameHeader", [])
    for game in game_header:
        home_team_id = game["HOME_TEAM_ID"]
        away_team_id = game["VISITOR_TEAM_ID"]

        if team_id in (home_team_id, away_team_id):
            opponent_id = away_team_id if team_id == home_team_id else home_team_id
            is_home = team_id == home_team_id

            all_teams = teams.get_teams()
            opponent = next((t for t in all_teams if t["id"] == opponent_id), None)

            # Check if back-to-back (team played yesterday)
            is_b2b = _check_back_to_back(team_id)

            return {
                "player_name": player["full_name"],
                "player_team": f"{team_city} {team_name}",
                "player_team_abbr": team_abbr,
                "player_team_id": team_id,
                "opponent_name": opponent["full_name"] if opponent else "Unknown",
                "opponent_abbr": opponent["abbreviation"] if opponent else "UNK",
                "opponent_id": opponent_id,
                "is_home": is_home,
                "is_back_to_back": is_b2b,
                "game_date": today,
            }

    return {
        "error": (
            f"{team_city} {team_name} does not appear to have a game scheduled today ({today}). "
            "The prediction will proceed with general analysis without opponent-specific data."
        ),
        "player_name": player["full_name"],
        "player_team": f"{team_city} {team_name}",
        "player_team_abbr": team_abbr,
        "player_team_id": team_id,
        "no_game_today": True,
    }


def is_parlay(prompt: str) -> bool:
    """Check if a prompt contains multiple legs (parlay)."""
    # Match " AND " (case-insensitive) or ", " as leg separators
    # Don't use "+" since stat terms like "pts+rebs+asts" use it
    return bool(re.search(r'\s+AND\s+|,\s+', prompt, re.IGNORECASE))


def parse_parlay_prompt(prompt: str) -> dict:
    """Split a parlay prompt into individual legs and parse each one.

    Supports separators: " AND " (case-insensitive), ", "
    Examples:
        "Kevin Durant 27.5 points over AND LeBron James 10.5 rebounds over"
        "Brunson 6.5 assists over, Tatum 27.5 points over"
    """
    leg_prompts = re.split(r'\s+AND\s+|,\s+', prompt, flags=re.IGNORECASE)

    legs = []
    errors = []
    for leg_prompt in leg_prompts:
        leg_prompt = leg_prompt.strip()
        if not leg_prompt:
            continue
        parsed = _parse_bet_prompt(leg_prompt)
        parsed["raw_prompt"] = leg_prompt
        if "error" in parsed and "player_id" not in parsed:
            errors.append(parsed["error"])
        legs.append(parsed)

    if errors and not legs:
        return {"error": "; ".join(errors), "legs": [], "num_legs": 0}

    return {"legs": legs, "num_legs": len(legs)}


# --- function_tool wrappers (for use by AI agents) ---

@function_tool
def parse_bet_prompt(prompt: str) -> str:
    """Parse a natural language betting prompt into structured data.

    Examples:
        "Duncan Robinson 8 points over" → player, stat, line, direction
        "LeBron James 25.5 pts under" → player, stat, line, direction
        "Steph Curry 4.5 threes over" → player, stat, line, direction
    """
    try:
        return json.dumps(_parse_bet_prompt(prompt))
    except Exception as e:
        return json.dumps({"error": f"Failed to parse bet prompt: {str(e)}"})


@function_tool
def find_today_opponent(player_name: str) -> str:
    """Find the opponent team for a player's game today.

    Returns the opponent team info if the player's team is playing today.
    """
    try:
        return json.dumps(_find_today_opponent(player_name))
    except Exception as e:
        return json.dumps({"error": f"Failed to find today's opponent: {str(e)}"})
