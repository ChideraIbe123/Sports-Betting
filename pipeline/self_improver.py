"""Self-improvement agent — analyzes prediction accuracy and tunes instruction parameters."""

import json
import re
from typing import Literal

from agents import Agent, Runner
from pydantic import BaseModel, Field

from pipeline.config import MIN_PREDICTIONS_FOR_IMPROVEMENT
from pipeline.db import (
    get_graded_predictions,
    get_performance_logs,
    get_active_instruction_version,
    get_latest_version_number,
    insert_instruction_version,
)
from bet_agents.prediction_agent import PREDICTION_AGENT_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Structured output for instruction adjustments
# ---------------------------------------------------------------------------

class ParamAdjustment(BaseModel):
    """A single parameter adjustment."""
    param_name: str = Field(description="Parameter name (e.g., 'base_rate_weight')")
    old_value: float = Field(description="Current value")
    new_value: float = Field(description="Proposed new value")
    reason: str = Field(description="Why this change should improve accuracy")


class InstructionAdjustment(BaseModel):
    """Structured output from the self-improvement agent."""
    should_adjust: bool = Field(
        description="Whether any adjustments are recommended"
    )
    overall_assessment: str = Field(
        description="2-3 sentence assessment of current prediction quality"
    )
    weak_spots: list[str] = Field(
        description="Identified weaknesses in current predictions"
    )
    strong_spots: list[str] = Field(
        description="What the model is doing well"
    )
    adjustments: list[ParamAdjustment] = Field(
        description="List of parameter adjustments to apply (empty if should_adjust=false)"
    )
    new_instructions_text: str = Field(
        description="The full updated instruction text with adjustments applied. If should_adjust=false, return the original text unchanged."
    )
    expected_improvement: str = Field(
        description="What improvement is expected from these changes"
    )


# ---------------------------------------------------------------------------
# Self-improvement agent
# ---------------------------------------------------------------------------

SELF_IMPROVE_INSTRUCTIONS = """You are an expert at calibrating sports prediction models. You receive \
accuracy data from an NBA player prop prediction system and recommend parameter adjustments.

## YOUR GOAL
Improve the prediction system's hit rate by adjusting instruction parameters. The system predicts \
OVER/UNDER on NBA player props (points, rebounds, assists, threes).

## PARAMETERS YOU CAN ADJUST
These are the tunable weights and thresholds in the prediction instructions:

### Factor Weights (must sum to 100):
- base_rate_weight: How much weight the season average and hit rate get (currently ~40)
- matchup_weight: How much weight matchup history gets (currently ~15)
- recent_form_weight: How much weight recent game form gets (currently ~15)
- defense_weight: How much weight defensive matchup gets (currently ~20)
- context_weight: How much weight home/away, B2B, pace get (currently ~10)

### Confidence Thresholds:
- high_conf_min/max: Range for HIGH confidence (currently 75-90)
- medium_conf_min/max: Range for MEDIUM confidence (currently 55-74)
- low_conf_min/max: Range for LOW confidence (currently 50-54)

### Hit Rate Signals:
- hit_rate_strong_over: Above this → strong OVER signal (currently 65)
- hit_rate_strong_under: Below this → strong UNDER signal (currently 35)

### Defense Thresholds:
- elite_defense_threshold: Def rating below this = elite (currently 108)
- poor_defense_threshold: Def rating above this = poor (currently 112)

### Other:
- b2b_penalty_pct: Back-to-back performance penalty (currently 7.5%)

## RULES
1. **Conservative changes**: Never change any weight by more than 5 points in a single iteration
2. **Weights must sum to 100**: If you increase one factor weight, decrease another
3. **Look for patterns**:
   - If OVER predictions miss a lot → the system might be too aggressive on overs
   - If HIGH confidence predictions miss → confidence thresholds need tightening
   - If a specific stat type (e.g., threes) has low hit rate → may need different treatment
4. **Data-driven**: Only recommend changes supported by the accuracy data
5. **If accuracy is already good (>60% hit rate)**: Be very conservative, small tweaks only
6. **If accuracy is poor (<50%)**: Identify the biggest problem area and focus there

## OUTPUT
- Set should_adjust=false if accuracy is good (>60%) and no clear pattern of errors exists
- Set should_adjust=true if you see actionable patterns
- In new_instructions_text, apply your adjustments to the full instruction text
- Keep the instruction structure identical, only change numeric values and thresholds

## IMPORTANT
When writing new_instructions_text:
- Preserve the exact markdown structure and headings
- Only change numeric values (weights, thresholds, percentages)
- Do NOT change the analysis framework logic or add new sections
- Do NOT remove any sections
"""

