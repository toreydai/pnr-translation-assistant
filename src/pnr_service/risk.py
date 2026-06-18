from typing import Any, Dict

from . import dsl
from .auth import AuthContext
from .config import AUTO_EXECUTION_ENABLED


def decide(
    intermediate: Dict[str, Any],
    validation_errors: Any,
    auth_context: AuthContext,
    context_provided: bool = True,
) -> Dict[str, Any]:
    # PNR-state staleness is enforced at execute() time by comparing the
    # client-supplied version against the stored translation version. There is
    # no second "current" version to compare against here, so it is not checked.
    if validation_errors:
        return {"status": "need_clarification", "requires_manual_review": False, "auto_executable": False}

    command = dsl.get_command(intermediate["intent"])
    if not command:
        return {"status": "manual_review", "requires_manual_review": True, "auto_executable": False}

    confidence = float(intermediate.get("confidence") or 0)
    if command.risk_policy.level == "high":
        return {"status": "manual_review", "requires_manual_review": True, "auto_executable": False}
    if command.risk_policy.level == "medium":
        return {"status": "ready_for_confirm", "requires_manual_review": False, "auto_executable": False}
    if confidence < command.risk_policy.min_confidence:
        return {"status": "need_clarification", "requires_manual_review": False, "auto_executable": False}

    # Never auto-execute against a fabricated/absent PNR context: without the
    # real current PNR state, passenger/segment existence cannot be validated.
    auto_executable = (
        AUTO_EXECUTION_ENABLED
        and command.risk_policy.auto_execute
        and auth_context.has_role("executor")
        and context_provided
    )
    return {
        "status": "auto_executable" if auto_executable else "ready_for_confirm",
        "requires_manual_review": False,
        "auto_executable": auto_executable,
    }

