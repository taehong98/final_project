from __future__ import annotations

import re
from typing import Dict


GENERIC_EMPTY_VALUES = {
    "",
    "-",
    "none",
    "n/a",
    "null",
    "unknown",
    "\uC5C6\uC74C",
    "\uD574\uB2F9 \uC5C6\uC74C",
    "\uBBF8\uAE30\uC7AC",
}

FIELD_KEYWORDS = {
    "policy_name": [
        "\uC815\uCC45\uBA85",
        "policy_name",
        "policy name",
    ],
    "summary": [
        "\uC815\uCC45 \uC694\uC57D",
        "summary",
    ],
    "description": [
        "\uC815\uCC45 \uC124\uBA85",
        "description",
    ],
    "target": [
        "\uC9C0\uC6D0 \uB300\uC0C1",
        "\uB300\uC0C1",
        "target",
    ],
    "benefit": [
        "\uC9C0\uC6D0 \uB0B4\uC6A9",
        "\uC9C0\uC6D0 \uAE08\uC561",
        "\uD61C\uD0DD",
        "benefit",
    ],
    "conditions": [
        "\uC120\uC815 \uAE30\uC900",
        "\uCD94\uAC00 \uC790\uACA9",
        "\uC81C\uD55C \uB300\uC0C1",
        "\uC2EC\uC0AC \uBC29\uBC95",
        "condition",
        "conditions",
    ],
    "how_to_apply": [
        "\uC2E0\uCCAD \uBC29\uBC95",
        "\uC2E0\uCCAD \uAE30\uAC04",
        "\uC81C\uCD9C \uC11C\uB958",
        "apply",
        "application",
    ],
}

PHONE_RE = re.compile(r"(?:\+?\d[\d()\-\s]{7,}\d)")
URL_RE = re.compile(r"https?://\S+")
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
DATE_RE = re.compile(r"\b20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}\b")
AGE_RANGE_RE = re.compile(r"\b\d{1,2}\s*[~\-]\s*\d{1,2}\s*(?:\uC138|years?)?")
MONEY_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:\uB9CC\uC6D0|\uCC9C\uC6D0|\uC6D0|KRW|USD)\b", re.IGNORECASE)
PRESERVE_RE = re.compile(r"\[\[PRESERVE_\d+\]\]")

NOISE_KEYWORDS = [
    "\uB300\uD45C\uBB38\uC758",
    "\uBB38\uC758",
    "\uC0C1\uB2F4\uC13C\uD130",
    "\uCF5C\uC13C\uD130",
    "\uC804\uD654",
    "\uC5F0\uB77D\uCC98",
]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def is_emptyish(value: str) -> bool:
    normalized = normalize_space(value).lower()
    return normalized in GENERIC_EMPTY_VALUES


def _clean_field_value(value: str) -> str:
    cleaned = normalize_space(value).strip(" -:;,.")
    if is_emptyish(cleaned):
        return ""
    return cleaned


def _normalize_label(label: str) -> str:
    return normalize_space(label).lower().replace(" ", "")


def _classify_label(label: str) -> str | None:
    normalized = _normalize_label(label)
    for field, keywords in FIELD_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower().replace(" ", "") in normalized:
                return field
    return None


def _split_labeled_line(line: str) -> tuple[str, str]:
    for sep in (":", "\uff1a"):
        if sep in line:
            left, right = line.split(sep, 1)
            return left.strip(), right.strip()
    return "", line.strip()


def _looks_like_noise_line(line: str) -> bool:
    phone_hits = len(PHONE_RE.findall(line))
    digit_count = sum(ch.isdigit() for ch in line)
    if phone_hits >= 2:
        return True
    if digit_count >= 20 and phone_hits >= 1:
        return True
    if any(keyword in line for keyword in NOISE_KEYWORDS) and phone_hits >= 1:
        return True
    return False


def strip_noise_lines(text: str) -> str:
    lines = [normalize_space(line) for line in str(text or "").splitlines()]
    kept: list[str] = []

    for raw_line in lines:
        if not raw_line:
            continue
        label, _ = _split_labeled_line(raw_line)
        field = _classify_label(label)
        if _looks_like_noise_line(raw_line) and field is None:
            continue
        if URL_RE.fullmatch(raw_line):
            continue
        kept.append(raw_line)

    return "\n".join(kept).strip()


def clean_fact_value(value: str) -> str:
    value = URL_RE.sub("", str(value or ""))
    value = value.replace("||", ", ")
    value = re.sub(r"^[\-\*\u00B7\u2022\u25CB\u203B\u2460-\u2473\s]+", "", value)
    value = re.sub(
        r"^(?:\uC815\uCC45\uBA85|\uC815\uCC45 \uC694\uC57D|\uC815\uCC45 \uC124\uBA85|\uC9C0\uC6D0\uB300\uC0C1|\uC9C0\uC6D0 \uB300\uC0C1|\uC9C0\uC6D0\uB0B4\uC6A9|\uC9C0\uC6D0 \uB0B4\uC6A9|\uC9C0\uC6D0\uAE08\uC561|\uC9C0\uC6D0 \uAE08\uC561|\uC2E0\uCCAD\uBC29\uBC95|\uC2E0\uCCAD \uBC29\uBC95|\uC2E0\uCCAD\uAE30\uD55C|\uC2E0\uCCAD \uAE30\uAC04|\uC81C\uCD9C\uC11C\uB958|\uC81C\uCD9C \uC11C\uB958|\uCD94\uAC00\uC790\uACA9|\uCD94\uAC00 \uC790\uACA9|\uC81C\uD55C\uB300\uC0C1|\uC81C\uD55C \uB300\uC0C1|\uC2EC\uC0AC\uBC29\uBC95|\uC2EC\uC0AC \uBC29\uBC95)\s*[:\uFF1A]\s*",
        "",
        value,
    )
    value = normalize_space(value)
    return _clean_field_value(value)


