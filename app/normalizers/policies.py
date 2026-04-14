from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    PolicyApplication,
    PolicyBenefit,
    PolicyCondition,
    PolicyDocument,
    PolicyLaw,
    PolicyMaster,
    PolicyRelatedLink,
    PolicyTag,
    RawPolicyConditionItem,
    RawPolicyDetailItem,
    RawPolicyListItem,
    RawPolicySubresourceItem,
)


GOV24_INCOME_CODE_MAP = {
    "JA0201": ("MID_0_50", "중위소득 50% 이하"),
    "JA0202": ("MID_51_75", "중위소득 51~75%"),
    "JA0203": ("MID_76_100", "중위소득 76~100%"),
    "JA0204": ("MID_101_200", "중위소득 101~200%"),
    "JA0205": ("MID_200_PLUS", "중위소득 200% 초과"),
}

GOV24_EMPLOYMENT_CODE_MAP = {
    "JA0326": ("EMPLOYED", "재직자"),
    "JA0327": ("UNEMPLOYED", "미취업자"),
    "JA0328": ("AGRICULTURE_FISHERY", "농어업인"),
}

GOV24_HOUSEHOLD_CODE_MAP = {
    "JA0404": ("SINGLE", "1인 가구"),
    "JA0411": ("MULTI_CHILD", "다자녀 가구"),
    "JA0412": ("HOMELESS_HOUSEHOLD", "무주택 세대"),
    "JA0414": ("SINGLE_PARENT", "한부모 가구"),
}

GOV24_SPECIAL_TARGET_CODE_MAP = {
    "JA0401": ("MULTICULTURAL", "다문화 가정"),
    "JA0402": ("NORTH_KOREAN_DEFECTOR", "북한이탈주민"),
    "JA0403": ("MULTI_CHILD", "다자녀 대상"),
    "JA0413": ("NEW_MOVE_IN", "신규 전입"),
}

GOV24_CONDITION_DESCRIPTION_MAP = {
    "JA0101": "남성 대상",
    "JA0102": "여성 대상",
    "JA0110": "최소 연령 조건",
    "JA0111": "최대 연령 조건",
    "JA0201": "중위소득 50% 이하",
    "JA0202": "중위소득 51~75%",
    "JA0203": "중위소득 76~100%",
    "JA0204": "중위소득 101~200%",
    "JA0205": "중위소득 200% 초과",
    "JA0326": "재직자",
    "JA0327": "미취업자",
    "JA0328": "농어업인",
    "JA0401": "다문화 가정",
    "JA0402": "북한이탈주민",
    "JA0403": "다자녀",
    "JA0404": "1인 가구",
    "JA0411": "다자녀 가구",
    "JA0412": "무주택 세대",
    "JA0413": "신규 전입",
    "JA0414": "한부모 가구",
}

BOKJIRO_LIFE_CYCLE_MAP = {
    "영유아": "INFANT",
    "아동": "CHILD",
    "청소년": "YOUTH",
    "청년": "YOUNG_ADULT",
    "중장년": "MIDDLE_AGED",
    "노년": "SENIOR",
}

GENERIC_MISSING_VALUES = {"", "해당없음", "없음", "-", "null", "NULL", None}
TRUE_MARKERS = {"Y", "y", "예", "1", 1, True}
NON_BENEFIT_KEYWORDS = ("본인부담", "개인부담", "자부담", "수수료", "본인 부담")


def make_policy_id(source: str, source_policy_id: str) -> str:
    return f"{source}__{source_policy_id}"


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return None if text in GENERIC_MISSING_VALUES else text


