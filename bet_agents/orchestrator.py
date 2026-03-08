"""Orchestrator - Programmatic pipeline that coordinates sub-agents for bet prediction."""

import asyncio

from agents import Runner

from bet_agents.stats_agent import stats_agent
from bet_agents.news_agent import news_agent
from bet_agents.prediction_agent import (
    prediction_agent, BetPrediction,
    parlay_agent, ParlayPrediction,
)
from tools.parser_tools import (
    _parse_bet_prompt, _find_today_opponent, is_combo_stat,
    parse_parlay_prompt,
)

AGENT_TIMEOUT = 180  # seconds


def _bet_prediction_to_dict(output: BetPrediction) -> dict:
    """Convert a BetPrediction to a plain dict."""
    return {
        "player_name": output.player_name,
        "stat_type": output.stat_type,
        "line": output.line,
        "prediction": output.prediction,
        "confidence": output.confidence,
        "confidence_pct": output.confidence_pct,
        "predicted_value": output.predicted_value,
        "player_is_out": output.player_is_out,
        "no_game_today": output.no_game_today,
        "reasoning": output.reasoning,
        "detailed_reasoning": output.detailed_reasoning,
        "key_factors_over": output.key_factors_over,
        "key_factors_under": output.key_factors_under,
        "risk_factors": output.risk_factors,
        "raw_output": None,
    }


async def run_prediction(prompt: str) -> dict:
    """Run the full prediction pipeline for a betting prompt.

    Pipeline:
    1. Parse the bet prompt (direct function call)
    2. Find today's opponent (direct function call)
    3. Call Stats Agent + News Agent IN PARALLEL
    4. Call Prediction Agent with ALL gathered data → structured BetPrediction
    """
    # Step 1: Parse the bet
    print("[1/4] Parsing bet prompt...")
    parsed = _parse_bet_prompt(prompt)

    if "error" in parsed and "player_id" not in parsed:
        return {"raw_output": f"Failed to parse bet: {parsed['error']}", "prediction": None, "confidence": None}

    player_name = parsed["player_name"]
    player_id = parsed["player_id"]
    stat_column = parsed["stat_column"]
    stat_type = parsed["stat_type"]
    line = parsed["line"]
    over_under = parsed["over_under"]

    print(f"    Player: {player_name} (ID: {player_id})")
    print(f"    Bet: {line} {stat_type} {over_under}")
    if is_combo_stat(stat_column):
        print(f"    Combo stat: {stat_column}")

    # Step 2: Find today's opponent
    print("[2/4] Finding today's opponent...")
    try:
        opponent = _find_today_opponent(player_name)
    except Exception as e:
        opponent = {"error": str(e), "no_game_today": True}

    opponent_info = ""
    if opponent.get("no_game_today"):
        opponent_info = (
            f"{player_name}'s team ({opponent.get('player_team', 'unknown')}) has NO GAME TODAY. "
            f"Provide a general assessment based on season data and recent form."
        )
        print(f"    No game today for {opponent.get('player_team', 'unknown')}")
    elif "error" in opponent:
        opponent_info = f"Could not determine opponent: {opponent.get('error', 'unknown error')}. Provide a general assessment."
        print(f"    Warning: {opponent.get('error', 'unknown')}")
    else:
        b2b_str = " (BACK-TO-BACK)" if opponent.get("is_back_to_back") else ""
        opponent_info = (
            f"Opponent: {opponent.get('opponent_name', 'Unknown')} ({opponent.get('opponent_abbr', 'UNK')}). "
            f"{'Home' if opponent.get('is_home') else 'Away'} game on {opponent.get('game_date', 'today')}.{b2b_str}"
        )
        print(f"    Opponent: {opponent.get('opponent_name', 'Unknown')}")
        print(f"    Home/Away: {'Home' if opponent.get('is_home') else 'Away'}")
        if opponent.get("is_back_to_back"):
            print(f"    Back-to-back: YES")

    # Step 3: Call Stats Agent + News Agent IN PARALLEL
    print("[3/4] Stats Agent + News Agent working in parallel...")
    stats_prompt = _build_stats_prompt(player_name, player_id, stat_column, stat_type, line, over_under, opponent, opponent_info)
    news_prompt = _build_news_prompt(player_name, stat_type, line, over_under, opponent)

    try:
        stats_result, news_result = await asyncio.wait_for(
            asyncio.gather(
                Runner.run(stats_agent, stats_prompt),
                Runner.run(news_agent, news_prompt),
            ),
            timeout=AGENT_TIMEOUT,
        )
        stats_output = str(stats_result.final_output)
        news_output = str(news_result.final_output)
    except asyncio.TimeoutError:
        print("    WARNING: Agent timeout, using partial data")
        stats_output = "Stats agent timed out. Use available data only."
        news_output = "News agent timed out. Use available data only."

    print(f"    Stats: {len(stats_output)} chars | News: {len(news_output)} chars")

    # Step 4: Call Prediction Agent with ALL data
    print("[4/4] Prediction Agent analyzing...")
    prediction_prompt = _build_prediction_prompt(
        player_name, stat_column, stat_type, line, over_under,
        opponent_info, opponent, stats_output, news_output
    )

    try:
        pred_result = await asyncio.wait_for(
            Runner.run(prediction_agent, prediction_prompt),
            timeout=AGENT_TIMEOUT,
        )
        output = pred_result.final_output
    except asyncio.TimeoutError:
        return {"raw_output": "Prediction agent timed out.", "prediction": None, "confidence": None}

    if isinstance(output, BetPrediction):
        return _bet_prediction_to_dict(output)

    return {
        "raw_output": str(output),
        "prediction": None,
        "confidence": None,
    }


