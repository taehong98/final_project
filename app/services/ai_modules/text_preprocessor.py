from __future__ import annotations

import re

KEEP_PREFIXES = [
    "정책명:", "정책 요약:", "정책 설명:", "지원 대상:", "지원 내용:", "지원 금액:",
    "신청 방법:", "신청 기간:", "제출 서류:", "추가 자격:", "제한 대상:",
    "선정 기준:", "신청 대상:", "유의 사항:", "제외 대상:",
]

DROP_PATTERNS = [
    r"https?://\S+",
    r"서비스URL\s*:\s*\S+",
    r"대표문의\s*:\s*.*",
    r"문의\s*:\s*.*",
    r"콜센터\s*[:：]?\s*[0-9\-\s/()]+",
    r"상담센터\s*[:：]?\s*[0-9\-\s/()]+",
]


def _normalize_line(line: str) -> str:
    line = str(line or "").strip()
    line = re.sub(r"\s+", " ", line)
    return line


def clean_policy_text(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""

    for pattern in DROP_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
    prioritized = [line for line in lines if any(line.startswith(prefix) for prefix in KEEP_PREFIXES)]
    selected = prioritized or lines

    deduped: list[str] = []
    seen: set[str] = set()
    for line in selected:
        if line in seen:
            continue
        deduped.append(line)
        seen.add(line)

    cleaned = "\n".join(deduped)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