self_improve_agent = Agent(
    name="Self-Improvement Agent",
    model="gpt-5.4",
    instructions=SELF_IMPROVE_INSTRUCTIONS,
    output_type=InstructionAdjustment,
)


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def _build_accuracy_report(predictions: list[dict]) -> str:
    """Build a comprehensive accuracy report from graded predictions."""
    if not predictions:
        return "No graded predictions available."

    total = len(predictions)
    hits = sum(1 for p in predictions if p.get("result") == "HIT")
    misses = sum(1 for p in predictions if p.get("result") == "MISS")
    pushes = sum(1 for p in predictions if p.get("result") == "PUSH")
    decidable = hits + misses
    hit_rate = hits / decidable if decidable > 0 else 0

    report = [
        f"=== PREDICTION ACCURACY REPORT ({total} predictions) ===\n",
        f"Overall: {hits} hits, {misses} misses, {pushes} pushes",
        f"Hit Rate: {hit_rate:.1%} ({hits}/{decidable})\n",
    ]

    # By confidence level
    for conf in ["HIGH", "MEDIUM", "LOW"]:
        conf_preds = [p for p in predictions if p.get("confidence") == conf]
        conf_hits = sum(1 for p in conf_preds if p.get("result") == "HIT")
        conf_misses = sum(1 for p in conf_preds if p.get("result") == "MISS")
        conf_total = conf_hits + conf_misses
        conf_rate = conf_hits / conf_total if conf_total > 0 else 0
        report.append(f"{conf} confidence: {conf_rate:.1%} ({conf_hits}/{conf_total})")

    report.append("")

    # By stat type
    stat_types = set(p.get("stat_type", "unknown") for p in predictions)
    for stat in sorted(stat_types):
        stat_preds = [p for p in predictions if p.get("stat_type") == stat]
        stat_hits = sum(1 for p in stat_preds if p.get("result") == "HIT")
        stat_misses = sum(1 for p in stat_preds if p.get("result") == "MISS")
        stat_total = stat_hits + stat_misses
        stat_rate = stat_hits / stat_total if stat_total > 0 else 0
        report.append(f"{stat}: {stat_rate:.1%} ({stat_hits}/{stat_total})")

    report.append("")

    # By direction
    overs = [p for p in predictions if p.get("prediction") == "OVER"]
    unders = [p for p in predictions if p.get("prediction") == "UNDER"]
    over_hits = sum(1 for p in overs if p.get("result") == "HIT")
    over_total = sum(1 for p in overs if p.get("result") in ("HIT", "MISS"))
    under_hits = sum(1 for p in unders if p.get("result") == "HIT")
    under_total = sum(1 for p in unders if p.get("result") in ("HIT", "MISS"))
    over_rate = over_hits / over_total if over_total > 0 else 0
    under_rate = under_hits / under_total if under_total > 0 else 0
    report.append(f"OVER predictions: {over_rate:.1%} ({over_hits}/{over_total})")
    report.append(f"UNDER predictions: {under_rate:.1%} ({under_hits}/{under_total})")
    report.append("")

    # Error analysis
    errors = []
    for p in predictions:
        if p.get("predicted_value") and p.get("actual_value") is not None:
            errors.append(p["predicted_value"] - p["actual_value"])

    if errors:
        avg_error = sum(errors) / len(errors)
        abs_errors = [abs(e) for e in errors]
        avg_abs_error = sum(abs_errors) / len(abs_errors)
        report.append(f"Avg error (predicted - actual): {avg_error:+.1f}")
        report.append(f"Avg absolute error: {avg_abs_error:.1f}")
        report.append("")

    # Worst misses (biggest confidence + wrong)
    high_misses = [
        p for p in predictions
        if p.get("result") == "MISS" and p.get("confidence") == "HIGH"
    ]
    if high_misses:
        report.append("HIGH confidence misses (worst errors):")
        for p in high_misses[:5]:
            report.append(
                f"  {p.get('player_name', '?')} {p.get('line', '?')} {p.get('stat_type', '?')}: "
                f"predicted {p.get('prediction', '?')} ({p.get('confidence_pct', '?')}%), "
                f"actual={p.get('actual_value', '?')}"
            )
        report.append("")

    return "\n".join(report)


