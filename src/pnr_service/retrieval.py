import re
from typing import Any, Dict, List, Optional

from .formatters import format_pnr_date, format_pnr_time

TERM_MAP = {
    "素食": {"intent": "add_ssr_meal", "ssr_code": "VGML", "evidence": "term:vgml"},
    "儿童餐": {"intent": "add_ssr_meal", "ssr_code": "CHML", "evidence": "term:chml"},
    "婴儿餐": {"intent": "add_ssr_meal", "ssr_code": "BBML", "evidence": "term:bbml"},
    "联系电话": {"intent": "add_contact_phone", "evidence": "cmd:add_contact_phone"},
    "取消": {"intent": "cancel_segment", "evidence": "cmd:cancel_segment"},
}

AIRLINES = {
    "东航": "MU",
    "南航": "CZ",
    "国航": "CA",
    "海航": "HU",
}

LOCATIONS = {
    "北京": "PEK",
    "首都机场": "PEK",
    "大兴": "PKX",
    "广州": "CAN",
    "成都": "CTU",
    "上海": "SHA",
    "虹桥": "SHA",
    "浦东": "PVG",
    "香港": "HKG",
    "山西": "TYN",
    "太原": "TYN",
    "内蒙": "HET",
    "内蒙古": "HET",
    "呼和浩特": "HET",
    "西藏": "LXA",
    "拉萨": "LXA",
}


def intent_shortlist(text: str) -> List[str]:
    intents: List[str] = []
    if _looks_like_flight_search(text):
        if any(keyword in text for keyword in ("往返", "回来", "回程", "第二天")):
            intents.append("flight_search_roundtrip")
        elif any(keyword in text for keyword in ("多段", "第二段", "再到", "然后到")):
            intents.append("flight_search_multicity")
        else:
            intents.append("flight_search_oneway")
    for keyword, value in TERM_MAP.items():
        if keyword in text and value["intent"] not in intents:
            intents.append(value["intent"])
    return intents or ["flight_search_oneway", "add_ssr_meal", "add_contact_phone", "cancel_segment"]


def retrieve(text: str, shortlist: List[str]) -> Dict[str, Any]:
    evidence_ids: List[str] = []
    hints: Dict[str, Any] = {}
    for keyword, value in TERM_MAP.items():
        if keyword in text and value["intent"] in shortlist:
            evidence_ids.append(value["evidence"])
            hints.update({k: v for k, v in value.items() if k not in ("intent", "evidence")})
    for keyword, airline in AIRLINES.items():
        if keyword in text:
            hints["airline"] = airline
            evidence_ids.append(f"term:airline:{airline}")
    locations = extract_locations(text)
    if locations:
        hints["locations"] = locations
        evidence_ids.extend(f"term:location:{item['code']}" for item in locations)
    flight_hints = extract_flight_hints(text)
    hints.update({key: value for key, value in flight_hints.items() if value not in (None, [], "")})
    return {
        "shortlist": shortlist,
        "hints": hints,
        "evidence_ids": sorted(set(evidence_ids)),
        "knowledge_version": "builtin-2026-06-16",
    }


def _looks_like_flight_search(text: str) -> bool:
    return any(keyword in text for keyword in ("飞", "航班", "去", "到", "中转", "经停", "往返"))


def extract_locations(text: str) -> List[Dict[str, str]]:
    matches: List[Dict[str, str]] = []
    for name, code in sorted(LOCATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        if name in text and code not in [item["code"] for item in matches]:
            matches.append({"name": name, "code": code})
    return matches


def extract_flight_hints(text: str) -> Dict[str, Any]:
    locations = extract_locations(text)
    hints: Dict[str, Any] = {
        "direct": "直飞" in text,
        "no_stopovers": "无经停" in text,
        "display_mode": _display_mode(text),
        "departure_date": _extract_date(text),
        "departure_time": _extract_time(text),
    }
    if len(locations) >= 2:
        hints["departure_code"] = locations[0]["code"]
        hints["arrival_code"] = locations[1]["code"]
    if any(keyword in text for keyword in ("往返", "回来", "回程", "第二天")):
        hints["return_date"] = _extract_return_date(text)
        hints["return_time"] = _extract_return_time(text)
    if len(locations) >= 4:
        hints["segments"] = [
            {
                "departure_code": locations[0]["code"],
                "arrival_code": locations[1]["code"],
                "departure_date": hints.get("departure_date"),
                "departure_time": hints.get("departure_time"),
            },
            {
                "departure_code": locations[2]["code"],
                "arrival_code": locations[3]["code"],
                "departure_date": hints.get("return_date") or _extract_second_date(text),
                "departure_time": hints.get("return_time"),
            },
        ]
    return hints


def _display_mode(text: str) -> str:
    if "完整" in text:
        return "h"
    if "按到达时间" in text:
        return "a"
    if "承运" in text:
        return "o"
    if "中转" in text or "经停" in text:
        return "m"
    return ""


def _extract_date(text: str) -> Optional[str]:
    for pattern in (
        r"大后天|后天|明天|今天|元旦|五一|国庆",
        r"下个月\s*\d{1,2}[号日]?",
        r"(?:\d{4}年)?\s*\d{1,2}月\s*\d{1,2}[号日]?",
    ):
        match = re.search(pattern, text)
        if match:
            return format_pnr_date(match.group(0))
    return None


def _extract_second_date(text: str) -> Optional[str]:
    matches = re.findall(r"(?:\d{4}年)?\s*\d{1,2}月\s*\d{1,2}[号日]?", text)
    if len(matches) >= 2:
        return format_pnr_date(matches[1])
    return None


def _extract_return_date(text: str) -> Optional[str]:
    if "第二天" in text:
        first = _extract_date(text)
        if first:
            # Let the model resolve exact return dates when relative to arbitrary dates.
            return first
    return _extract_second_date(text) or _extract_date(text)


def _extract_time(text: str) -> Optional[str]:
    match = re.search(r"(上午|下午|晚上|凌晨|中午)?\s*\d{1,2}[点:：]\d{0,2}|上午|下午|晚上|凌晨|中午", text)
    if match:
        return format_pnr_time(match.group(0))
    return None


def _extract_return_time(text: str) -> Optional[str]:
    matches = re.findall(r"(?:上午|下午|晚上|凌晨|中午)?\s*\d{1,2}[点:：]\d{0,2}|上午|下午|晚上|凌晨|中午", text)
    if len(matches) >= 2:
        return format_pnr_time(matches[1])
    return None