def _build_stats_prompt(player_name, player_id, stat_column, stat_type, line, over_under, opponent, opponent_info):
    """Build the prompt for the Stats Agent."""
    prompt = (
        f"I need comprehensive stats for this NBA player prop bet:\n\n"
        f"PLAYER: {player_name} (ID: {player_id})\n"
        f"STAT: {stat_column} ({stat_type})"
    )
    if is_combo_stat(stat_column):
        from tools.parser_tools import get_combo_components
        prompt += f" [COMBO: sum of {'+'.join(get_combo_components(stat_column))}]"
    prompt += (
        f"\nLINE: {line} {over_under}\n"
        f"GAME: {opponent_info}\n\n"
        f"Gather the following data using your tools:\n\n"
        f"1. SEASON STATS: Call get_player_season_stats with player_id={player_id}, stat_column=\"{stat_column}\", line={line}\n"
        f"   → I need: season avg, median, std_dev, hit rate vs the {line} line, trend, last 5 values\n\n"
        f"2. RECENT GAMES: Call get_player_recent_games with player_id={player_id}\n"
        f"   → I need: last 5 game box scores with minutes played. Flag any DNP/low-minute games.\n\n"
        f"3. HOME/AWAY SPLITS: Call get_player_home_away_splits with player_id={player_id}, stat_column=\"{stat_column}\"\n"
        f"   → I need: home avg vs away avg\n\n"
    )

    if opponent.get("opponent_abbr"):
        prompt += (
            f"4. VS OPPONENT HISTORY: Call get_player_vs_team_stats with player_id={player_id}, "
            f"opponent_abbr=\"{opponent['opponent_abbr']}\", stat_column=\"{stat_column}\", line={line}\n"
            f"   → I need: avg vs this team, hit rate vs team, game-by-game\n\n"
            f"5. ADVANCED STATS: Call get_player_advanced_stats with player_id={player_id}\n"
            f"   → I need: FG%, 3P%, minutes per game\n\n"
            f"6. OPPONENT DEFENSE: Call get_team_defensive_rating with team_abbreviation=\"{opponent['opponent_abbr']}\"\n\n"
            f"7. OPPONENT PACE: Call get_team_pace with team_abbreviation=\"{opponent['opponent_abbr']}\"\n"
            f"   → I need: pace, def rating, off rating\n\n"
        )
    else:
        prompt += (
            f"4. ADVANCED STATS: Call get_player_advanced_stats with player_id={player_id}\n\n"
        )

    prompt += (
        f"8. INJURY REPORT: Call get_injury_report\n"
        f"   → Look for injuries to {player_name} or relevant teammates\n\n"
        f"After gathering all data, provide a CLEAR SUMMARY organized by section. "
        f"Include the hit rate prominently (e.g., 'Player went over {line} in X/Y games (Z%)')."
    )
    return prompt


