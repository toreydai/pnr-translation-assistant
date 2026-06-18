import re
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class RedactionResult:
    text: str
    mapping: Dict[str, str] = field(default_factory=dict)


PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?\d[\d -]{8,}\d)(?!\d)")),
    # Document/ID numbers: 6-20 uppercase alphanumerics that contain at least
    # one digit. The digit requirement avoids redacting all-letter tokens such
    # as airport/airline/SSR codes (e.g. PEKCAN, VGML) that are not PII.
    ("DOC_ID", re.compile(r"(?<![A-Za-z0-9])(?=[A-Z0-9]*[0-9])[A-Z0-9]{6,20}(?![A-Za-z0-9])")),
]


def redact(text: str) -> RedactionResult:
    mapping: Dict[str, str] = {}
    redacted = text
    for label, pattern in PATTERNS:
        counter = 1

        def replace(match: re.Match[str]) -> str:
            nonlocal counter
            token = f"{label}_{counter}"
            counter += 1
            mapping[token] = match.group(0)
            return token

        redacted = pattern.sub(replace, redacted)
    return RedactionResult(text=redacted, mapping=mapping)

