import re
from datetime import date, timedelta
from typing import Optional


MONTH_MAP = {
    1: "jan",
    2: "feb",
    3: "mar",
    4: "apr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dec",
}


def format_pnr_date(value: str, base_date: Optional[date] = None, include_year: bool = True) -> Optional[str]:
    if not value:
        return None
    base = base_date or date.today()
    text = str(value).strip().lower()
    if re.match(r"^\d{2}[a-z]{3}(\d{2})?$", text):
        return text

    holiday_map = {
        "元旦": date(base.year + (1 if base.month > 1 else 0), 1, 1),
        "五一": date(base.year + (1 if base.month > 5 else 0), 5, 1),
        "国庆": date(base.year + (1 if base.month > 10 else 0), 10, 1),
    }
    for keyword, resolved in holiday_map.items():
        if keyword in text:
            return _format_date(resolved, include_year)

    if "大后天" in text:
        return _format_date(base + timedelta(days=3), include_year)
    if "后天" in text:
        return _format_date(base + timedelta(days=2), include_year)
    if "明天" in text:
        return _format_date(base + timedelta(days=1), include_year)
    if "今天" in text:
        return _format_date(base, include_year)

    next_month_match = re.search(r"下个月\s*(\d{1,2})[号日]?", text)
    if next_month_match:
        month = base.month + 1
        year = base.year
        if month == 13:
            month = 1
            year += 1
        return _format_date(date(year, month, int(next_month_match.group(1))), include_year)

    full_match = re.search(r"(?:(\d{4})年)?\s*(\d{1,2})月\s*(\d{1,2})[号日]?", text)
    if full_match:
        year = int(full_match.group(1) or base.year)
        month = int(full_match.group(2))
        day = int(full_match.group(3))
        return _format_date(date(year, month, day), include_year)

    return None


def format_pnr_time(value: str) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if re.match(r"^\d{4}$", text):
        return text
    defaults = {
        "上午": "0600",
        "中午": "1200",
        "下午": "1200",
        "晚上": "1800",
        "凌晨": "0000",
    }
    for keyword, formatted in defaults.items():
        if keyword in text and not re.search(r"\d{1,2}[点:：]", text):
            return formatted

    match = re.search(r"(?:(上午|下午|晚上|凌晨|中午))?\s*(\d{1,2})[点:：](\d{1,2})?", text)
    if match:
        period = match.group(1) or ""
        hour = int(match.group(2))
        minute = int(match.group(3) or 0)
        if period in ("下午", "晚上") and hour < 12:
            hour += 12
        if period == "凌晨" and hour == 12:
            hour = 0
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02d}{minute:02d}"
    return None


def _format_date(value: date, include_year: bool) -> str:
    suffix = f"{value.year % 100:02d}" if include_year else ""
    return f"{value.day:02d}{MONTH_MAP[value.month]}{suffix}"

