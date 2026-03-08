# NBA Betting Predictor

AI-powered NBA player prop prediction system using multi-agent architecture. Enter a bet like "Donovan Mitchell 24.5 points over" and get a data-driven prediction with detailed analysis.

## Features

- **Multi-agent pipeline**: Stats Agent, News Agent, and Prediction Agent work together
- **Real-time data**: Live NBA stats via `nba_api`, real-time news via web search
- **Parlay support**: Analyze multi-leg parlays with correlation detection
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

main.py              # CLI entry point
app.py               # Streamlit web UI
```

## Requirements

- Python 3.10+
- OpenAI API key (uses GPT models via OpenAI Agents SDK)
- Internet connection (for NBA stats API and news search)

## Disclaimer

This is for informational and educational purposes only. Always gamble responsibly.
