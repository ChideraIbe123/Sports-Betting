"""Fetch NBA player prop lines from The Odds API (DraftKings)."""

import httpx

from pipeline.config import ODDS_API_KEY, ODDS_BASE_URL, MARKETS, MONTHLY_CREDIT_BUDGET, ODDS_MARKET_TO_STAT
from pipeline.db import get_monthly_credits_used, insert_credit_usage


# Top NBA stars — games with these players are prioritised for predictions
PRIORITY_PLAYERS = {
    "LeBron James", "Kevin Durant", "Stephen Curry", "Giannis Antetokounmpo",
    "Nikola Jokic", "Luka Doncic", "Jayson Tatum", "Joel Embiid",
    "Anthony Davis", "Donovan Mitchell", "Shai Gilgeous-Alexander",
    "Damian Lillard", "Trae Young", "Devin Booker", "Kyrie Irving",
    "Jalen Brunson", "Anthony Edwards", "Ja Morant", "Jaylen Brown",
    "De'Aaron Fox", "LaMelo Ball", "Darius Garland", "Tyrese Haliburton",
    "Bam Adebayo", "Karl-Anthony Towns", "Chet Holmgren", "Victor Wembanyama",
    "Paolo Banchero", "Zion Williamson", "Jimmy Butler",
}

# Name corrections: Odds API name → nba_api-compatible name
NAME_CORRECTIONS = {
    "PJ Washington": "P.J. Washington",
    "CJ McCollum": "C.J. McCollum",
    "OG Anunoby": "O.G. Anunoby",
    "Nic Claxton": "Nicolas Claxton",
    "Herb Jones": "Herbert Jones",
}


class CreditBudgetExceeded(Exception):
    pass


def normalize_player_name(name: str) -> str:
    """Normalize player name from Odds API for nba_api compatibility."""
    return NAME_CORRECTIONS.get(name, name)


def decimal_to_american(decimal_odds: float | None) -> int | None:
    """Convert decimal odds (e.g. 2.14) to American odds (e.g. +114)."""
    if decimal_odds is None:
        return None
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    else:
        return round(-100 / (decimal_odds - 1))


async def fetch_todays_events() -> list[dict]:
    """Fetch today's NBA events from The Odds API (0 credits)."""
    url = f"{ODDS_BASE_URL}/sports/basketball_nba/events"
    params = {"apiKey": ODDS_API_KEY}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def score_event(event: dict) -> float:
    """Score an event for priority selection. Higher = more interesting."""
    score = 1.0
    home = event.get("home_team", "")
    away = event.get("away_team", "")

    # Boost for teams with star players (rough heuristic by team name)
    for player in PRIORITY_PLAYERS:
        last_name = player.split()[-1].lower()
        if last_name in home.lower() or last_name in away.lower():
            score += 0.5

    # All games get a base score so we still pick some even without star matching
    return score


def select_events(events: list[dict], max_games: int = 3) -> list[dict]:
    """Select the top N events by priority score."""
    if len(events) <= max_games:
        return events

    scored = [(score_event(e), e) for e in events]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:max_games]]


async def fetch_player_props(event_id: str, event_info: dict) -> list[dict]:
    """Fetch DraftKings player props for a specific event.

    Costs len(MARKETS) credits (typically 4).
    Returns list of prop dicts ready for prediction.
    """
    credits_used = get_monthly_credits_used()
    cost = len(MARKETS)
    if credits_used + cost > MONTHLY_CREDIT_BUDGET:
        raise CreditBudgetExceeded(
            f"Monthly budget exceeded: {credits_used}/{MONTHLY_CREDIT_BUDGET} used, "
            f"need {cost} more"
        )

    url = f"{ODDS_BASE_URL}/sports/basketball_nba/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": ",".join(MARKETS),
        "bookmakers": "draftkings",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()

    # Log credit usage
    insert_credit_usage(cost, event_id, MARKETS)

    return _parse_props_response(resp.json(), event_info)


def _parse_props_response(data: dict, event_info: dict) -> list[dict]:
    """Extract individual player props from The Odds API response.

    The response structure:
    {
        "bookmakers": [{
            "key": "draftkings",
            "markets": [{
                "key": "player_points",
                "outcomes": [
                    {"name": "Over", "description": "LeBron James", "price": -110, "point": 25.5},
                    {"name": "Under", "description": "LeBron James", "price": -110, "point": 25.5},
                ]
            }]
        }]
    }
    """
    props = []
    bookmakers = data.get("bookmakers", [])

    for bookmaker in bookmakers:
        if bookmaker.get("key") != "draftkings":
            continue

        for market in bookmaker.get("markets", []):
            market_key = market.get("key", "")
            if market_key not in ODDS_MARKET_TO_STAT:
                continue

            stat_type, stat_column = ODDS_MARKET_TO_STAT[market_key]

            # Group outcomes by player (Over/Under pairs)
            player_lines = {}
            for outcome in market.get("outcomes", []):
                player_name = outcome.get("description", "")
                if not player_name:
                    continue

                direction = outcome.get("name", "").lower()  # "over" or "under"
                line = outcome.get("point")
                price = outcome.get("price")

                if player_name not in player_lines:
                    player_lines[player_name] = {"line": line}
                if direction == "over":
                    player_lines[player_name]["over_odds"] = decimal_to_american(price)
                elif direction == "under":
                    player_lines[player_name]["under_odds"] = decimal_to_american(price)

            for player_name, line_data in player_lines.items():
                if line_data.get("line") is None:
                    continue
                props.append({
                    "player_name": normalize_player_name(player_name),
                    "stat_type": stat_type,
                    "stat_column": stat_column,
                    "line": line_data["line"],
                    "over_odds": line_data.get("over_odds"),
                    "under_odds": line_data.get("under_odds"),
                    "market_key": market_key,
                    "event_id": data.get("id", ""),
                    "home_team": event_info.get("home_team", ""),
                    "away_team": event_info.get("away_team", ""),
                })

    return props