def _build_news_prompt(player_name, stat_type, line, over_under, opponent):
    """Build the prompt for the News Agent."""
    prompt = (
        f"Research real-time news for this NBA player prop bet:\n\n"
        f"PLAYER: {player_name}\n"
        f"TEAM: {opponent.get('player_team', 'unknown')}\n"
        f"BET: {line} {stat_type} {over_under}\n"
    )

    if opponent.get("opponent_name"):
        prompt += (
            f"OPPONENT: {opponent['opponent_name']}\n\n"
            f"YOU MUST SEARCH FOR ALL OF THE FOLLOWING:\n\n"
            f"1. PLAYER STATUS: Use web search for \"{player_name} injury status today\" and \"{player_name} playing tonight\"\n"
            f"   → Is {player_name} healthy? Any minutes restriction? Any role change?\n\n"
            f"2. OPPONENT INJURIES: Use web search for \"{opponent['opponent_name']} injuries today\" "
            f"and \"{opponent['opponent_name']} injury report\"\n"
            f"   → Who is OUT? Who is QUESTIONABLE? This is CRITICAL.\n\n"
            f"3. DEFENSIVE MATCHUP: Use web search for:\n"
            f"   - \"Who guards {player_name} {opponent['opponent_name']}\"\n"
            f"   - \"{opponent['opponent_name']} best perimeter defender\" (if {stat_type} is points/threes)\n"
            f"   → WHO typically defends {player_name}? Is that defender AVAILABLE tonight?\n\n"
            f"4. LINEUP CHANGES: Use web search for \"{opponent['opponent_name']} starting lineup tonight\"\n\n"
            f"5. TEAMMATE STATUS: Search for \"{opponent.get('player_team', '')} injuries\"\n\n"
            f"IMPORTANT: The MOST VALUABLE finding is whether the opponent's primary defender "
            f"for {player_name} is OUT or LIMITED. This single factor can swing a prediction significantly."
        )
    else:
        prompt += (
            f"\nSearch for:\n"
            f"1. \"{player_name} injury status\" - is the player healthy?\n"
            f"2. \"{player_name} recent performance\" - any trending news?\n"
            f"3. \"{opponent.get('player_team', '')} news\" - team context\n"
        )

    return prompt


def _build_prediction_prompt(player_name, stat_column, stat_type, line, over_under,
                              opponent_info, opponent, stats_output, news_output):
    """Build the prompt for the Prediction Agent."""
    context_notes = []
    if opponent.get("is_back_to_back"):
        context_notes.append(f"BACK-TO-BACK ALERT: {player_name}'s team played yesterday. Expect 5-10% lower performance.")
    if opponent.get("is_home") is not None:
        context_notes.append(f"Location: {'HOME' if opponent.get('is_home') else 'AWAY'} game")

    context_str = "\n".join(context_notes)

    return (
        f"=== BET TO ANALYZE ===\n"
        f"Player: {player_name}\n"
        f"Stat: {stat_column} ({stat_type})\n"
        f"Line: {line}\n"
        f"Direction to evaluate: {over_under}\n"
        f"Game: {opponent_info}\n"
        f"{context_str}\n\n"
        f"=== STATISTICAL DATA FROM STATS AGENT ===\n"
        f"{stats_output}\n\n"
        f"=== NEWS & MATCHUP INTELLIGENCE FROM NEWS AGENT ===\n"
        f"{news_output}\n\n"
        f"=== INSTRUCTIONS ===\n"
        f"Produce your OVER/UNDER prediction for {player_name} {line} {stat_type}.\n\n"
        f"Your analysis MUST include:\n"
        f"1. BASE RATE + HIT RATE: Season avg vs {line} line, and the hit rate percentage\n"
        f"2. MATCHUP HISTORY: Performance vs this opponent + vs-team hit rate\n"
        f"3. RECENT FORM: Trending up/down, any DNP games\n"
        f"4. DEFENSIVE MATCHUP: Primary defender status, opponent defense quality, def rating, pace\n"
        f"5. CONTEXT: Home/away splits, back-to-back status, teammate injuries, pace impact\n"
        f"6. FINAL DECISION: Weigh all factors with hit rate as a key anchor.\n\n"
        f"Include specific hit rate numbers in your key_factors lists."
    )


# ---------------------------------------------------------------------------
# Parlay Pipeline
# ---------------------------------------------------------------------------

