import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RiskPolicy:
    level: str
    auto_execute: bool
    min_confidence: float


@dataclass(frozen=True)
class CommandDefinition:
    intent: str
    description: str
    required_fields: List[str]
    optional_fields: List[str]
    enum_constraints: Dict[str, List[str]]
    format_constraints: Dict[str, str]
    render_template: str
    risk_policy: RiskPolicy
    status: str = "active"


COMMANDS: Dict[str, CommandDefinition] = {
    "add_ssr_meal": CommandDefinition(
        intent="add_ssr_meal",
        description="添加特殊餐食 SSR",
        required_fields=["passenger_ref", "segment_ref", "ssr_code", "airline"],
        optional_fields=[],
        enum_constraints={"ssr_code": ["VGML", "AVML", "CHML", "BBML"]},
        format_constraints={
            "passenger_ref": r"^P[0-9]+$",
            "segment_ref": r"^S[0-9]+$",
            "airline": r"^[A-Z0-9]{2}$",
        },
        render_template="SSR {ssr_code} {airline} HK1/{passenger_ref}/{segment_ref}",
        risk_policy=RiskPolicy(level="low", auto_execute=True, min_confidence=0.85),
    ),
    "add_contact_phone": CommandDefinition(
        intent="add_contact_phone",
        description="添加联系电话",
        required_fields=["phone"],
        optional_fields=[],
        enum_constraints={},
        format_constraints={"phone": r"^PHONE_[0-9]+$|^\+?[0-9][0-9 -]{7,20}$"},
        render_template="CTCM {phone}",
        risk_policy=RiskPolicy(level="low", auto_execute=False, min_confidence=0.90),
    ),
    "cancel_segment": CommandDefinition(
        intent="cancel_segment",
        description="取消航段",
        required_fields=["segment_ref"],
        optional_fields=[],
        enum_constraints={},
        format_constraints={"segment_ref": r"^S[0-9]+$"},
        render_template="XI {segment_ref}",
        risk_policy=RiskPolicy(level="high", auto_execute=False, min_confidence=0.95),
    ),
    "flight_search_oneway": CommandDefinition(
        intent="flight_search_oneway",
        description="查询单程航班可用性",
        required_fields=["departure_code", "arrival_code", "departure_date"],
        optional_fields=["departure_time", "airline", "direct", "no_stopovers", "display_mode"],
        enum_constraints={"display_mode": ["h", "a", "o", "m", ""]},
        format_constraints={
            "departure_code": r"^[A-Z]{3}$",
            "arrival_code": r"^[A-Z]{3}$",
            "departure_date": r"^[0-9]{2}[a-z]{3}([0-9]{2})?$",
            "departure_time": r"^[0-9]{4}$",
            "airline": r"^[A-Z0-9]{2}$",
        },
        render_template="",
        risk_policy=RiskPolicy(level="low", auto_execute=False, min_confidence=0.85),
    ),
    "flight_search_roundtrip": CommandDefinition(
        intent="flight_search_roundtrip",
        description="查询往返航班可用性",
        required_fields=["departure_code", "arrival_code", "departure_date", "return_date"],
        optional_fields=["departure_time", "return_time", "airline", "return_airline", "direct", "no_stopovers", "display_mode"],
        enum_constraints={"display_mode": ["h", "a", "o", "m", ""]},
        format_constraints={
            "departure_code": r"^[A-Z]{3}$",
            "arrival_code": r"^[A-Z]{3}$",
            "departure_date": r"^[0-9]{2}[a-z]{3}([0-9]{2})?$",
            "return_date": r"^[0-9]{2}[a-z]{3}([0-9]{2})?$",
            "departure_time": r"^[0-9]{4}$",
            "return_time": r"^[0-9]{4}$",
            "airline": r"^[A-Z0-9]{2}$",
            "return_airline": r"^[A-Z0-9]{2}$",
        },
        render_template="",
        risk_policy=RiskPolicy(level="low", auto_execute=False, min_confidence=0.85),
    ),
    "flight_search_multicity": CommandDefinition(
        intent="flight_search_multicity",
        description="查询多段航班可用性",
        required_fields=["segments"],
        optional_fields=["display_mode", "direct", "no_stopovers"],
        enum_constraints={"display_mode": ["h", "a", "o", "m", ""]},
        format_constraints={},
        render_template="",
        risk_policy=RiskPolicy(level="low", auto_execute=False, min_confidence=0.85),
    ),
}


def get_command(intent: str) -> Optional[CommandDefinition]:
    command = COMMANDS.get(intent)
    if command and command.status == "active":
        return command
    return None


