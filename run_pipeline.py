#!/usr/bin/env python3
"""CLI entry point for the self-improving prediction pipeline.

Usage:
    python run_pipeline.py predict   — Fetch today's DraftKings props and run predictions
    python run_pipeline.py grade     — Grade yesterday's predictions against actual results
    python run_pipeline.py improve   — Analyze accuracy and self-tune prediction instructions
    python run_pipeline.py status    — Show accuracy metrics and credit usage
    python run_pipeline.py seed      — Store initial instruction version in Supabase
    python run_pipeline.py loop      — Run continuously on schedule (predict/grade/improve)
"""

import asyncio
import sys

from dotenv import load_dotenv
load_dotenv()

from pipeline.runner import (
    predict_phase,
    grade_phase,
    improve_phase,
    status_report,
    seed_instructions,
    run_loop,
)


COMMANDS = {
    "predict": predict_phase,
    "grade": grade_phase,
    "improve": improve_phase,
    "status": status_report,
    "seed": seed_instructions,
    "loop": run_loop,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(
            "\nUsage: python run_pipeline.py <command>\n\n"
            "Commands:\n"
            "  predict   Fetch today's DraftKings props and run predictions\n"
            "  grade     Grade yesterday's predictions against actual results\n"
            "  improve   Analyze accuracy and self-tune prediction instructions\n"
            "  status    Show accuracy metrics and credit usage\n"
            "  seed      Store initial instruction version in Supabase\n"
            "  loop      Run continuously on schedule (predict/grade/improve)\n"
        )
        sys.exit(1)

    command = sys.argv[1]
    print(f"\n  Running: {command}")
    asyncio.run(COMMANDS[command]())


if __name__ == "__main__":
    main()
