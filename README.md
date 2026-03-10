# NBA Betting Predictor

AI-powered NBA player prop prediction system using multi-agent architecture. Enter a bet like "Donovan Mitchell 24.5 points over" and get a data-driven prediction with detailed analysis.

## Features

- **Multi-agent pipeline**: Stats Agent, News Agent, and Prediction Agent work together
- **Real-time data**: Live NBA stats via `nba_api`, real-time news via web search
- **Parlay support**: Analyze multi-leg parlays with correlation detection
- **Self-improving**: Automatically grades predictions against real results and tunes its own parameters every 3 days
- **Defensive matchup analysis**: Identifies key defender status, team defense quality, pace
- **Hit rate tracking**: "Player went over X in Y% of games" at season/recent/vs-team levels
- **Combo stats**: PRA, PR, PA, RA, STOCKS computed automatically
- **Edge case handling**: Player OUT, no game today, back-to-back detection

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up environment

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

### 3. Run a prediction

**Single bet (CLI):**
```bash
python main.py "Donovan Mitchell 24.5 points over"
python main.py "Jalen Brunson 6.5 assists over"
python main.py "LeBron James 40.5 pra over"
```

**Parlay (use AND or comma to separate legs):**
```bash
python main.py "Mitchell 24.5 pts over AND Brunson 6.5 assists over"
python main.py "Tatum 27.5 pts over AND Mitchell 24.5 pts over AND Brunson 6.5 ast over"
```

**Web UI:**
```bash
streamlit run app.py
```

## How It Works

```
Input: "Donovan Mitchell 24.5 points over"
  |
  1. Parse bet prompt (player, stat, line, direction)
  2. Find today's opponent + back-to-back check
  3. Stats Agent + News Agent (run in parallel)
     - Stats: season avg, hit rate, variance, home/away splits, vs-team, pace, defense
     - News: injury reports, defender status, lineup changes
  4. Prediction Agent analyzes all data -> structured prediction
```

For parlays, all legs run in parallel (a 3-leg parlay takes ~2 min, not 3x a single bet), then a Parlay Agent assesses combined probability and correlations.

## Supported Stats

| Stat | Keywords |
|------|----------|
| Points | `points`, `pts` |
| Rebounds | `rebounds`, `rebs`, `reb` |
| Assists | `assists`, `ast` |
| Threes | `threes`, `3pt`, `3s` |
| Steals | `steals`, `stl` |
| Blocks | `blocks`, `blk` |
| Turnovers | `turnovers`, `tov` |
| PRA | `pra`, `points rebounds assists` |
| Points + Rebounds | `pr`, `points rebounds` |
| Points + Assists | `pa`, `points assists` |
| Rebounds + Assists | `ra`, `rebounds assists` |
| Steals + Blocks | `stocks`, `steals blocks` |

## Self-Improving Pipeline

The system runs autonomously in the background — fetching real DraftKings prop lines, making predictions, grading them against actual game results, and self-tuning its prediction weights every 3 days.

### How Self-Improvement Works

```
Daily Cycle:
  4:00 PM ET  →  Fetch DraftKings props for top 3 games
                 Run prediction pipeline for each player prop
                 Store predictions + odds in Supabase

  8:00 AM ET  →  Fetch actual box scores from nba_api
  (next day)     Grade each prediction: HIT / MISS / PUSH
                 Log daily accuracy metrics

Every 3 Days:
  9:00 AM ET  →  Self-Improvement Agent analyzes accuracy data:
                 - Hit rate by confidence level (HIGH/MEDIUM/LOW)
                 - Hit rate by stat type (points/rebounds/assists/threes)
                 - Hit rate by direction (OVER vs UNDER)
                 - Worst misses (high confidence + wrong)
                 Adjusts prediction weights:
                 - Factor weights (base rate, matchup, defense, form, context)
                 - Confidence thresholds
                 - Hit rate signal thresholds
                 - Defense rating thresholds
                 Stores new instruction version in Supabase
```

### Setup

1. Create a [Supabase](https://supabase.com) project and run `supabase_schema.sql` in the SQL Editor
2. Get a free API key from [The Odds API](https://the-odds-api.com)
3. Add to your `.env` file:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-key
   ODDS_API_KEY=your-odds-api-key
   ```

### Pipeline Commands

```bash
python run_pipeline.py seed      # Store initial instruction version (run once)
python run_pipeline.py predict   # Fetch today's DraftKings props + run predictions
python run_pipeline.py grade     # Grade yesterday's predictions vs actual box scores
python run_pipeline.py improve   # Analyze accuracy + self-tune prediction weights
python run_pipeline.py status    # Show accuracy metrics + credit usage
python run_pipeline.py loop      # Run continuously on schedule (background)
```

### Running in the Background

The pipeline needs to stay running to operate on schedule. Use `nohup` to keep it alive after closing your terminal:

```bash
# Start the loop in the background
nohup python -u run_pipeline.py loop > pipeline.log 2>&1 &

# Check the logs
tail -f pipeline.log

# Check if it's running
ps aux | grep run_pipeline

# Stop it
kill $(ps aux | grep 'run_pipeline.py loop' | grep -v grep | awk '{print $2}')
```

Or if you have `tmux` installed:
```bash
brew install tmux
tmux new -s pipeline
python run_pipeline.py loop
# Press Ctrl+B then D to detach (it keeps running)
# Reconnect later: tmux attach -t pipeline
```

### Credit Budget

Uses The Odds API free tier (500 credits/month). Fetches 4 markets (points, rebounds, assists, threes) for top 3 games/day = 12 credits/day = ~360/month with a 140-credit buffer.

## Project Structure

```
bet_agents/          # AI agents
  orchestrator.py    # Pipeline coordination (single + parlay)
  prediction_agent.py # Prediction + Parlay models
  stats_agent.py     # Stats gathering agent
  news_agent.py      # News/injury agent

tools/               # Data tools
  parser_tools.py    # Bet parsing, player lookup, opponent finder
  stats_tools.py     # NBA stats via nba_api
  news_tools.py      # News search via GNews + ESPN
  cache.py           # In-memory TTL cache

pipeline/            # Self-improving pipeline
  config.py          # Supabase + Odds API configuration
  db.py              # Supabase CRUD operations
  odds_fetcher.py    # Fetch DraftKings props from The Odds API
  result_grader.py   # Grade predictions vs actual box scores
  self_improver.py   # LLM agent that tunes prediction weights
  runner.py          # Orchestrate predict/grade/improve phases

main.py              # CLI entry point (single predictions)
app.py               # Streamlit web UI
run_pipeline.py      # CLI entry point (automated pipeline)
supabase_schema.sql  # Database schema for Supabase
```

## Requirements

- Python 3.10+
- OpenAI API key (uses GPT models via OpenAI Agents SDK)
- Internet connection (for NBA stats API and news search)
- Supabase account (free tier, for pipeline mode)
- The Odds API key (free tier, 500 credits/month, for pipeline mode)

## Disclaimer

This is for informational and educational purposes only. Always gamble responsibly.
