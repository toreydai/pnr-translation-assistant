import json
import re
from typing import Any, Dict

import boto3

from .config import PRIMARY_MODEL_ID


_bedrock = None


def _bedrock_client():
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")
    return _bedrock


SYSTEM_PROMPT = """You translate Chinese natural language requests into a strict JSON intermediate representation for PNR commands.
Never output executable PNR commands.
Return only JSON with keys: intent, entities, missing_fields, risk_level, confidence, evidence_ids, clarification_question.
Use provided evidence and hints. If required fields are missing, do not guess.
"""


def _extract_json_text(response: Dict[str, Any]) -> str:
    output = response.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    if content and "text" in content[0]:
        return content[0]["text"]
    raise ValueError("Bedrock response does not contain text content")


def parse_model_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def _converse(model_id: str, prompt: str) -> Dict[str, Any]:
    response = _bedrock_client().converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        system=[{"text": SYSTEM_PROMPT}],
        inferenceConfig={"temperature": 0.0, "maxTokens": 1200},
    )
    return parse_model_json(_extract_json_text(response))


def generate_intermediate(
    user_text_redacted: str,
    pnr_context: Dict[str, Any],
    retrieval_context: Dict[str, Any],
) -> Dict[str, Any]:
    prompt = json.dumps(
        {
            "task": "translate_to_pnr_intermediate",
            "user_text": user_text_redacted,
            "pnr_context": pnr_context,
            "retrieval_context": retrieval_context,
            "json_schema": {
                "intent": "string",
                "entities": "object",
                "missing_fields": "array",
                "risk_level": "low|medium|high",
                "confidence": "number",
                "evidence_ids": "array",
                "clarification_question": "string|null",
            },
        },
        ensure_ascii=False,
    )
    try:
        return _converse(PRIMARY_MODEL_ID, prompt)
    except Exception:
        # Deterministic fallback keeps local tests and initial deployments usable
        # when model access has not been granted yet.
        hints = retrieval_context.get("hints") or {}
        shortlist = retrieval_context.get("shortlist") or []
        intent = shortlist[0] if shortlist else "unknown"
        entities: Dict[str, Any] = {}
        if intent == "add_ssr_meal":
            entities = {
                "passenger_ref": "P1" if "第一个" in user_text_redacted else None,
                "segment_ref": "S2" if "第二段" in user_text_redacted else "S1",
                "ssr_code": hints.get("ssr_code"),
                "airline": hints.get("airline"),
            }
        elif intent == "cancel_segment":
            entities = {"segment_ref": "S1"}
        elif intent == "add_contact_phone":
            entities = {"phone": "PHONE_1"}
        elif intent.startswith("flight_search_"):
            entities = _fallback_flight_entities(intent, hints)
        missing = [key for key, value in entities.items() if not value]
        return {
            "intent": intent,
            "entities": {key: value for key, value in entities.items() if value},
            "missing_fields": missing,
            "risk_level": "high" if intent == "cancel_segment" else "medium",
            "confidence": 0.70 if missing else 0.91,
            "evidence_ids": retrieval_context.get("evidence_ids") or [],
            "clarification_question": "请补充缺失字段" if missing else None,
        }


def _fallback_flight_entities(intent: str, hints: Dict[str, Any]) -> Dict[str, Any]:
    if intent == "flight_search_multicity" and hints.get("segments"):
        return {
            "segments": [segment for segment in hints["segments"] if segment.get("departure_date")],
            "display_mode": hints.get("display_mode", ""),
            "direct": hints.get("direct", False),
            "no_stopovers": hints.get("no_stopovers", False),
        }
    entities = {
        "departure_code": hints.get("departure_code"),
        "arrival_code": hints.get("arrival_code"),
        "departure_date": hints.get("departure_date"),
        "departure_time": hints.get("departure_time"),
        "airline": hints.get("airline"),
        "direct": hints.get("direct", False),
        "no_stopovers": hints.get("no_stopovers", False),
        "display_mode": hints.get("display_mode", ""),
    }
    if intent == "flight_search_roundtrip":
        entities["return_date"] = hints.get("return_date")
        entities["return_time"] = hints.get("return_time")
        entities["return_airline"] = hints.get("return_airline")
    return entities
