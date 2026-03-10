"""Pipeline configuration — Supabase client, Odds API, and constants."""

import os

from supabase import create_client

# Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# The Odds API
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
if not ODDS_API_KEY:
    raise RuntimeError("ODDS_API_KEY must be set in .env")
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"

# Budget
MONTHLY_CREDIT_BUDGET = 480  # leave 20-credit buffer from 500 free
MAX_GAMES_PER_DAY = 3
MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
]

# Stat mapping: Odds API market key → (stat_type for prompt, stat_column for nba_api)
ODDS_MARKET_TO_STAT = {
    "player_points": ("points", "PTS"),
    "player_rebounds": ("rebounds", "REB"),
    "player_assists": ("assists", "AST"),
    "player_threes": ("threes", "FG3M"),
}

# Self-improvement
MIN_PREDICTIONS_FOR_IMPROVEMENT = 5
IMPROVEMENT_INTERVAL_DAYS = 3