def extract_policy_facts(policy_text: str) -> Dict[str, str]:
    cleaned_text = strip_noise_lines(policy_text)
    facts: Dict[str, list[str]] = {
        "policy_name": [],
        "summary": [],
        "description": [],
        "target": [],
        "benefit": [],
        "conditions": [],
        "how_to_apply": [],
    }

    current_field: str | None = None

    for line in cleaned_text.splitlines():
        label, value = _split_labeled_line(line)
        field = _classify_label(label)
        if field:
            candidate = clean_fact_value(value)
            if candidate:
                facts[field].append(candidate)
            current_field = field
            continue

        if current_field and current_field != "policy_name" and not _looks_like_noise_line(line):
            continuation = clean_fact_value(line)
            if continuation:
                if facts[current_field]:
                    merged_value = f"{facts[current_field][-1]} {continuation}".strip()
                    facts[current_field][-1] = normalize_space(merged_value)[:240]
                else:
                    facts[current_field].append(continuation)

    merged: Dict[str, str] = {}
    for field, candidates in facts.items():
        merged[field] = candidates[0] if candidates else ""

    if not merged["policy_name"]:
        first_line = cleaned_text.splitlines()[0] if cleaned_text else ""
        merged["policy_name"] = clean_fact_value(first_line)

    if not merged["benefit"]:
        merged["benefit"] = merged["summary"] or merged["description"]

    if not merged["conditions"] and merged["description"]:
        merged["conditions"] = merged["description"]

    if not merged["target"] and merged["summary"]:
        merged["target"] = merged["summary"]

    return merged


def choose_better_value(primary: str, secondary: str) -> str:
    primary = clean_fact_value(primary)
    secondary = clean_fact_value(secondary)
    if primary and not _looks_too_generic(primary):
        return primary
    return secondary


def _looks_too_generic(value: str) -> bool:
    normalized = normalize_space(value).lower()
    if normalized in {"none", "not provided", "unknown", "n/a"}:
        return True
    if normalized in {"\uC5C6\uC74C", "\uBBF8\uAE30\uC7AC"}:
        return True
    if "please provide" in normalized:
        return True
    if normalized.count("none") >= 2:
        return True
    return False


def assemble_korean_summary(facts: Dict[str, str]) -> str:
    policy_name = choose_better_value(facts.get("policy_name", ""), "\uD574\uB2F9 \uC815\uCC45")
    target = clean_fact_value(facts.get("target", ""))
    benefit = clean_fact_value(facts.get("benefit", ""))
    conditions = clean_fact_value(facts.get("conditions", ""))
    how_to_apply = clean_fact_value(facts.get("how_to_apply", ""))

    sentences: list[str] = []
    if target:
        sentences.append(f"{policy_name}\uC758 \uC8FC\uC694 \uB300\uC0C1\uC740 {target}\uC785\uB2C8\uB2E4.")
    else:
        sentences.append(f"{policy_name}\uC5D0 \uB300\uD55C \uC815\uCC45 \uC548\uB0B4\uC785\uB2C8\uB2E4.")

    if benefit:
        sentences.append(f"\uC8FC\uC694 \uC9C0\uC6D0 \uB0B4\uC6A9\uC740 {benefit}\uC785\uB2C8\uB2E4.")
    if conditions:
        sentences.append(f"\uD655\uC778\uD574\uC57C \uD560 \uC8FC\uC694 \uC870\uAC74\uC740 {conditions}\uC785\uB2C8\uB2E4.")
    if how_to_apply:
        sentences.append(f"\uC2E0\uCCAD\uC740 {how_to_apply} \uBC29\uC2DD\uC73C\uB85C \uC9C4\uD589\uD569\uB2C8\uB2E4.")

    return " ".join(sentences[:4]).strip()


def protect_special_tokens(text: str) -> tuple[str, dict[str, str]]:
    protected = str(text or "")
    replacements: dict[str, str] = {}
    counter = 1

    patterns = [
        URL_RE,
        DATE_RE,
        PERCENT_RE,
        AGE_RANGE_RE,
        MONEY_RE,
    ]

    def replace_match(match: re.Match[str]) -> str:
        nonlocal counter
        token = f"[[PRESERVE_{counter}]]"
        counter += 1
        replacements[token] = match.group(0)
        return token

    for pattern in patterns:
        protected = pattern.sub(replace_match, protected)

    return protected, replacements


def restore_special_tokens(text: str, replacements: dict[str, str]) -> str:
    restored = str(text or "")
    for token, original in replacements.items():
        restored = restored.replace(token, original)
    return restored


def count_preserve_tokens(text: str) -> int:
    return len(PRESERVE_RE.findall(str(text or "")))
