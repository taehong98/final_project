from __future__ import annotations

import re

from .policy_heuristics import _classify_label, _split_labeled_line, normalize_space, strip_noise_lines


KEEP_PREFIXES = [
    "\uC815\uCC45\uBA85",
    "\uC815\uCC45 \uC694\uC57D",
    "\uC815\uCC45 \uC124\uBA85",
    "\uC9C0\uC6D0 \uB300\uC0C1",
    "\uC9C0\uC6D0 \uB0B4\uC6A9",
    "\uC9C0\uC6D0 \uAE08\uC561",
    "\uC2E0\uCCAD \uBC29\uBC95",
    "\uC2E0\uCCAD \uAE30\uAC04",
    "\uC81C\uCD9C \uC11C\uB958",
    "\uCD94\uAC00 \uC790\uACA9",
    "\uC81C\uD55C \uB300\uC0C1",
    "\uC2EC\uC0AC \uBC29\uBC95",
    "policy name",
    "summary",
    "description",
    "target",
    "benefit",
    "application",
]

INLINE_URL_RE = re.compile(r"https?://\S+")


def _is_prioritized_line(line: str) -> bool:
    lowered = normalize_space(line).lower()
    label, _ = _split_labeled_line(line)
    return bool(_classify_label(label)) or any(lowered.startswith(prefix.lower()) for prefix in KEEP_PREFIXES)


def clean_policy_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    without_noise = strip_noise_lines(raw)
    without_inline_urls = INLINE_URL_RE.sub("", without_noise)
    lines = [normalize_space(line) for line in without_inline_urls.splitlines() if normalize_space(line)]

    prioritized = [line for line in lines if _is_prioritized_line(line)]
    selected = prioritized or lines

    deduped: list[str] = []
    seen: set[str] = set()
    for line in selected:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
        if len(deduped) >= 14:
            break

    return "\n".join(deduped).strip()
