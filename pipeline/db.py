"""Supabase CRUD operations for the prediction pipeline."""

from datetime import date, datetime

from pipeline.config import supabase


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

def insert_prediction(data: dict) -> dict:
    """Insert a new prediction row."""
    return supabase.table("predictions").insert(data).execute()


def get_pending_predictions(game_date: date) -> list[dict]:
    """Get all pending predictions for a specific game date."""
    return (
        supabase.table("predictions")
        .select("*")
        .eq("status", "pending")
        .eq("game_date", game_date.isoformat())
        .execute()
        .data
    )


def update_prediction_grade(
    pred_id: str,
    status: str,
    actual_value: float | None = None,
    result: str | None = None,
):
    """Grade a prediction with actual result."""
    update = {"status": status, "graded_at": datetime.utcnow().isoformat()}
    if actual_value is not None:
        update["actual_value"] = actual_value
    if result is not None:
        update["result"] = result
    return supabase.table("predictions").update(update).eq("id", pred_id).execute()


def get_graded_predictions(limit: int = 100) -> list[dict]:
    """Get recent graded predictions for analysis."""
    return (
        supabase.table("predictions")
        .select("*")
        .eq("status", "graded")
        .order("graded_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )


def get_predictions_by_run(pipeline_run_id: str) -> list[dict]:
    """Get all predictions from a specific pipeline run."""
    return (
        supabase.table("predictions")
        .select("*")
        .eq("pipeline_run_id", pipeline_run_id)
        .execute()
        .data
    )


# ---------------------------------------------------------------------------
# Performance Log
# ---------------------------------------------------------------------------

def insert_performance_log(data: dict) -> dict:
    """Insert a performance log entry."""
    return supabase.table("performance_log").insert(data).execute()


def get_performance_logs(period_type: str = "daily", limit: int = 30) -> list[dict]:
    """Get recent performance logs."""
    return (
        supabase.table("performance_log")
        .select("*")
        .eq("period_type", period_type)
        .order("period_start", desc=True)
        .limit(limit)
        .execute()
        .data
    )


# ---------------------------------------------------------------------------
# Instruction Versions
# ---------------------------------------------------------------------------

def get_active_instruction_version() -> dict | None:
    """Get the currently active instruction version."""
    result = (
        supabase.table("instruction_versions")
        .select("*")
        .eq("is_active", True)
        .limit(1)
        .execute()
        .data
    )
    return result[0] if result else None


def get_latest_version_number() -> int:
    """Get the latest instruction version number."""
    result = (
        supabase.table("instruction_versions")
        .select("version_number")
        .order("version_number", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return result[0]["version_number"] if result else 0


def insert_instruction_version(data: dict) -> dict:
    """Insert a new instruction version and deactivate the old one."""
    # Deactivate current active version
    supabase.table("instruction_versions").update(
        {"is_active": False}
    ).eq("is_active", True).execute()

    data["is_active"] = True
    return supabase.table("instruction_versions").insert(data).execute()


# ---------------------------------------------------------------------------
# Credit Usage
# ---------------------------------------------------------------------------

def get_monthly_credits_used(month: str | None = None) -> int:
    """Get total credits used this month."""
    if month is None:
        month = date.today().strftime("%Y-%m")
    result = (
        supabase.table("credit_usage")
        .select("credits_used")
        .eq("month", month)
        .execute()
        .data
    )
    return sum(row["credits_used"] for row in result)


def insert_credit_usage(credits: int, event_id: str, markets: list[str]):
    """Log credit usage."""
    return supabase.table("credit_usage").insert({
        "month": date.today().strftime("%Y-%m"),
        "credits_used": credits,
        "event_id": event_id,
        "markets": markets,
    }).execute()