def _build_opponent_info(player_name: str, opponent: dict) -> str:
    """Build opponent info string from opponent dict."""
    if opponent.get("no_game_today"):
        return (
            f"{player_name}'s team ({opponent.get('player_team', 'unknown')}) has NO GAME TODAY. "
            f"Provide a general assessment based on season data and recent form."
        )
    if "error" in opponent:
        return f"Could not determine opponent: {opponent.get('error', 'unknown error')}. Provide a general assessment."

    b2b_str = " (BACK-TO-BACK)" if opponent.get("is_back_to_back") else ""
    return (
        f"Opponent: {opponent.get('opponent_name', 'Unknown')} ({opponent.get('opponent_abbr', 'UNK')}). "
        f"{'Home' if opponent.get('is_home') else 'Away'} game on {opponent.get('game_date', 'today')}.{b2b_str}"
    )


def _build_parlay_prompt(leg_dicts: list[dict]) -> str:
    """Build the prompt for the Parlay Agent."""
    parts = [f"=== PARLAY ANALYSIS ({len(leg_dicts)} LEGS) ===\n"]

    for i, leg in enumerate(leg_dicts, 1):
        parts.append(
            f"--- LEG {i} ---\n"
            f"Player: {leg.get('player_name', 'Unknown')}\n"
            f"Bet: {leg.get('line', '?')} {leg.get('stat_type', '?')} {leg.get('prediction', '?')}\n"
            f"Prediction: {leg.get('prediction', '?')}\n"
            f"Confidence: {leg.get('confidence', '?')} ({leg.get('confidence_pct', '?')}%)\n"
            f"Predicted Value: {leg.get('predicted_value', '?')}\n"
            f"Player OUT: {leg.get('player_is_out', False)}\n"
            f"No Game Today: {leg.get('no_game_today', False)}\n"
            f"Reasoning: {leg.get('reasoning', 'N/A')}\n"
        )

    parts.append(
        f"\n=== INSTRUCTIONS ===\n"
        f"Analyze this {len(leg_dicts)}-leg parlay. Calculate combined probability, "
        f"detect correlations between legs, and decide GO or SKIP."
    )
    return "\n".join(parts)