def _apply_params_to_instructions(instructions: str, params: dict) -> str:
    """Apply extracted parameter values to instruction text template.

    This modifies specific numeric values in the instruction text.
    """
    text = instructions

    # Weight replacements
    weight_map = {
        "base_rate_weight": (r"(Base Rate & Hit Rate.*?weight ~)\d+(%)", "base_rate_weight"),
        "matchup_weight": (r"(Matchup History.*?weight ~)\d+(%)", "matchup_weight"),
        "recent_form_weight": (r"(Recent Form.*?weight ~)\d+(%)", "recent_form_weight"),
        "defense_weight": (r"(DEFENSIVE MATCHUP.*?weight ~)\d+(%)", "defense_weight"),
        "context_weight": (r"(Context.*?weight ~)\d+(%)", "context_weight"),
    }

    for param_name, (pattern, key) in weight_map.items():
        if key in params:
            val = int(params[key])
            text = re.sub(pattern, rf"\g<1>{val}\2", text, flags=re.IGNORECASE)

    # Defense thresholds
    if "elite_defense_threshold" in params:
        val = int(params["elite_defense_threshold"])
        text = re.sub(r"(def rating <)\d+", rf"\g<1>{val}", text)
    if "poor_defense_threshold" in params:
        val = int(params["poor_defense_threshold"])
        text = re.sub(r"(def rating >)\d+", rf"\g<1>{val}", text)

    # Confidence ranges
    if "high_conf_min" in params and "high_conf_max" in params:
        text = re.sub(
            r"(HIGH \()\d+-\d+(%\))",
            rf"\g<1>{int(params['high_conf_min'])}-{int(params['high_conf_max'])}\2",
            text,
        )
    if "medium_conf_min" in params and "medium_conf_max" in params:
        text = re.sub(
            r"(MEDIUM \()\d+-\d+(%\))",
            rf"\g<1>{int(params['medium_conf_min'])}-{int(params['medium_conf_max'])}\2",
            text,
        )
    if "low_conf_min" in params and "low_conf_max" in params:
        text = re.sub(
            r"(LOW \()\d+-\d+(%\))",
            rf"\g<1>{int(params['low_conf_min'])}-{int(params['low_conf_max'])}\2",
            text,
        )

    return text


# ---------------------------------------------------------------------------
# Main self-improvement function
# ---------------------------------------------------------------------------