def value_of(payload: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_datetime_value(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def normalize_split_items(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = str(value).replace("\r", "\n").replace("||", "\n")
    normalized = normalized.replace("•", "\n").replace("·", "\n")
    results: list[str] = []
    for part in normalized.splitlines():
        cleaned = part.strip(" \t\r\n-")
        if cleaned and cleaned not in GENERIC_MISSING_VALUES:
            results.append(cleaned)
    return results


def split_csv_items(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def first_url(*values: str | None) -> str | None:
    pattern = re.compile(r"https?://[^\s)]+")
    for value in values:
        if not value:
            continue
        match = pattern.search(str(value))
        if match:
            return match.group(0)
    return None


def format_amount_label(amount: int | None) -> str | None:
    if amount is None:
        return None
    if amount >= 10000 and amount % 10000 == 0:
        return f"최대 {amount // 10000:,}만원"
    return f"최대 {amount:,}원"


def _eligible_amount_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.replace("\r", "\n").splitlines() if line.strip()]
    filtered = []
    for line in lines:
        if any(keyword in line for keyword in NON_BENEFIT_KEYWORDS) and "지원" not in line:
            continue
        filtered.append(line)
    return filtered or [text]


def _extract_year_hint(text: str) -> int | None:
    year4 = re.search(r"(20\d{2})\s*[년./-]", text)
    if year4:
        return int(year4.group(1))
    year2 = re.search(r"[\"']?(\d{2})\s*년", text)
    if year2:
        return 2000 + int(year2.group(1))
    return None


def extract_amount_info(text: str | None) -> tuple[int | None, str | None]:
    if not text:
        return None, None

    candidates: list[int] = []
    for line in _eligible_amount_lines(str(text)):
        monthly_patterns = [
            r"월\s*(?:최대\s*)?(\d[\d,]*)\s*(만원|천원|원)\s*(?:씩)?\s*(?:최장|최대)?\s*(\d+)\s*개월",
            r"(\d[\d,]*)\s*(만원|천원|원)\s*[xX×]\s*(\d+)\s*개월",
        ]
        for pattern in monthly_patterns:
            for amount, unit, months in re.findall(pattern, line):
                multiplier = {"원": 1, "천원": 1000, "만원": 10000}[unit]
                candidates.append(int(amount.replace(",", "")) * multiplier * int(months))

        for amount, unit in re.findall(r"(?:월|연간|연|최대|1인당|인당)?\s*(\d[\d,]*)\s*(만원|천원|원)", line):
            multiplier = {"원": 1, "천원": 1000, "만원": 10000}[unit]
            candidates.append(int(amount.replace(",", "")) * multiplier)

    if not candidates:
        return None, None

    candidates = [amount for amount in candidates if 0 < amount <= 2_000_000_000]
    if not candidates:
        return None, None

    amount = max(candidates)
    return amount, format_amount_label(amount)


def extract_period_label(text: str | None, fallback: str | None = None) -> str | None:
    if text:
        match = re.search(r"월\s*(?:최대\s*)?(\d[\d,]*)\s*(만원|천원|원)\s*(?:씩)?\s*(?:최장|최대)?\s*(\d+)\s*개월", text)
        if match:
            amount, unit, months = match.groups()
            unit_label = {"원": "원", "천원": "천원", "만원": "만원"}[unit]
            return f"월 {int(amount.replace(',', '')):,}{unit_label} x {months}개월"
    return clean_text(fallback)


def parse_date_range(text: str | None) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    raw_text = str(text)
    matches = re.findall(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw_text)
    if matches:
        normalized = [f"{year}-{int(month):02d}-{int(day):02d}" for year, month, day in matches]
        return normalized[0], normalized[1] if len(normalized) > 1 else None

    korean_matches = re.findall(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", raw_text)
    if korean_matches:
        normalized = [f"{year}-{int(month):02d}-{int(day):02d}" for year, month, day in korean_matches]
        return normalized[0], normalized[1] if len(normalized) > 1 else None

    year_hint = _extract_year_hint(raw_text)
    short_matches = re.findall(r"(?<!\d)(\d{1,2})[.](\d{1,2})(?!\d)", raw_text)
    if year_hint and short_matches:
        normalized = [f"{year_hint}-{int(month):02d}-{int(day):02d}" for month, day in short_matches]
        return normalized[0], normalized[1] if len(normalized) > 1 else None

    return None, None


def parse_application_period_type(text: str | None) -> str | None:
    if not text:
        return None
    if "상시" in text:
        return "ALWAYS_OPEN"
    if "공고" in text or "별도" in text or "추후" in text:
        return "ANNOUNCEMENT"
    if parse_date_range(text)[0]:
        return "FIXED_PERIOD"
    return None


def bool_from_marker(value: Any) -> bool | None:
    if value is None:
        return None
    return value in TRUE_MARKERS


def active_labels_from_map(raw: dict[str, Any], code_map: dict[str, tuple[str, str]]) -> tuple[list[str], list[str]]:
    active = [(code, values) for code, values in code_map.items() if bool_from_marker(raw.get(code))]
    if not active:
        return [], []
    if len(active) == len(code_map):
        return [], []
    codes = [code for code, _ in active]
    labels = [desc for _, (_, desc) in active]
    normalized = [normalized_code for _, (normalized_code, _) in active]
    return normalized, [f"{code}: {label}" for code, label in zip(codes, labels)]


def latest_raw_map(db: Session, model: Any, source: str) -> dict[str, dict[str, Any]]:
    subquery = (
        select(model.source_policy_id, func.max(model.id).label("max_id"))
        .where(model.source == source)
        .group_by(model.source_policy_id)
        .subquery()
    )
    rows = db.execute(select(model).join(subquery, model.id == subquery.c.max_id)).scalars().all()
    return {row.source_policy_id: row.raw_json for row in rows}


def latest_subresource_map(db: Session, source: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    subquery = (
        select(
            RawPolicySubresourceItem.source_policy_id,
            RawPolicySubresourceItem.subresource_type,
            func.max(RawPolicySubresourceItem.id).label("max_id"),
        )
        .where(RawPolicySubresourceItem.source == source)
        .group_by(RawPolicySubresourceItem.source_policy_id, RawPolicySubresourceItem.subresource_type)
        .subquery()
    )
    rows = db.execute(select(RawPolicySubresourceItem).join(subquery, RawPolicySubresourceItem.id == subquery.c.max_id)).scalars().all()
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
    for row in rows:
        items = row.raw_json.get("items", [])
        if isinstance(items, dict):
            items = [items]
        grouped[row.source_policy_id][row.subresource_type] = [item for item in items if isinstance(item, dict)]
    return grouped


def reset_policy_children(db: Session, policy_id: str) -> None:
    db.execute(delete(PolicyDocument).where(PolicyDocument.policy_id == policy_id))
    db.execute(delete(PolicyRelatedLink).where(PolicyRelatedLink.policy_id == policy_id))
    db.execute(delete(PolicyLaw).where(PolicyLaw.policy_id == policy_id))
    db.execute(delete(PolicyTag).where(PolicyTag.policy_id == policy_id))


def add_tags(db: Session, policy_id: str, tag_type: str, labels: Iterable[str]) -> None:
    seen: set[str] = set()
    for label in labels:
        for item in normalize_split_items(label):
            cleaned = clean_text(item)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            db.add(
                PolicyTag(
                    policy_id=policy_id,
                    tag_type=tag_type,
                    tag_code=cleaned,
                    tag_label=cleaned,
                )
            )


def add_link(
    db: Session,
    policy_id: str,
    link_type: str,
    link_name: str | None,
    link_url: str | None,
    sort_order: int,
    seen_urls: set[str],
) -> int:
    clean_url = clean_text(link_url)
    clean_name = clean_text(link_name)
    dedupe_key = clean_url
    if link_type == "form" and clean_name:
        dedupe_key = f"form:{clean_name}"
    if not clean_url or dedupe_key in seen_urls:
        return sort_order
    seen_urls.add(dedupe_key)
    db.add(
        PolicyRelatedLink(
            policy_id=policy_id,
            link_type=link_type,
            link_name=clean_name,
            link_url=clean_url,
            sort_order=sort_order,
        )
    )
    return sort_order + 1


def add_document(
    db: Session,
    *,
    seen_keys: set[tuple[str, str]],
    policy_id: str,
    document_group: str,
    document_name: str | None,
    document_type: str | None,
    document_description: str | None,
    is_required: bool,
    issued_within_days: int | None,
    source: str,
    file_url: str | None,
    normalized_at: datetime,
) -> None:
    clean_name = clean_text(document_name)
    clean_url = clean_text(file_url)
    if not clean_name:
        return
    dedupe_key = (document_group, clean_name)
    if dedupe_key in seen_keys:
        return
    seen_keys.add(dedupe_key)
    db.add(
        PolicyDocument(
            policy_id=policy_id,
            document_type=document_type,
            document_name=clean_name[:500],
            document_description=clean_text(document_description) or clean_name,
            is_required=is_required,
            issued_within_days=issued_within_days,
            source=source,
            document_group=document_group,
            file_url=clean_url,
            normalized_at=normalized_at,
        )
    )


def format_contact_lines(items: list[dict[str, Any]]) -> str | None:
    lines: list[str] = []
    for item in items:
        name = clean_text(item.get("servSeDetailNm"))
        value = clean_text(item.get("servSeDetailLink"))
        if not name and not value:
            continue
        lines.append(f"{name}: {value}" if name and value else (name or value or ""))
    return clean_text("\n".join(lines))


def format_application_method_lines(items: list[dict[str, Any]]) -> str | None:
    lines: list[str] = []
    for item in items:
        name = clean_text(item.get("servSeDetailNm"))
        value = clean_text(item.get("servSeDetailLink"))
        if name and value:
            lines.append(f"{name}: {value}")
        elif value:
            lines.append(value)
        elif name:
            lines.append(name)
    return clean_text("\n".join(lines))


def extract_application_period_from_text(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        for line in str(text).replace("\r", "\n").splitlines():
            stripped = line.strip()
            if "신청기간" in stripped or "접수기간" in stripped:
                return clean_text(stripped)
    return None


def extract_gov24_detail_row(detail_payload: dict[str, Any], expected_service_id: str | None = None) -> dict[str, Any]:
    if not isinstance(detail_payload, dict):
        return {}
    data_node = detail_payload.get("data")
    rows: list[dict[str, Any]] = []
    if isinstance(data_node, list):
        rows = [item for item in data_node if isinstance(item, dict)]
    elif isinstance(data_node, dict):
        rows = [data_node]
    if not rows:
        return {}
    if expected_service_id:
        expected = str(expected_service_id)
        for row in rows:
            detail_service_id = clean_text(value_of(row, "서비스ID", "serviceId", "servId"))
            if detail_service_id and str(detail_service_id) == expected:
                return row
        return {}
    return rows[0]


def compose_condition_description(raw: dict[str, Any], detail_raw: dict[str, Any]) -> str | None:
    lines = [clean_text(value_of(detail_raw, "선정기준")), clean_text(value_of(detail_raw, "지원대상"))]
    active_descriptions = []
    for code, description in GOV24_CONDITION_DESCRIPTION_MAP.items():
        value = raw.get(code)
        if value is None:
            continue
        if isinstance(value, (int, float)) and code in {"JA0110", "JA0111"}:
            active_descriptions.append(f"{description}: {value}")
        elif bool_from_marker(value):
            active_descriptions.append(f"{code}: {description}")
    if active_descriptions:
        lines.append("조건 코드 해석: " + ", ".join(active_descriptions[:12]))
    filtered = [line for line in lines if line]
    return clean_text("\n\n".join(filtered))


def normalize_gov24(db: Session) -> int:
    list_map = latest_raw_map(db, RawPolicyListItem, "gov24")
    detail_map = latest_raw_map(db, RawPolicyDetailItem, "gov24")
    condition_map = latest_raw_map(db, RawPolicyConditionItem, "gov24")

    count = 0
    for source_policy_id, list_raw in list_map.items():
        detail_raw = extract_gov24_detail_row(detail_map.get(source_policy_id, {}), expected_service_id=source_policy_id)
        condition_raw = condition_map.get(source_policy_id, {})
        policy_id = make_policy_id("gov24", source_policy_id)
        now = datetime.utcnow()

        title = clean_text(value_of(list_raw, "서비스명")) or clean_text(value_of(detail_raw, "서비스명")) or source_policy_id
        summary = clean_text(value_of(list_raw, "서비스목적요약", "서비스목적"))
        description = clean_text(
            "\n\n".join(
                part
                for part in [
                    clean_text(value_of(detail_raw, "서비스목적", "서비스목적요약")),
                    clean_text(value_of(detail_raw, "지원대상")),
                    clean_text(value_of(detail_raw, "선정기준")),
                    clean_text(value_of(detail_raw, "지원내용")),
                ]
                if part
            )
        )
        application_method_text = clean_text(value_of(detail_raw, "신청방법")) or clean_text(value_of(list_raw, "신청방법"))
        application_period_text = clean_text(value_of(detail_raw, "신청기한")) or clean_text(value_of(list_raw, "신청기한"))
        source_url = clean_text(value_of(list_raw, "상세조회URL"))
        application_url = clean_text(value_of(detail_raw, "온라인신청사이트URL")) or first_url(application_method_text, source_url)
        benefit_text = clean_text(value_of(detail_raw, "지원내용")) or clean_text(value_of(list_raw, "지원내용"))
        benefit_amount_value, _ = extract_amount_info(benefit_text)

        income_codes, income_descriptions = active_labels_from_map(condition_raw, GOV24_INCOME_CODE_MAP)
        employment_codes, employment_descriptions = active_labels_from_map(condition_raw, GOV24_EMPLOYMENT_CODE_MAP)
        household_codes, household_descriptions = active_labels_from_map(condition_raw, GOV24_HOUSEHOLD_CODE_MAP)
        special_target_codes, special_target_descriptions = active_labels_from_map(condition_raw, GOV24_SPECIAL_TARGET_CODE_MAP)
        user_types = normalize_split_items(clean_text(value_of(list_raw, "사용자구분")))

        db.merge(
            PolicyMaster(
                policy_id=policy_id,
                source="gov24",
                source_policy_id=source_policy_id,
                title=title,
                summary=summary,
                description=description,
                category_large=clean_text(value_of(list_raw, "서비스분야")),
                category_medium=", ".join(user_types) if user_types else None,
                source_url=source_url,
                application_url=application_url,
                managing_agency=clean_text(value_of(detail_raw, "소관기관명", "소관기관", "제공기관명")) or clean_text(value_of(list_raw, "소관기관명")),
                operating_agency=clean_text(value_of(list_raw, "부서명", "부처명")),
                contact_text=clean_text(value_of(detail_raw, "문의처")) or clean_text(value_of(list_raw, "전화문의")),
                support_cycle=clean_text(value_of(detail_raw, "지원주기")),
                provision_type=clean_text(value_of(detail_raw, "지원유형")) or clean_text(value_of(list_raw, "지원유형")),
                online_apply_yn=bool(application_url) or ("온라인" in (application_method_text or "")),
                registered_at=parse_datetime_value(value_of(list_raw, "등록일시")),
                updated_at=parse_datetime_value(value_of(detail_raw, "수정일시") or value_of(list_raw, "수정일시")),
                status_active_yn=True,
                normalized_at=now,
            )
        )

        db.merge(
            PolicyCondition(
                policy_id=policy_id,
                age_min=value_of(condition_raw, "JA0110"),
                age_max=value_of(condition_raw, "JA0111"),
                age_limit_yn=value_of(condition_raw, "JA0110") is not None or value_of(condition_raw, "JA0111") is not None,
                gender_male_yn=bool_from_marker(condition_raw.get("JA0101")),
                gender_female_yn=bool_from_marker(condition_raw.get("JA0102")),
                income_code=",".join(income_codes) if income_codes else None,
                income_min_amount=None,
                income_max_amount=None,
                income_text=", ".join(income_descriptions) if income_descriptions else None,
                household_type_codes_json=household_codes or None,
                employment_codes_json=employment_codes or None,
                housing_codes_json=None,
                life_cycle_codes_json=None,
                school_codes_json=None,
                major_codes_json=None,
                marriage_codes_json=None,
                region_codes_json=None,
                special_target_codes_json=special_target_codes or None,
                additional_qualification_text=compose_condition_description(condition_raw, detail_raw),
                restricted_target_text=clean_text(value_of(detail_raw, "지원대상")),
                condition_source_confidence=0.95,
                normalized_at=now,
            )
        )

        db.merge(
            PolicyBenefit(
                policy_id=policy_id,
                benefit_detail_text=benefit_text,
                benefit_amount_raw_text=benefit_text,
                benefit_amount_value=benefit_amount_value,
                currency="KRW" if benefit_amount_value else None,
                benefit_period_label=extract_period_label(benefit_text),
                support_scale_count=None,
                support_scale_limit_yn=None,
                first_come_first_served_yn="선착순" in (benefit_text or ""),
                normalized_at=now,
            )
        )

        start_date, end_date = parse_date_range(application_period_text)
        db.merge(
            PolicyApplication(
                policy_id=policy_id,
                application_method_text=application_method_text,
                application_period_text=application_period_text,
                application_period_type_code=parse_application_period_type(application_period_text),
                business_period_start_date=start_date,
                business_period_end_date=end_date,
                business_period_etc_text=None,
                screening_method_text=clean_text(value_of(detail_raw, "선정기준")),
                application_url=application_url,
                online_apply_yn=bool(application_url) or ("온라인" in (application_method_text or "")),
                receiving_org_name=clean_text(value_of(detail_raw, "접수기관명", "접수기관")) or clean_text(value_of(list_raw, "접수기관")),
                processing_note_text=None,
                normalized_at=now,
            )
        )

        reset_policy_children(db, policy_id)
        seen_documents: set[tuple[str, str]] = set()
        seen_urls: set[str] = set()

        for group, text in [
            ("submission", clean_text(value_of(detail_raw, "구비서류"))),
            ("self_verify", clean_text(value_of(detail_raw, "본인확인필요구비서류"))),
            ("official_verify", clean_text(value_of(detail_raw, "공무원확인구비서류"))),
        ]:
            for item in normalize_split_items(text):
                add_document(
                    db,
                    seen_keys=seen_documents,
                    policy_id=policy_id,
                    document_group=group,
                    document_name=item,
                    document_type=None,
                    document_description=item,
                    is_required=True,
                    issued_within_days=90 if "3개월" in item else None,
                    source="gov24",
                    file_url=None,
                    normalized_at=now,
                )

        sort_order = 1
        sort_order = add_link(db, policy_id, "apply", "온라인 신청", application_url, sort_order, seen_urls)
        sort_order = add_link(db, policy_id, "detail", "정부24 상세", source_url, sort_order, seen_urls)

        seen_laws: set[str] = set()
        for law_name in normalize_split_items(clean_text(value_of(detail_raw, "법령"))):
            normalized_law_name = clean_text(law_name)
            if not normalized_law_name or normalized_law_name in seen_laws:
                continue
            seen_laws.add(normalized_law_name)
            db.add(
                PolicyLaw(
                    policy_id=policy_id,
                    law_name=normalized_law_name[:500],
                    law_type="law",
                    source="gov24",
                )
            )

        add_tags(db, policy_id, "topic", [clean_text(value_of(list_raw, "서비스분야")) or ""])
        add_tags(db, policy_id, "user_type", user_types)
        add_tags(db, policy_id, "household", household_descriptions)
        add_tags(db, policy_id, "employment", employment_descriptions)
        add_tags(db, policy_id, "special_target", special_target_descriptions)

        count += 1

    db.commit()
    return count


def normalize_bokjiro(db: Session) -> int:
    list_map = latest_raw_map(db, RawPolicyListItem, "bokjiro")
    detail_map = latest_raw_map(db, RawPolicyDetailItem, "bokjiro")
    sub_map = latest_subresource_map(db, "bokjiro")

    count = 0
    for source_policy_id, list_raw in list_map.items():
        detail_root = detail_map.get(source_policy_id, {})
        detail_raw = detail_root.get("wantedDtl", {}) if isinstance(detail_root, dict) else {}
        subresources = sub_map.get(source_policy_id, {})
        policy_id = make_policy_id("bokjiro", source_policy_id)
        now = datetime.utcnow()

        title = clean_text(value_of(detail_raw, "servNm")) or clean_text(value_of(list_raw, "servNm")) or source_policy_id
        summary = clean_text(value_of(list_raw, "servDgst")) or clean_text(value_of(detail_raw, "wlfareInfoOutlCn"))
        description = clean_text(
            "\n\n".join(
                part
                for part in [
                    clean_text(value_of(detail_raw, "wlfareInfoOutlCn")),
                    clean_text(value_of(detail_raw, "tgtrDtlCn")),
                    clean_text(value_of(detail_raw, "slctCritCn")),
                    clean_text(value_of(detail_raw, "alwServCn")),
                ]
                if part
            )
        )

        life_cycles = [BOKJIRO_LIFE_CYCLE_MAP[item] for item in split_csv_items(value_of(list_raw, "lifeArray")) if item in BOKJIRO_LIFE_CYCLE_MAP]
        special_targets = split_csv_items(value_of(list_raw, "trgterIndvdlArray"))
        topic_tags = split_csv_items(value_of(list_raw, "intrsThemaArray"))

        apply_items = subresources.get("applmetList", [])
        contact_items = subresources.get("inqplCtadrList", [])
        homepage_items = subresources.get("inqplHmpgReldList", [])
        form_items = subresources.get("basfrmList", [])
        law_items = subresources.get("baslawList", [])

        application_method_text = format_application_method_lines(apply_items)
        contact_text = format_contact_lines(contact_items) or clean_text(value_of(list_raw, "rprsCtadr"))
        source_url = clean_text(value_of(list_raw, "servDtlLink"))
        application_url = first_url(*(item.get("servSeDetailLink") for item in homepage_items), source_url)
        benefit_text = clean_text(value_of(detail_raw, "alwServCn")) or clean_text(value_of(list_raw, "servDgst"))
        benefit_amount_value, _ = extract_amount_info(benefit_text)

        application_period_text = clean_text(value_of(detail_raw, "aplyYmdCn")) or extract_application_period_from_text(
            clean_text(value_of(detail_raw, "alwServCn")),
            clean_text(value_of(detail_raw, "wlfareInfoOutlCn")),
            clean_text(value_of(list_raw, "servDgst")),
        )
        start_date, end_date = parse_date_range(application_period_text)

        db.merge(
            PolicyMaster(
                policy_id=policy_id,
                source="bokjiro",
                source_policy_id=source_policy_id,
                title=title,
                summary=summary,
                description=description,
                category_large=clean_text(value_of(list_raw, "srvPvsnNm")),
                category_medium=", ".join(topic_tags) if topic_tags else None,
                source_url=source_url,
                application_url=application_url,
                managing_agency=clean_text(value_of(detail_raw, "jurMnofNm")) or clean_text(value_of(list_raw, "jurMnofNm")),
                operating_agency=clean_text(value_of(list_raw, "jurOrgNm")),
                contact_text=contact_text,
                support_cycle=clean_text(value_of(list_raw, "sprtCycNm")),
                provision_type=clean_text(value_of(list_raw, "srvPvsnNm")),
                online_apply_yn=value_of(list_raw, "onapPsbltYn") == "Y",
                registered_at=parse_datetime_value(value_of(list_raw, "svcfrstRegTs")),
                updated_at=None,
                status_active_yn=True,
                normalized_at=now,
            )
        )

        db.merge(
            PolicyCondition(
                policy_id=policy_id,
                age_min=None,
                age_max=None,
                age_limit_yn=None,
                gender_male_yn=None,
                gender_female_yn=None,
                income_code=None,
                income_min_amount=None,
                income_max_amount=None,
                income_text=None,
                household_type_codes_json=None,
                employment_codes_json=None,
                housing_codes_json=None,
                life_cycle_codes_json=life_cycles or None,
                school_codes_json=None,
                major_codes_json=None,
                marriage_codes_json=None,
                region_codes_json=None,
                special_target_codes_json=special_targets or None,
                additional_qualification_text=clean_text(value_of(detail_raw, "slctCritCn")),
                restricted_target_text=clean_text(value_of(detail_raw, "tgtrDtlCn")),
                condition_source_confidence=0.70,
                normalized_at=now,
            )
        )

        db.merge(
            PolicyBenefit(
                policy_id=policy_id,
                benefit_detail_text=benefit_text,
                benefit_amount_raw_text=benefit_text,
                benefit_amount_value=benefit_amount_value,
                currency="KRW" if benefit_amount_value else None,
                benefit_period_label=extract_period_label(benefit_text, clean_text(value_of(list_raw, "sprtCycNm"))),
                support_scale_count=None,
                support_scale_limit_yn=None,
                first_come_first_served_yn="선착순" in (benefit_text or ""),
                normalized_at=now,
            )
        )

        db.merge(
            PolicyApplication(
                policy_id=policy_id,
                application_method_text=application_method_text,
                application_period_text=application_period_text,
                application_period_type_code=parse_application_period_type(application_period_text),
                business_period_start_date=start_date,
                business_period_end_date=end_date,
                business_period_etc_text=None,
                screening_method_text=clean_text(value_of(detail_raw, "slctCritCn")),
                application_url=application_url,
                online_apply_yn=value_of(list_raw, "onapPsbltYn") == "Y",
                receiving_org_name=clean_text(value_of(detail_raw, "jurMnofNm")) or clean_text(value_of(list_raw, "jurMnofNm")),
                processing_note_text=None,
                normalized_at=now,
            )
        )

        reset_policy_children(db, policy_id)
        seen_documents: set[tuple[str, str]] = set()
        seen_urls: set[str] = set()

        for item in form_items:
            name = clean_text(item.get("servSeDetailNm"))
            url = clean_text(item.get("servSeDetailLink"))
            add_document(
                db,
                seen_keys=seen_documents,
                policy_id=policy_id,
                document_group="form",
                document_name=name,
                document_type="FORM",
                document_description=name,
                is_required=False,
                issued_within_days=None,
                source="bokjiro",
                file_url=url,
                normalized_at=now,
            )

        sort_order = 1
        sort_order = add_link(db, policy_id, "detail", "복지로 상세", source_url, sort_order, seen_urls)
        sort_order = add_link(db, policy_id, "apply", "신청 또는 안내 링크", application_url, sort_order, seen_urls)
        for item in homepage_items:
            sort_order = add_link(
                db,
                policy_id,
                "homepage",
                clean_text(item.get("servSeDetailNm")),
                clean_text(item.get("servSeDetailLink")),
                sort_order,
                seen_urls,
            )
        for item in form_items:
            sort_order = add_link(
                db,
                policy_id,
                "form",
                clean_text(item.get("servSeDetailNm")),
                clean_text(item.get("servSeDetailLink")),
                sort_order,
                seen_urls,
            )

        seen_laws: set[str] = set()
        for item in law_items:
            law_name = clean_text(item.get("servSeDetailNm"))
            if not law_name or law_name in seen_laws:
                continue
            seen_laws.add(law_name)
            db.add(PolicyLaw(policy_id=policy_id, law_name=law_name[:500], law_type="law", source="bokjiro"))

        add_tags(db, policy_id, "topic", topic_tags)
        add_tags(db, policy_id, "life_cycle", life_cycles)
        add_tags(db, policy_id, "special_target", special_targets)
        add_tags(db, policy_id, "provision_type", [clean_text(value_of(list_raw, "srvPvsnNm")) or ""])

        count += 1

    db.commit()
    return count
