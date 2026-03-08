"""CLI entry point for the Sports Betting Prediction App."""

import asyncio
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

# Suppress noisy HTTP request logs from openai/httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

from bet_agents.orchestrator import run_prediction, run_parlay
from tools.parser_tools import is_parlay


def _display_single_prediction(result: dict):
    """Display a single-leg prediction result."""
    if result.get("prediction"):
        pred = result

        # Warnings
        if pred.get("player_is_out"):
            print("  *** PLAYER IS CURRENTLY OUT/INJURED ***")
            print("  Analysis below is for when the player is active.")
            print()
        if pred.get("no_game_today"):
            print("  *** NO GAME TODAY ***")
            print("  General assessment based on season data.")
            print()

        print(f"{'='*60}")
        print(f"  {pred.get('player_name', '')} - {pred.get('line', '')} {pred.get('stat_type', '')} ")
        print(f"  PREDICTION: {pred['prediction']}")
        print(f"  Confidence: {pred['confidence']} ({pred['confidence_pct']}%)")
        print(f"  Predicted Value: {pred['predicted_value']}")
        print(f"{'='*60}\n")
        print(f"REASONING:\n{pred['reasoning']}\n")
        print(f"DETAILED ANALYSIS:\n{pred['detailed_reasoning']}\n")

        if pred.get("key_factors_over"):
            print("FACTORS FAVORING OVER:")
            for f in pred["key_factors_over"]:
                print(f"  + {f}")
            print()

        if pred.get("key_factors_under"):
            print("FACTORS FAVORING UNDER:")
            for f in pred["key_factors_under"]:
                print(f"  - {f}")
            print()

        if pred.get("risk_factors"):
            print("RISK FACTORS:")
            for f in pred["risk_factors"]:
                print(f"  ! {f}")
            print()
    else:
        print(result.get("raw_output", "No prediction generated."))


def _display_parlay_result(result: dict):
    """Display a parlay prediction result."""
    legs = result.get("legs", [])
    parlay = result.get("parlay")

    # Show each leg (condensed)
    print(f"\n{'='*60}")
    print(f"  PARLAY LEGS ({len(legs)} legs)")
    print(f"{'='*60}\n")

    for i, leg in enumerate(legs, 1):
        status = ""
        if leg.get("player_is_out"):
            status = " [OUT]"
        elif leg.get("no_game_today"):
            status = " [NO GAME]"

        print(f"  Leg {i}: {leg.get('player_name', '?')} {leg.get('line', '?')} {leg.get('stat_type', '?')}{status}")
        print(f"         {leg.get('prediction', '?')} - {leg.get('confidence', '?')} ({leg.get('confidence_pct', '?')}%) | Predicted: {leg.get('predicted_value', '?')}")
        print(f"         {leg.get('reasoning', 'N/A')}")
        print()

    # Show parlay summary
    if parlay:
        verdict = parlay["parlay_prediction"]
        print(f"{'='*60}")
        print(f"  PARLAY VERDICT: {verdict}")
        print(f"  Confidence: {parlay['parlay_confidence']}")
        print(f"  Combined Probability: {parlay['combined_probability']:.1f}%")
        print(f"  Adjusted Probability: {parlay['adjusted_probability']:.1f}%")
        print(f"  Riskiest Leg: {parlay['riskiest_leg']}")
        print(f"{'='*60}\n")

        print(f"PARLAY ANALYSIS:\n{parlay['parlay_reasoning']}\n")

        if parlay.get("correlation_notes"):
            print("CORRELATIONS:")
            for note in parlay["correlation_notes"]:
                print(f"  ~ {note}")
            print()

        if parlay.get("risk_factors"):
            print("RISK FACTORS:")
            for f in parlay["risk_factors"]:
                print(f"  ! {f}")
            print()
    else:
        print("Parlay agent failed to produce a summary.\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py \"<betting prompt>\"")
        print()
        print("Single bet:")
        print('  python main.py "Duncan Robinson 8 points over"')
        print('  python main.py "LeBron James 25.5 pts over"')
        print()
        print("Parlay (use AND to separate legs):")
        print('  python main.py "Kevin Durant 27.5 points over AND Jalen Brunson 6.5 assists over"')
        print('  python main.py "Tatum 27.5 pts over AND Mitchell 24.5 pts over AND Brunson 6.5 ast over"')
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    parlay_mode = is_parlay(prompt)

    print(f"\n{'='*60}")
    print(f"  NBA Betting Prediction{' (PARLAY)' if parlay_mode else ''}")
    print(f"  Prompt: {prompt}")
    print(f"{'='*60}\n")
    print(f"Analyzing{' parlay' if parlay_mode else ''}... (this may take 30-60 seconds)\n")

    if parlay_mode:
        result = asyncio.run(run_parlay(prompt))
        if result.get("error"):
            print(f"Error: {result['error']}")
        else:
            _display_parlay_result(result)
    else:
        result = asyncio.run(run_prediction(prompt))
        _display_single_prediction(result)

    print(f"\n{'='*60}")
    print("  Disclaimer: This is for informational purposes only.")
    print("  Always gamble responsibly.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
