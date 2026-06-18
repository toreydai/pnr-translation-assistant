import json
import uuid
from decimal import Decimal
from typing import Any, Dict

from . import dsl, model, retrieval, risk, store
from .auth import AuthContext, require_any_role
from .pii import redact


def _decimalize(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _decimalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimalize(item) for item in value]
    return value


def _pnr_context(body: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    """Return (pnr_context, provided).

    When the caller does not supply a PNR context we do NOT fabricate
    passenger/segment refs — that would give false confidence to the
    "ref exists in current PNR" validation. We return empty refs and flag
    the request as context-less so it can never be auto-executed.
    """
    provided = body.get("pnr_context")
    if provided:
        return provided, True
    return {
        "passenger_refs": [],
        "segment_refs": [],
        "version": body.get("pnr_context_version", "v1"),
    }, False


def _unredact(value: Any, mapping: Dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, dict):
        return {key: _unredact(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_unredact(item, mapping) for item in value]
    return value


def _derive_real_command(intermediate: Dict[str, Any], mapping: Dict[str, str]) -> str:
    """Render the real (de-redacted) executable command for secure storage."""
    if not mapping:
        return dsl.render(intermediate)
    real = dict(intermediate)
    real["entities"] = _unredact(dict(intermediate.get("entities") or {}), mapping)
    return dsl.render(real)


def translate(body: Dict[str, Any], auth_context: AuthContext) -> Dict[str, Any]:
    require_any_role(auth_context, ["translator", "executor", "reviewer", "admin"])
    user_text = body["user_text"]
    pnr_context, context_provided = _pnr_context(body)
    redaction = redact(user_text)
    shortlist = retrieval.intent_shortlist(redaction.text)
    retrieval_context = retrieval.retrieve(redaction.text, shortlist)
    intermediate = model.generate_intermediate(redaction.text, pnr_context, retrieval_context)
    intermediate = _merge_retrieval_hints(intermediate, retrieval_context)
    intermediate = _apply_deterministic_fixes(intermediate, redaction.mapping)
    intermediate = dsl.normalize(intermediate)
    validation_errors = dsl.validate(intermediate, pnr_context)

    command_preview_redacted = None
    real_command = None
    secure_command_ref = None
    command_digest = None
    if not validation_errors and not intermediate.get("missing_fields"):
        command_preview_redacted = dsl.render(intermediate)
        if not dsl.reverse_parse(command_preview_redacted, intermediate):
            validation_errors.append("rendered command failed reverse parse")
        else:
            # Secure store and integrity hash cover the REAL executable command;
            # the API only ever surfaces the redacted preview.
            real_command = _derive_real_command(intermediate, redaction.mapping)
            command_digest = store.command_hash(real_command)

    decision = risk.decide(
        intermediate,
        validation_errors or intermediate.get("missing_fields") or [],
        auth_context,
        context_provided,
    )
    translation_id = f"tr-{uuid.uuid4().hex}"
    if real_command is not None:
        secure_command_ref = store.put_secure_command(translation_id, real_command, redaction.mapping)

    record = {
        "translation_id": translation_id,
        "tenant_id": auth_context.tenant_id,
        "session_id": body.get("session_id", ""),
        "pnr_context_id": body.get("pnr_context_id", ""),
        "pnr_context_version": pnr_context.get("version", "v1"),
        "user_text_redacted": redaction.text,
        "intent": intermediate.get("intent", ""),
        "intermediate": intermediate,
        "validation_errors": validation_errors,
        "command_preview_redacted": command_preview_redacted or "",
        "command_hash": command_digest or "",
        "secure_command_ref": secure_command_ref or "",
        "confidence": Decimal(str(intermediate.get("confidence", 0))),
        "risk_level": intermediate.get("risk_level", "unknown"),
        "status": decision["status"],
        "model_id": "moonshotai.kimi-k2.5",
        "evidence_ids": intermediate.get("evidence_ids", []),
        "created_by": auth_context.subject,
        "created_at": store.now_epoch(),
    }
    store.save_translation(_decimalize(record))
    return {
        "translation_id": translation_id,
        "status": decision["status"],
        "intent": intermediate.get("intent"),
        "intermediate": intermediate.get("entities", {}),
        "missing_fields": intermediate.get("missing_fields", []),
        "command_preview_redacted": command_preview_redacted,
        "confidence": float(intermediate.get("confidence", 0)),
        "risk_level": intermediate.get("risk_level"),
        "requires_manual_review": decision["requires_manual_review"],
        "auto_executable": decision["auto_executable"],
        "validation_errors": validation_errors,
        "explanations": [
            f"intent={intermediate.get('intent')}",
            f"evidence={','.join(intermediate.get('evidence_ids', []))}",
        ],
    }


def execute(body: Dict[str, Any], auth_context: AuthContext) -> Dict[str, Any]:
    require_any_role(auth_context, ["executor", "admin"])
    translation_id = body["translation_id"]
    record = store.get_translation(translation_id, auth_context.tenant_id)
    if not record:
        raise ValueError("translation not found")
    if record.get("status") not in ("ready_for_confirm", "auto_executable"):
        raise ValueError(f"translation is not executable: {record.get('status')}")
    if body.get("pnr_context_version") != record.get("pnr_context_version"):
        raise ValueError("stale pnr_context_version")

    execution_record = {
        "idempotency_key": body["idempotency_key"],
        "tenant_id": auth_context.tenant_id,
        "execution_id": f"exe-{uuid.uuid4().hex}",
        "translation_id": translation_id,
        "executed_by": auth_context.subject,
        "command_hash": record.get("command_hash", ""),
        "status": "executed",
        "created_at": store.now_epoch(),
    }
    # Idempotent: a retry with the same key returns the original execution
    # instead of erroring.
    stored = store.save_execution(execution_record)
    return {
        "status": "executed",
        "execution_id": stored["execution_id"],
        "command_redacted": record.get("command_preview_redacted", ""),
        "pnr_context_version": body.get("pnr_context_version"),
    }


def review(body: Dict[str, Any], auth_context: AuthContext, action: str) -> Dict[str, Any]:
    require_any_role(auth_context, ["reviewer", "admin"])
    translation_id = body["translation_id"]
    record = store.get_translation(translation_id, auth_context.tenant_id)
    if not record:
        raise ValueError("translation not found")
    # maker-checker: the reviewer must not be the person who requested it.
    if record.get("created_by") == auth_context.subject:
        raise PermissionError("maker-checker violation: reviewer cannot be the requester")
    if record.get("status") not in ("manual_review", "need_clarification", "ready_for_confirm"):
        raise ValueError(f"translation is not reviewable: {record.get('status')}")

    new_status = "ready_for_confirm" if action == "approved" else "rejected"
    review_note = body.get("review_note", "")
    store.update_translation_status(
        translation_id,
        auth_context.tenant_id,
        new_status,
        reviewed_by=auth_context.subject,
        review_note=review_note,
    )
    return {
        "translation_id": translation_id,
        "status": new_status,
        "reviewed_by": auth_context.subject,
        "review_note": review_note,
    }


def parse_body(raw_body: Any) -> Dict[str, Any]:
    if not raw_body:
        return {}
    if isinstance(raw_body, dict):
        return raw_body
    return json.loads(raw_body)


def _merge_retrieval_hints(intermediate: Dict[str, Any], retrieval_context: Dict[str, Any]) -> Dict[str, Any]:
    hints = retrieval_context.get("hints") or {}
    entities = dict(intermediate.get("entities") or {})
    intent = intermediate.get("intent")
    if intent and intent.startswith("flight_search_"):
        for field in (
            "departure_code",
            "arrival_code",
            "departure_date",
            "departure_time",
            "return_date",
            "return_time",
            "airline",
            "return_airline",
            "direct",
            "no_stopovers",
            "display_mode",
            "segments",
        ):
            if entities.get(field) in (None, "", []):
                value = hints.get(field)
                if value not in (None, "", []):
                    entities[field] = value
    merged = dict(intermediate)
    merged["entities"] = entities
    return merged


def _apply_deterministic_fixes(intermediate: Dict[str, Any], redaction_mapping: Dict[str, str]) -> Dict[str, Any]:
    intent = intermediate.get("intent")
    entities = dict(intermediate.get("entities") or {})
    fixed = dict(intermediate)

    if intent == "add_contact_phone" and not entities.get("phone"):
        for token in redaction_mapping:
            if token.startswith("PHONE_"):
                entities["phone"] = token
                fixed["confidence"] = max(float(fixed.get("confidence") or 0), 0.95)
                fixed["risk_level"] = "low"
                break

    if intent == "cancel_segment":
        fixed["risk_level"] = "high"

    fixed["entities"] = entities
    return fixed
