# Sports Betting Prediction App

## Overview
Multi-agent NBA betting prediction app using OpenAI Agents SDK. Users provide natural language betting prompts (e.g., "Duncan Robinson 8 points over") and the system predicts whether the bet will hit.

## Tech Stack
- Python 3.10+, OpenAI Agents SDK, nba_api, Streamlit
- Models: gpt-5-mini (orchestrator/stats/news), gpt-5.4 (prediction)

## Project Structure
```
bet_agents/      - AI agents (orchestrator, stats, news, prediction)
tools/           - Data tools (parser, stats via nba_api, news via gnews)
docs/            - SDK and API reference docs
main.py          - CLI entry point
app.py           - Streamlit web UI
```

## How to Run
```bash
# CLI
python main.py "LeBron James 25.5 points over"

# Web UI
streamlit run app.py
```

## Key Conventions
- All `@function_tool` functions return `str` (use `json.dumps()` for structured data)
- Wrap tool logic in try/except, return error strings on failure
- `time.sleep(0.6)` before each nba_api call (rate limiting)
- Agents are wired via `Agent.as_tool()` (orchestrator maintains control)
- Prediction Agent uses structured Pydantic output (`BetPrediction`)

## Environment
- Requires `OPENAI_API_KEY` in `.env`
- nba_api requires no API key