def validate(intermediate: Dict[str, Any], pnr_context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    intent = intermediate.get("intent")
    command = get_command(intent)
    if not command:
        return [f"unsupported intent: {intent}"]

    entities = intermediate.get("entities") or {}
    for field in command.required_fields:
        if entities.get(field) in (None, ""):
            errors.append(f"missing required field: {field}")

    for field, allowed in command.enum_constraints.items():
        value = entities.get(field)
        if value and value not in allowed:
            errors.append(f"invalid enum {field}: {value}")

    for field, pattern in command.format_constraints.items():
        value = entities.get(field)
        if value and not re.match(pattern, str(value)):
            errors.append(f"invalid format {field}: {value}")

    if intent == "flight_search_multicity":
        segments = entities.get("segments") or []
        if not isinstance(segments, list) or len(segments) < 2:
            errors.append("segments must contain at least two flight segments")
        for index, segment in enumerate(segments):
            for field in ("departure_code", "arrival_code", "departure_date"):
                if not segment.get(field):
                    errors.append(f"segments[{index}] missing {field}")

    passenger_refs = set(pnr_context.get("passenger_refs") or [])
    segment_refs = set(pnr_context.get("segment_refs") or [])
    passenger_ref = entities.get("passenger_ref")
    segment_ref = entities.get("segment_ref")
    if passenger_ref and passenger_refs and passenger_ref not in passenger_refs:
        errors.append(f"passenger_ref not in current PNR: {passenger_ref}")
    if segment_ref and segment_refs and segment_ref not in segment_refs:
        errors.append(f"segment_ref not in current PNR: {segment_ref}")

    return errors


def normalize(intermediate: Dict[str, Any]) -> Dict[str, Any]:
    command = get_command(intermediate.get("intent"))
    if not command:
        return intermediate
    allowed_fields = set(command.required_fields)
    allowed_fields.update(command.optional_fields)
    allowed_fields.update(command.enum_constraints.keys())
    allowed_fields.update(command.format_constraints.keys())
    entities = intermediate.get("entities") or {}
    entities = _normalize_flight_entities(intermediate.get("intent"), entities)
    normalized = dict(intermediate)
    normalized["entities"] = {
        field: value for field, value in entities.items() if field in allowed_fields
    }
    normalized["missing_fields"] = [
        field
        for field in command.required_fields
        if normalized["entities"].get(field) in (None, "", [])
    ]
    return normalized


def _normalize_flight_entities(intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:
    if not intent or not intent.startswith("flight_search_"):
        return entities

    normalized = dict(entities)
    for field in ("airline", "return_airline"):
        if isinstance(normalized.get(field), dict):
            normalized[field] = normalized[field].get("code")
    for field in ("departure_date", "return_date"):
        if isinstance(normalized.get(field), str):
            normalized[field] = normalized[field].lower()

    if intent == "flight_search_multicity":
        segments = []
        for segment in normalized.get("segments") or []:
            item = dict(segment)
            if isinstance(item.get("departure_location"), dict) and not item.get("departure_code"):
                item["departure_code"] = item["departure_location"].get("code")
            if isinstance(item.get("arrival_location"), dict) and not item.get("arrival_code"):
                item["arrival_code"] = item["arrival_location"].get("code")
            if isinstance(item.get("departure_date"), str):
                item["departure_date"] = item["departure_date"].lower()
            segments.append(item)
        normalized["segments"] = segments
    return normalized


def render(intermediate: Dict[str, Any]) -> str:
    command = get_command(intermediate["intent"])
    if not command:
        raise ValueError(f"unsupported intent: {intermediate.get('intent')}")
    entities = intermediate.get("entities") or {}
    if intermediate["intent"].startswith("flight_search_"):
        return _render_flight_search(intermediate["intent"], entities)
    return command.render_template.format(**entities)


def reverse_parse(command: str, intermediate: Dict[str, Any]) -> bool:
    try:
        return command == render(intermediate)
    except Exception:
        return False


def _render_flight_search(intent: str, entities: Dict[str, Any]) -> str:
    display_mode = entities.get("display_mode", "")
    prefix = f"av:{display_mode}" if display_mode else "av:"
    if intent == "flight_search_oneway":
        return _render_segment(prefix, entities)
    if intent == "flight_search_roundtrip":
        outbound = _render_segment(prefix, entities)
        ret = _render_return_segment(entities)
        return f"{outbound}&{ret}"
    if intent == "flight_search_multicity":
        segments = entities.get("segments") or []
        if not segments:
            raise ValueError("segments required")
        rendered = [_render_segment(prefix, segments[0])]
        rendered.extend(_render_segment("", segment).lstrip("av:") for segment in segments[1:])
        return "&".join(rendered)
    raise ValueError(f"unsupported flight search intent: {intent}")


def _render_segment(prefix: str, values: Dict[str, Any]) -> str:
    command = f"{prefix}/{values['departure_code']}{values['arrival_code']}/{values['departure_date']}"
    for field in ("departure_time", "airline"):
        if values.get(field):
            command += f"/{values[field]}"
    if values.get("direct"):
        command += "/d"
    if values.get("no_stopovers"):
        command += "/n"
    return command


def _render_return_segment(values: Dict[str, Any]) -> str:
    command = values["return_date"]
    if values.get("return_time"):
        command += f"/{values['return_time']}"
    if values.get("return_airline") or values.get("airline"):
        command += f"/{values.get('return_airline') or values.get('airline')}"
    if values.get("direct"):
        command += "/d"
    if values.get("no_stopovers"):
        command += "/n"
    return command
