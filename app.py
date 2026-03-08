"""Streamlit web UI for the Sports Betting Prediction App."""

import asyncio

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from bet_agents.orchestrator import run_prediction, run_parlay
from tools.parser_tools import is_parlay

st.set_page_config(page_title="NBA Betting Predictor", page_icon="🏀", layout="wide")

st.title("🏀 NBA Betting Predictor")
st.markdown("Enter a player prop bet and get an AI-powered prediction with defensive matchup analysis.")

# Sidebar with examples
with st.sidebar:
    st.header("Example Prompts")

    st.markdown("**Single Bets**")
    single_examples = [
        "Duncan Robinson 8 points over",
        "LeBron James 25.5 pts over",
        "Nikola Jokic 10.5 rebounds under",
    ]
    for example in single_examples:
        if st.button(example, key=example):
            st.session_state["prompt"] = example

    st.markdown("**Parlays**")
    parlay_examples = [
        "Kevin Durant 27.5 pts over AND Jalen Brunson 6.5 assists over",
        "Tatum 27.5 pts over AND Mitchell 24.5 pts over",
    ]
    for example in parlay_examples:
        if st.button(example, key=example):
            st.session_state["prompt"] = example

    st.divider()
    st.markdown("### How it works")
    st.markdown(
        "1. **Parse** your bet prompt\n"
        "2. **Find** today's opponent\n"
        "3. **Stats Agent** gathers data\n"
        "4. **News Agent** searches for injuries & matchup info\n"
        "5. **Prediction Agent** analyzes everything\n"
        "6. **Parlay Agent** combines multi-leg analysis (parlays only)"
    )
    st.divider()
    st.caption("For informational purposes only. Gamble responsibly.")

# Main input
prompt = st.text_input(
    "Enter your bet (use AND to separate parlay legs)",
    value=st.session_state.get("prompt", ""),
    placeholder="e.g., Duncan Robinson 8 points over AND LeBron James 25.5 pts over",
)

if st.button("Analyze", type="primary", disabled=not prompt):
    parlay_mode = is_parlay(prompt)
    spinner_msg = (
        "Analyzing parlay... This may take 1-2 minutes as agents gather data for all legs..."
        if parlay_mode else
        "Analyzing... This may take 30-60 seconds as agents gather data..."
    )

    with st.spinner(spinner_msg):
        try:
            if parlay_mode:
                result = asyncio.run(run_parlay(prompt))
            else:
                result = asyncio.run(run_prediction(prompt))
        except Exception as e:
            st.error(f"Error running prediction: {e}")
            result = None

    if result:
        if result.get("is_parlay"):
            # --- Parlay Display ---
            legs = result.get("legs", [])
            parlay = result.get("parlay")

            if result.get("error"):
                st.error(result["error"])
            else:
                # Parlay verdict at the top
                if parlay:
                    verdict = parlay["parlay_prediction"]
                    verdict_color = "green" if verdict == "GO" else "red"
                    st.markdown(f"## Parlay Verdict: :{verdict_color}[{verdict}]")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Confidence", parlay["parlay_confidence"])
                    with col2:
                        st.metric("Combined Probability", f"{parlay['combined_probability']:.1f}%")
                    with col3:
                        st.metric("Adjusted Probability", f"{parlay['adjusted_probability']:.1f}%")

                    st.write(parlay["parlay_reasoning"])

                    if parlay.get("correlation_notes"):
                        with st.expander("Correlations"):
                            for note in parlay["correlation_notes"]:
                                st.info(note)

                    if parlay.get("risk_factors"):
                        with st.expander("Parlay Risk Factors"):
                            for f in parlay["risk_factors"]:
                                st.warning(f)

                    st.divider()

                # Individual legs
                st.subheader(f"Individual Legs ({len(legs)})")
                for i, leg in enumerate(legs, 1):
                    status = ""
                    if leg.get("player_is_out"):
                        status = " [OUT]"
                    elif leg.get("no_game_today"):
                        status = " [NO GAME]"

                    leg_title = f"Leg {i}: {leg.get('player_name', '?')} {leg.get('line', '?')} {leg.get('stat_type', '?')}{status}"
                    with st.expander(leg_title, expanded=True):
                        if leg.get("player_is_out"):
                            st.warning("Player is currently OUT/injured.")
                        if leg.get("no_game_today"):
                            st.info("No game today.")

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            color = "green" if leg.get("prediction") == "OVER" else "red"
                            st.markdown(f"### :{color}[{leg.get('prediction', '?')}]")
                        with col2:
                            st.metric("Confidence", f"{leg.get('confidence', '?')} ({leg.get('confidence_pct', '?')}%)")
                        with col3:
                            st.metric("Predicted Value", leg.get("predicted_value", "?"))

                        st.write(leg.get("reasoning", ""))

        elif result.get("prediction"):
            # --- Single Bet Display ---
            pred = result

            if pred.get("player_is_out"):
                st.warning("Player is currently OUT/injured. Analysis below is for when the player is active.")
            if pred.get("no_game_today"):
                st.info("No game today. General assessment based on season data.")

            player_line = f"{pred.get('player_name', '')} - {pred.get('line', '')} {pred.get('stat_type', '')}"
            st.subheader(player_line)

            col1, col2, col3 = st.columns(3)
            with col1:
                color = "green" if pred["prediction"] == "OVER" else "red"
                st.markdown(f"### :{color}[{pred['prediction']}]")
            with col2:
                st.metric("Confidence", f"{pred['confidence']} ({pred['confidence_pct']}%)")
            with col3:
                st.metric("Predicted Value", pred["predicted_value"])

            st.divider()

            st.subheader("Reasoning")
            st.write(pred["reasoning"])

            with st.expander("Detailed Analysis", expanded=True):
                st.write(pred["detailed_reasoning"])

            col_over, col_under = st.columns(2)
            with col_over:
                st.subheader("Factors Favoring OVER")
                if pred.get("key_factors_over"):
                    for f in pred["key_factors_over"]:
                        st.markdown(f"- {f}")
            with col_under:
                st.subheader("Factors Favoring UNDER")
                if pred.get("key_factors_under"):
                    for f in pred["key_factors_under"]:
                        st.markdown(f"- {f}")

            if pred.get("risk_factors"):
                st.subheader("Risk Factors")
                for f in pred["risk_factors"]:
                    st.warning(f)

        elif result.get("raw_output"):
            st.subheader("Analysis")
            st.write(result["raw_output"])
        else:
            st.warning("No prediction was generated. Please try a different prompt.")