async def run_parlay(prompt: str) -> dict:
    """Run the full parlay prediction pipeline for a multi-leg betting prompt.

    Pipeline:
    1. Parse the parlay into individual legs
    2. Find today's opponent for each leg
    3. Run Stats + News agents for ALL legs in parallel
    4. Run Prediction Agent for each leg in parallel
    5. Run Parlay Agent to aggregate and assess the parlay
    """
    # Step 1: Parse all legs
    print("[1/5] Parsing parlay legs...")
    parlay = parse_parlay_prompt(prompt)
    legs = parlay["legs"]

    if not legs:
        return {"error": f"Failed to parse parlay: {parlay.get('error', 'no legs found')}"}

    valid_legs = [l for l in legs if "player_id" in l]
    if not valid_legs:
        errors = [l.get("error", "unknown") for l in legs if "error" in l]
        return {"error": f"No valid legs parsed: {'; '.join(errors)}"}

    for i, leg in enumerate(valid_legs, 1):
        print(f"    Leg {i}: {leg['player_name']} {leg['line']} {leg['stat_type']} {leg['over_under']}")

    # Step 2: Find opponents for each leg (sequential — rate limits)
    print(f"[2/5] Finding opponents for {len(valid_legs)} legs...")
    opponents = []
    for leg in valid_legs:
        try:
            opp = _find_today_opponent(leg["player_name"])
        except Exception as e:
            opp = {"error": str(e), "no_game_today": True}
        opponents.append(opp)
        opp_name = opp.get("opponent_name", opp.get("player_team", "unknown"))
        print(f"    Leg {len(opponents)}: vs {opp_name}")

    # Step 3: Run Stats + News for ALL legs in parallel
    print(f"[3/5] Stats + News agents for all {len(valid_legs)} legs in parallel...")
    data_tasks = []
    for leg, opp in zip(valid_legs, opponents):
        opp_info = _build_opponent_info(leg["player_name"], opp)
        stats_p = _build_stats_prompt(
            leg["player_name"], leg["player_id"], leg["stat_column"],
            leg["stat_type"], leg["line"], leg["over_under"], opp, opp_info,
        )
        news_p = _build_news_prompt(
            leg["player_name"], leg["stat_type"], leg["line"], leg["over_under"], opp,
        )
        data_tasks.append(Runner.run(stats_agent, stats_p))
        data_tasks.append(Runner.run(news_agent, news_p))

    try:
        data_results = await asyncio.wait_for(
            asyncio.gather(*data_tasks, return_exceptions=True),
            timeout=AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print("    WARNING: Data gathering timed out")
        data_results = [None] * len(data_tasks)

    # Pair up results: [stats1, news1, stats2, news2, ...]
    stats_outputs = []
    news_outputs = []
    for i in range(len(valid_legs)):
        s_idx, n_idx = i * 2, i * 2 + 1
        s_res = data_results[s_idx] if s_idx < len(data_results) else None
        n_res = data_results[n_idx] if n_idx < len(data_results) else None

        if s_res and not isinstance(s_res, Exception):
            stats_outputs.append(str(s_res.final_output))
        else:
            stats_outputs.append("Stats agent timed out. Use available data only.")

        if n_res and not isinstance(n_res, Exception):
            news_outputs.append(str(n_res.final_output))
        else:
            news_outputs.append("News agent timed out. Use available data only.")

    for i in range(len(valid_legs)):
        print(f"    Leg {i+1}: Stats {len(stats_outputs[i])} chars | News {len(news_outputs[i])} chars")

    # Step 4: Run Prediction Agent for each leg in parallel
    print(f"[4/5] Prediction Agent analyzing {len(valid_legs)} legs in parallel...")
    pred_tasks = []
    for i, (leg, opp) in enumerate(zip(valid_legs, opponents)):
        opp_info = _build_opponent_info(leg["player_name"], opp)
        pred_p = _build_prediction_prompt(
            leg["player_name"], leg["stat_column"], leg["stat_type"],
            leg["line"], leg["over_under"], opp_info, opp,
            stats_outputs[i], news_outputs[i],
        )
        pred_tasks.append(Runner.run(prediction_agent, pred_p))

    try:
        pred_results = await asyncio.wait_for(
            asyncio.gather(*pred_tasks, return_exceptions=True),
            timeout=AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print("    WARNING: Prediction agents timed out")
        pred_results = [None] * len(pred_tasks)

    leg_dicts = []
    for i, res in enumerate(pred_results):
        if res and not isinstance(res, Exception) and isinstance(res.final_output, BetPrediction):
            leg_dicts.append(_bet_prediction_to_dict(res.final_output))
        else:
            # Fallback for failed legs
            leg = valid_legs[i]
            leg_dicts.append({
                "player_name": leg["player_name"],
                "stat_type": leg["stat_type"],
                "line": leg["line"],
                "prediction": "UNDER",
                "confidence": "LOW",
                "confidence_pct": 50,
                "predicted_value": 0,
                "player_is_out": False,
                "no_game_today": False,
                "reasoning": "Prediction agent failed for this leg.",
                "detailed_reasoning": "N/A",
                "key_factors_over": [],
                "key_factors_under": [],
                "risk_factors": ["Prediction agent error"],
                "raw_output": str(res) if res else "Timed out",
            })

    for i, ld in enumerate(leg_dicts, 1):
        print(f"    Leg {i}: {ld['player_name']} {ld['line']} {ld['stat_type']} → {ld['prediction']} ({ld['confidence_pct']}%)")

    # Step 5: Run Parlay Agent for aggregation
    print("[5/5] Parlay Agent analyzing combined legs...")
    parlay_prompt = _build_parlay_prompt(leg_dicts)

    try:
        parlay_result = await asyncio.wait_for(
            Runner.run(parlay_agent, parlay_prompt),
            timeout=AGENT_TIMEOUT,
        )
        parlay_output = parlay_result.final_output
    except asyncio.TimeoutError:
        parlay_output = None

    parlay_dict = None
    if isinstance(parlay_output, ParlayPrediction):
        parlay_dict = {
            "num_legs": parlay_output.num_legs,
            "parlay_prediction": parlay_output.parlay_prediction,
            "parlay_confidence": parlay_output.parlay_confidence,
            "combined_probability": parlay_output.combined_probability,
            "adjusted_probability": parlay_output.adjusted_probability,
            "correlation_notes": parlay_output.correlation_notes,
            "riskiest_leg": parlay_output.riskiest_leg,
            "parlay_reasoning": parlay_output.parlay_reasoning,
            "risk_factors": parlay_output.risk_factors,
        }

    return {
        "is_parlay": True,
        "legs": leg_dicts,
        "parlay": parlay_dict,
    }