async def run_self_improvement(predictions: list[dict] | None = None) -> dict:
    """Analyze predictions and run self-improvement agent.

    Returns dict with 'applied' bool and adjustment details.
    """
    if predictions is None:
        predictions = get_graded_predictions(limit=200)

    if len(predictions) < MIN_PREDICTIONS_FOR_IMPROVEMENT:
        return {
            "applied": False,
            "reason": f"Need {MIN_PREDICTIONS_FOR_IMPROVEMENT} predictions, have {len(predictions)}",
        }

    # Build accuracy report
    accuracy_report = _build_accuracy_report(predictions)
    print(f"  Accuracy report:\n{accuracy_report}")

    # Get current params
    active = get_active_instruction_version()
    current_params = active.get("extracted_params", {}) if active else {}
    current_text = active.get("instructions_text", PREDICTION_AGENT_INSTRUCTIONS) if active else PREDICTION_AGENT_INSTRUCTIONS

    # Build prompt for self-improvement agent
    prompt = (
        f"=== CURRENT PREDICTION INSTRUCTIONS ===\n"
        f"{current_text}\n\n"
        f"=== CURRENT PARAMETERS ===\n"
        f"{json.dumps(current_params, indent=2)}\n\n"
        f"=== ACCURACY DATA ===\n"
        f"{accuracy_report}\n\n"
        f"=== TASK ===\n"
        f"Analyze the accuracy data and recommend parameter adjustments to improve the hit rate.\n"
        f"If the hit rate is already good (>60%) and no clear patterns of error exist, "
        f"set should_adjust=false.\n\n"
        f"Remember:\n"
        f"- Weights must sum to 100\n"
        f"- No single weight change > 5 points\n"
        f"- Focus on the biggest problem areas\n"
        f"- Be conservative — small improvements compound over time\n"
    )

    print("  Running self-improvement agent...")
    result = await Runner.run(self_improve_agent, prompt)
    adjustment = result.final_output

    if not isinstance(adjustment, InstructionAdjustment):
        return {"applied": False, "reason": "Agent did not produce valid output"}

    print(f"  Assessment: {adjustment.overall_assessment}")
    print(f"  Should adjust: {adjustment.should_adjust}")

    if adjustment.weak_spots:
        print(f"  Weak spots: {', '.join(adjustment.weak_spots)}")
    if adjustment.strong_spots:
        print(f"  Strong spots: {', '.join(adjustment.strong_spots)}")

    if not adjustment.should_adjust:
        return {
            "applied": False,
            "reason": "No adjustment needed",
            "assessment": adjustment.overall_assessment,
        }

    # Apply adjustments
    print(f"\n  Applying {len(adjustment.adjustments)} parameter changes:")
    new_params = dict(current_params)
    for adj in adjustment.adjustments:
        print(f"    {adj.param_name}: {adj.old_value} → {adj.new_value} ({adj.reason})")
        new_params[adj.param_name] = adj.new_value

    # Validate weight sum
    weight_keys = ["base_rate_weight", "matchup_weight", "recent_form_weight", "defense_weight", "context_weight"]
    weight_sum = sum(new_params.get(k, 0) for k in weight_keys)
    if abs(weight_sum - 100) > 1:
        print(f"  WARNING: Weights sum to {weight_sum}, not 100. Normalizing...")
        for k in weight_keys:
            if k in new_params:
                new_params[k] = round(new_params[k] * 100 / weight_sum, 1)

    # Use the agent's new_instructions_text if it looks valid, otherwise apply params ourselves
    new_text = adjustment.new_instructions_text
    if len(new_text) < len(current_text) * 0.5:
        # Agent returned truncated text, apply params manually
        new_text = _apply_params_to_instructions(current_text, new_params)

    # Store new version
    version_num = get_latest_version_number() + 1
    insert_instruction_version({
        "version_number": version_num,
        "instructions_text": new_text,
        "extracted_params": new_params,
        "change_reason": adjustment.expected_improvement,
        "predictions_count": 0,
        "hit_rate": None,
    })

    # Update the prediction agent's live instructions
    from bet_agents.prediction_agent import prediction_agent
    prediction_agent.instructions = new_text

    print(f"\n  Stored new instruction version v{version_num}")
    print(f"  Expected improvement: {adjustment.expected_improvement}")

    return {
        "applied": True,
        "version": version_num,
        "adjustments": [
            {"param": a.param_name, "old": a.old_value, "new": a.new_value, "reason": a.reason}
            for a in adjustment.adjustments
        ],
        "assessment": adjustment.overall_assessment,
        "expected_improvement": adjustment.expected_improvement,
    }
