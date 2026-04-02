from __future__ import annotations

import logging
import re
from typing import Any

from main_pipeline import BenePickPipeline

log = logging.getLogger("benefic.analysis")

_PIPELINE = None


def _get_pipeline() -> BenePickPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = BenePickPipeline(csv_path="benepick_dict.csv")
    return _PIPELINE


def _make_slug(name: str, idx: int = 0) -> str:
    slug = re.sub(r"[^\w가-힣]", "-", str(name)).strip("-").lower()
    slug = re.sub(r"-+", "-", slug)
    return slug or f"policy-{idx}"


def _score_to_css(score: int) -> dict:
    if score >= 80:
        return {
            "card_class": "top",
            "percent_class": "high",
            "progress_color": "green",
            "icon_color": "green",
            "badge_class": "badge-green",
            "badge_label": "✅ 조건 충족",
        }
    elif score >= 60:
        return {
            "card_class": "mid",
            "percent_class": "mid",
            "progress_color": "blue",
            "icon_color": "blue",
            "badge_class": "badge-blue",
            "badge_label": "⚡ 확인 필요",
        }
    else:
        return {
            "card_class": "low",
            "percent_class": "low",
            "progress_color": "orange",
            "icon_color": "orange",
            "badge_class": "badge-orange",
            "badge_label": "⚠️ 조건 부족",
        }


def _pick_icon(policy: dict[str, Any]) -> str:
    text = f"{policy.get('서비스분야', '')} {policy.get('지원유형', '')} {policy.get('서비스명', '')}"
    icon_map = {
        "주거": "🏠",
        "월세": "🏠",
        "취업": "💼",
        "고용": "💼",
        "교육": "🎓",
        "장학": "🎓",
        "의료": "🏥",
        "건강": "🏥",
        "보육": "👶",
        "돌봄": "👶",
        "금융": "🏦",
        "대출": "🏦",
        "현금": "💰",
        "수당": "💰",
    }
    for key, icon in icon_map.items():
        if key in text:
            return icon
    return "📋"


def _extract_benefit(policy: dict[str, Any]) -> str:
    text = str(policy.get("지원내용") or policy.get("서비스목적요약") or "").strip()

    monthly_multi = re.search(r"월\s*([\d,]+)\s*만\s*원?\s*[×x]\s*최대\s*(\d+)\s*개월", text)
    if monthly_multi:
        monthly = int(monthly_multi.group(1).replace(",", ""))
        months = int(monthly_multi.group(2))
        return f"최대 {monthly * months:,}만원"

    manwon_matches = re.findall(r"(최대|월|연|1인당|가구당)?\s*([\d,]+)\s*만\s*원", text)
    if manwon_matches:
        best_val = 0
        best_label = ""
        for prefix, num in manwon_matches:
            value = int(num.replace(",", ""))
            if value > best_val:
                best_val = value
                best_label = prefix.strip()
        if best_val > 0:
            return f"{best_label} {best_val:,}만원".strip()

    won_matches = re.findall(r"([\d,]+)\s*원", text)
    if won_matches:
        try:
            values = [int(x.replace(",", "")) for x in won_matches]
            max_val = max(values)
            if max_val >= 10000:
                return f"최대 {max_val // 10000:,}만원"
            return f"최대 {max_val:,}원"
        except Exception:
            pass

    return "지원내용 확인"


def _make_subtitle(policy: dict[str, Any]) -> str:
    parts = []

    target = str(policy.get("지원대상") or "").strip()
    criteria = str(policy.get("선정기준") or "").strip()
    region = str(policy.get("소관기관명") or "").strip()

    if target:
        parts.append(target[:20])
    if criteria:
        parts.append(criteria[:20])
    elif region:
        parts.append(region[:20])

    if not parts:
        return "세부 조건 확인 필요"

    return " · ".join(parts[:2])


def _pick(user: dict, *keys, default="미입력"):
    for key in keys:
        value = user.get(key)
        if value is not None and value != "":
            return value
    return default


def _bool_label(value) -> str:
    return "예" if bool(value) else "아니오"


def _build_user_condition_text(user: dict) -> str:
    age = _pick(user, "나이", "age")
    annual_income = _pick(user, "연소득", "annual_income")
    income_percent = _pick(user, "income_percent")
    household_type = _pick(user, "가구유형", "household_type")
    household_size = _pick(user, "가구원수", "household_size")
    region = _pick(user, "거주지역", "region")
    employment_status = _pick(user, "고용상태", "employment_status")
    disability = _pick(user, "장애여부", "disability", default="없음")
    veteran = _pick(user, "국가유공자", "veteran", default=False)
    multicultural = _pick(user, "다문화가구", "multicultural", default=False)

    lines = []

    lines.append(f"나이: {age}세" if age != "미입력" else "나이: 미입력")
    lines.append(f"거주지역: {region}")
    lines.append(f"고용상태: {employment_status}")
    lines.append(f"가구유형: {household_type}")
    lines.append(f"가구원수: {household_size}명" if household_size != "미입력" else "가구원수: 미입력")
    lines.append(f"장애여부: {disability}")
    lines.append(f"국가유공자: {_bool_label(veteran)}")
    lines.append(f"다문화가구: {_bool_label(multicultural)}")

    if income_percent != "미입력":
        lines.append(f"소득평가액 비율: {income_percent}%")
        lines.append(f"중위소득 기준: {income_percent}%")
    else:
        lines.append("소득평가액 비율: 미입력")

    if annual_income != "미입력":
        lines.append(f"연소득: {annual_income}만원")
    else:
        lines.append("연소득: 미입력")

    return ", ".join(lines)


def _contains_korean(text: str) -> bool:
    return bool(re.search(r"[가-힣]", str(text or "")))


def _normalize_text(text: str) -> str:
    text = str(text or "").strip()
    replacements = {
        "나이이(가)": "나이가",
        "소득평가액 비율이(가)": "소득평가액 비율이",
        "정책 기준에 따라 탈락 사유가 확인되지 않음": "정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다.",
        "정책 기준에 따라 탈락 사유가 확인되지 않았습니다": "정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다.",
        "정책 기준에 따라 탈락 사유가 확인되지 않음.": "정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다.",
        "정책 기준에 따라 탈락 사유가 확인되지 않았습니다.": "정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다.",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\.\.+", ".", text)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\s+,", ",", text)
    return text


def _protect_named_entities(text: str, lang: str) -> str:
    text = str(text or "")

    # 잘못 번역된 서울 교정
    text = text.replace("東京", "서울")
    text = text.replace("东京", "서울")

    if lang == "ja":
        text = text.replace("서울시민", "ソウル市民")
        text = text.replace("서울시", "ソウル市")
        text = text.replace("서울", "ソウル")
    elif lang == "zh":
        text = text.replace("서울시민", "首尔市民")
        text = text.replace("서울시", "首尔市")
        text = text.replace("서울", "首尔")
    elif lang == "en":
        text = text.replace("서울시민", "Seoul citizens")
        text = text.replace("서울시", "Seoul")
        text = text.replace("서울", "Seoul")
    elif lang == "vi":
        text = text.replace("서울시민", "công dân Seoul")
        text = text.replace("서울시", "Seoul")
        text = text.replace("서울", "Seoul")
    elif lang == "ko":
        text = text.replace("Seoul", "서울")

    return text


def _translate_fixed_text(text: str, lang: str) -> str:
    text = _normalize_text(text)
    if not text or lang == "ko" or not _contains_korean(text):
        return text

    patterns = {
        "en": [
            (r"정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다\.?", "No clear disqualification reason was identified under the policy criteria."),
            (r"정책 원문에서 판정 가능한 핵심 수치 조건을 찾지 못했습니다\.?", "The core numerical conditions that can be determined from the policy document were not found."),
            (r"나이가 최대 기준을 초과합니다\.?", "The age exceeds the maximum allowed threshold."),
            (r"소득평가액 비율이 최대 기준을 초과합니다\.?", "The assessed income ratio exceeds the maximum allowed threshold."),
            (r"정책의 연령 기준을 다시 확인하고, 공고문에 출생연도 기준이나 예외 조건이 있는지 확인하세요\.?", "Please review the age requirement again and check whether the notice includes birth-year rules or exception clauses."),
            (r"소득평가액이 기준 범위에 들어가는지 다시 확인하고, 공고문상 예외 기준이나 공제 항목이 있는지 확인하세요\.?", "Please verify again whether the assessed income falls within the required range and check the notice for exceptions or deductible items."),
            (r"\(기준:\s*([^)]+?),\s*현재:\s*([^)]+?)\)", r"(Standard: \1, Current: \2)"),
        ],
        "zh": [
            (r"정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다\.?", "根据政策标准，未发现明确的不符合原因。"),
            (r"정책 원문에서 판정 가능한 핵심 수치 조건을 찾지 못했습니다\.?", "未能在政策原文中找到可判定的核心数值条件。"),
            (r"나이가 최대 기준을 초과합니다\.?", "年龄超过了最高标准。"),
            (r"소득평가액 비율이 최대 기준을 초과합니다\.?", "收入评估比例超过了最高标准。"),
            (r"정책의 연령 기준을 다시 확인하고, 공고문에 출생연도 기준이나 예외 조건이 있는지 확인하세요\.?", "请再次确认政策的年龄标准，并查看公告中是否有按出生年份计算或例外条件。"),
            (r"소득평가액이 기준 범위에 들어가는지 다시 확인하고, 공고문상 예외 기준이나 공제 항목이 있는지 확인하세요\.?", "请再次确认收入评估额是否在标准范围内，并查看公告中是否有例外标准或扣除项目。"),
            (r"\(기준:\s*([^)]+?),\s*현재:\s*([^)]+?)\)", r"（标准：\1，当前：\2）"),
        ],
        "ja": [
            (r"정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다\.?", "政策基準上、明確な不適格理由は確認されませんでした。"),
            (r"정책 원문에서 판정 가능한 핵심 수치 조건을 찾지 못했습니다\.?", "政策原文から判定可能な主要数値条件を見つけられませんでした。"),
            (r"나이가 최대 기준을 초과합니다\.?", "年齢が上限基準を超えています。"),
            (r"소득평가액 비율이 최대 기준을 초과합니다\.?", "所得評価額の比率が上限基準を超えています。"),
            (r"정책의 연령 기준을 다시 확인하고, 공고문에 출생연도 기준이나 예외 조건이 있는지 확인하세요\.?", "政策の年齢基準を再確認し、公示文に出生年基準や例外条件があるか確認してください。"),
            (r"소득평가액이 기준 범위에 들어가는지 다시 확인하고, 공고문상 예외 기준이나 공제 항목이 있는지 확인하세요\.?", "所得評価額が基準範囲内に入るか再確認し、公示文上の例外基準や控除項目があるか確認してください。"),
            (r"\(기준:\s*([^)]+?),\s*현재:\s*([^)]+?)\)", r"（基準：\1、現在：\2）"),
        ],
        "vi": [
            (r"정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다\.?", "Không phát hiện lý do bị loại rõ ràng theo tiêu chí của chính sách."),
            (r"정책 원문에서 판정 가능한 핵심 수치 조건을 찾지 못했습니다\.?", "Không tìm thấy điều kiện số liệu cốt lõi có thể xác định từ văn bản chính sách gốc."),
            (r"나이가 최대 기준을 초과합니다\.?", "Tuổi vượt quá ngưỡng tối đa cho phép."),
            (r"소득평가액 비율이 최대 기준을 초과합니다\.?", "Tỷ lệ thu nhập được đánh giá vượt quá ngưỡng tối đa cho phép."),
            (r"정책의 연령 기준을 다시 확인하고, 공고문에 출생연도 기준이나 예외 조건이 있는지 확인하세요\.?", "Hãy kiểm tra lại điều kiện tuổi của chính sách và xem thông báo có 기준 theo năm sinh hoặc điều kiện ngoại lệ hay không."),
            (r"소득평가액이 기준 범위에 들어가는지 다시 확인하고, 공고문상 예외 기준이나 공제 항목이 있는지 확인하세요\.?", "Hãy kiểm tra lại xem mức thu nhập được đánh giá có nằm trong phạm vi tiêu chuẩn hay không, và xem thông báo có tiêu chuẩn ngoại lệ hoặc khoản khấu trừ hay không."),
            (r"\(기준:\s*([^)]+?),\s*현재:\s*([^)]+?)\)", r"(Tiêu chuẩn: \1, Hiện tại: \2)"),
        ],
    }

    for pattern, replacement in patterns.get(lang, []):
        text = re.sub(pattern, replacement, text)

    return text



def _translate_threshold_tokens(text: str, lang: str) -> str:
    text = str(text or "")

    if lang == "en":
        text = re.sub(r"(\d+)\s*세\s*이하", r"\1 or younger", text)
        text = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*이하", r"\1% or lower", text)

    elif lang == "zh":
        text = re.sub(r"(\d+)\s*세\s*이하", r"\1岁以下", text)
        text = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*이하", r"\1%以下", text)

    elif lang == "ja":
        text = re.sub(r"(\d+)\s*세\s*이하", r"\1歳以下", text)
        text = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*이하", r"\1%以下", text)

    elif lang == "vi":
        text = re.sub(r"(\d+)\s*세\s*이하", r"từ \1 tuổi trở xuống", text)
        text = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*이하", r"\1% trở xuống", text)

    return text



def _force_phrase_fixes(text: str, lang: str) -> str:
    text = str(text or "")

    if lang == "en":
        replacements = {
            "Policy criteria do not confirm disqualification reason": "No clear disqualification reason was identified under the policy criteria.",
            "Policy criteria do not confirm the reason for disqualification": "No clear disqualification reason was identified under the policy criteria.",
            "Current: 27세": "Current: 27",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"Current:\s*(\d+)\s*세", r"Current: \1", text)

    elif lang == "zh":
        replacements = {
            "根据政策标准，未确认淘汰原因": "根据政策标准，未发现明确的不符合原因。",
            "首尔에서 월세 거주 중인": "在首尔租房居住的",
            "19세부터 39세까지의": "19岁至39岁的",
            "재산은 일반재산": "财产需满足一般财产",
            "임차 보증금이 :": "租赁保证金为",
            "当前：27세": "当前：27",
            "현재：27세": "当前：27",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"当前[:：]\s*(\d+)\s*세", r"当前：\1", text)
        text = re.sub(r"현재[:：]\s*(\d+)\s*세", r"当前：\1", text)

    elif lang == "ja":
        replacements = {
            "政策基準に従って脱落理由が確認されない": "政策基準上、明確な不適格理由は確認されませんでした。",
            "無住状態": "無住宅状態",
            "現在：27세": "現在：27",
            "現在: 27세": "現在：27",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"現在[:：]\s*(\d+)\s*세", r"現在：\1", text)

    elif lang == "vi":
        replacements = {
            "Chính sách được xác nhận không có lý do bị loại": "Không phát hiện lý do bị loại rõ ràng theo tiêu chí của chính sách.",
            "Điều kiện chính sách không xác định được lý do bị loại": "Không phát hiện lý do bị loại rõ ràng theo tiêu chí của chính sách.",
            "Chính sách nguyên văn không tìm thấy được điều kiện số lượng chính xác để xác định": "Không tìm thấy điều kiện số liệu cốt lõi có thể xác định từ văn bản chính sách gốc.",
            "기준 theo năm sinh": "tiêu chí theo năm sinh",
            "Hiện tại: 27세": "Hiện tại: 27",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"Hiện tại[:：]\s*(\d+)\s*세", r"Hiện tại: \1", text)

    return text


def _postprocess_text(text: str, lang: str) -> str:
    text = _translate_fixed_text(text, lang)
    text = _translate_threshold_tokens(text, lang)
    text = _normalize_text(text)
    text = _protect_named_entities(text, lang)
    text = _force_phrase_fixes(text, lang)

    # 자잘한 후처리
    if lang == "zh":
        text = text.replace("若 首尔市民", "若首尔市民")
    elif lang == "ja":
        text = text.replace("無家可歸状態", "無住宅状態")
        text = text.replace("無住状態", "無住宅状態")
    elif lang == "vi":
        text = text.replace("2.026", "2026")

    return text


def _split_items(text: str) -> list[str]:
    text = _normalize_text(text)

    parts = re.split(r"(?:\n+|\s*;\s*)", text)
    parts = [p.strip(" -•\t") for p in parts if p.strip()]

    return parts


def _lang_pack(lang: str) -> dict:
    lang = (lang or "ko").lower()

    packs = {
        "ko": {
            "point": "주요 확인 포인트는",
            "next": "다음 단계로는",
            "reason": "핵심 사유",
            "step_label": lambda n: f"{n}단계",
            "check_needed": "조건 확인 필요",
            "check_needed_msg": "정책 원문 기준 세부 자격을 추가 확인해야 합니다.",
            "passed_msg": "현재 조건 기준으로는 핵심 자격을 대체로 충족한 것으로 보입니다.",
            "need_more_msg": "현재 조건 기준으로는 세부 자격 확인이 더 필요합니다.",
            "review_msg": "정책 원문 기준 세부 조건과 신청 자격을 먼저 확인합니다.",
            "default_steps": [
                "자격 재확인 — 정책 원문에서 신청 대상과 기간을 다시 확인합니다.",
                "정보 준비 — 본인 조건과 일치하는 증빙 정보를 정리합니다.",
                "신청 진행 — 공식 신청처에서 접수 절차를 진행합니다.",
            ],
        },
        "en": {
            "point": "Key point:",
            "next": "Next step:",
            "reason": "Key reason",
            "step_label": lambda n: f"Step {n}",
            "check_needed": "Needs review",
            "check_needed_msg": "You need to review the detailed eligibility requirements in the policy text.",
            "passed_msg": "Based on the current inputs, the core eligibility appears to be mostly satisfied.",
            "need_more_msg": "Based on the current inputs, more detailed eligibility review is needed.",
            "review_msg": "Please review the detailed conditions and application eligibility in the original policy text first.",
            "default_steps": [
                "Recheck eligibility — review the target group and application period in the policy text.",
                "Prepare information — organize documents and facts that match your situation.",
                "Proceed to apply — start the application through the official channel.",
            ],
        },
        "zh": {
            "point": "关键确认点：",
            "next": "下一步：",
            "reason": "核心原因",
            "step_label": lambda n: f"第{n}步",
            "check_needed": "需要进一步确认",
            "check_needed_msg": "需要根据政策原文进一步确认详细申请资格。",
            "passed_msg": "根据当前输入，核心资格条件大致符合。",
            "need_more_msg": "根据当前输入，仍需进一步确认详细资格条件。",
            "review_msg": "请先根据政策原文确认详细条件和申请资格。",
            "default_steps": [
                "重新确认资格——查看政策原文中的对象与申请期间。",
                "准备资料——整理与本人情况一致的证明信息。",
                "开始申请——通过官方渠道进行申请。",
            ],
        },
        "ja": {
            "point": "主な確認ポイント：",
            "next": "次の段階：",
            "reason": "主な理由",
            "step_label": lambda n: f"第{n}段階",
            "check_needed": "追加確認が必要です",
            "check_needed_msg": "政策原文に基づいて詳細な申請資格を追加確認する必要があります。",
            "passed_msg": "現在の入力条件では、主要な資格条件をおおむね満たしていると考えられます。",
            "need_more_msg": "現在の入力条件では、詳細な資格条件の追加確認が必要です。",
            "review_msg": "まず政策原文で詳細条件と申請資格を確認してください。",
            "default_steps": [
                "資格再確認 — 政策原文で対象者と申請期間を確認します。",
                "情報準備 — 自分の状況に合う証빙情報を整理します。",
                "申請進行 — 公式申請先で手続きを進めます。",
            ],
        },
        "vi": {
            "point": "Điểm cần lưu ý:",
            "next": "Bước tiếp theo:",
            "reason": "Lý do chính",
            "step_label": lambda n: f"Bước {n}",
            "check_needed": "Cần kiểm tra thêm",
            "check_needed_msg": "Cần kiểm tra thêm điều kiện đủ chi tiết theo văn bản chính sách.",
            "passed_msg": "Dựa trên thông tin hiện tại, có vẻ bạn phần lớn đáp ứng các điều kiện cốt lõi.",
            "need_more_msg": "Dựa trên thông tin hiện tại, vẫn cần kiểm tra thêm các điều kiện chi tiết.",
            "review_msg": "Trước tiên hãy kiểm tra điều kiện chi tiết và tư cách nộp đơn trong văn bản chính sách gốc.",
            "default_steps": [
                "Kiểm tra lại điều kiện — xem lại đối tượng và thời hạn nộp trong văn bản chính sách.",
                "Chuẩn bị thông tin — sắp xếp giấy tờ phù hợp với tình trạng của bạn.",
                "Tiến hành nộp — thực hiện quy trình qua kênh chính thức.",
            ],
        },
    }

    return packs.get(lang, packs["ko"])


def _make_reason_items(reason_text: str, score_pct: int, lang: str = "ko") -> list[dict]:
    pack = _lang_pack(lang)
    reason_text = _postprocess_text(reason_text, lang)

    if not reason_text:
        if score_pct >= 80:
            return []
        return [{
            "icon": "⚠️",
            "html": f"<strong>{pack['check_needed']}:</strong> {pack['check_needed_msg']}"
        }]

    chunks = _split_items(reason_text)
    items = []

    for chunk in chunks[:3]:
        items.append({
            "icon": "⚠️",
            "html": f"<strong>{pack['reason']}:</strong> {chunk}"
        })

    return items


def _make_guide_items(guide_text: str, score_pct: int, lang: str = "ko") -> list[dict]:
    pack = _lang_pack(lang)
    guide_text = _postprocess_text(guide_text, lang)

    if not guide_text:
        if score_pct >= 80:
            return [
                {"icon": "✅", "html": f"<strong>{pack['step_label'](1)}:</strong> {pack['default_steps'][0]}"},
                {"icon": "📎", "html": f"<strong>{pack['step_label'](2)}:</strong> {pack['default_steps'][1]}"},
                {"icon": "🚀", "html": f"<strong>{pack['step_label'](3)}:</strong> {pack['default_steps'][2]}"},
            ]
        return [{
            "icon": "✅",
            "html": f"<strong>{pack['step_label'](1)}:</strong> {pack['review_msg']}"
        }]

    chunks = _split_items(guide_text)
    icons = ["✅", "📎", "🚀"]
    items = []

    for idx, chunk in enumerate(chunks[:3], start=1):
        items.append({
            "icon": icons[(idx - 1) % len(icons)],
            "html": f"<strong>{pack['step_label'](idx)}:</strong> {chunk}"
        })

    return items


def _make_personal_summary(
    summary_text: str,
    reason_text: str,
    guide_text: str,
    score_pct: int,
    lang: str = "ko",
) -> str:
    pack = _lang_pack(lang)

    summary_text = _postprocess_text(summary_text, lang)
    reason_text = _postprocess_text(reason_text, lang)
    guide_text = _postprocess_text(guide_text, lang)

    lines = []

    if summary_text:
        lines.append(summary_text)

    if reason_text:
        lines.append(f"{pack['point']} {reason_text}")
    else:
        if score_pct >= 80:
            lines.append(pack["passed_msg"])
        else:
            lines.append(pack["need_more_msg"])

    if guide_text:
        lines.append(f"{pack['next']} {guide_text}")

    return " ".join(lines[:3]).strip()


def _translate_dashboard_value(field: str, value, lang: str) -> str:
    value = "-" if value is None else str(value)

    region_map = {
        "서울": {"en": "Seoul", "zh": "首尔", "ja": "ソウル", "vi": "Seoul"},
    }
    household_map = {
        "1인 가구": {"en": "Single-person household", "zh": "单人家庭", "ja": "1人世帯", "vi": "Hộ một người"},
        "2인 가구": {"en": "Two-person household", "zh": "双人家庭", "ja": "2人世帯", "vi": "Hộ hai người"},
        "한부모 가구": {"en": "Single-parent household", "zh": "单亲家庭", "ja": "ひとり親世帯", "vi": "Hộ đơn thân"},
    }
    employment_map = {
        "구직자 (실업)": {"en": "Job seeker (unemployed)", "zh": "求职者（失业）", "ja": "求職者（失業）", "vi": "Người tìm việc (thất nghiệp)"},
        "재직자": {"en": "Employed", "zh": "在职", "ja": "在職", "vi": "Đang làm việc"},
        "자영업자": {"en": "Self-employed", "zh": "个体经营者", "ja": "自営業", "vi": "Tự kinh doanh"},
        "학생": {"en": "Student", "zh": "学生", "ja": "学生", "vi": "Sinh viên"},
    }
    education_map = {
        "대졸": {"en": "College graduate", "zh": "大学毕业", "ja": "大卒", "vi": "Tốt nghiệp đại học"},
        "고졸": {"en": "High school graduate", "zh": "高中毕业", "ja": "高卒", "vi": "Tốt nghiệp trung học"},
    }

    mapping_by_field = {
        "region": region_map,
        "household_type": household_map,
        "employment_status": employment_map,
        "education_level": education_map,
    }

    if lang == "ko":
        return value

    field_map = mapping_by_field.get(field, {})
    if value in field_map and lang in field_map[value]:
        return field_map[value][lang]

    return value


def _dashboard_pack(lang: str) -> dict:
    packs = {
        "ko": {
            "today": "오늘",
            "age_label": lambda age: f"만 {age}세",
            "income_label": lambda pct: f"중위소득 {pct}%",
            "summary": lambda total, eligible: f"총 {total}개 정책 분석 완료. 수급 가능(60% 이상) {eligible}건.",
            "tags": {
                "age": lambda age: f"📅 만 {age}세",
                "region": lambda region: f"📍 {region}",
                "income": lambda pct: f"💰 중위소득 {pct}%",
                "household": lambda val: f"🏠 {val}",
                "employment": lambda val: f"👔 {val}",
            },
        },
        "en": {
            "today": "Today",
            "age_label": lambda age: f"Age {age}",
            "income_label": lambda pct: f"Median income {pct}%",
            "summary": lambda total, eligible: f"Analysis complete for {total} policies. {eligible} policies have a likely eligibility of 60% or higher.",
            "tags": {
                "age": lambda age: f"📅 Age {age}",
                "region": lambda region: f"📍 {region}",
                "income": lambda pct: f"💰 Median income {pct}%",
                "household": lambda val: f"🏠 {val}",
                "employment": lambda val: f"👔 {val}",
            },
        },
        "zh": {
            "today": "今天",
            "age_label": lambda age: f"{age}岁",
            "income_label": lambda pct: f"中位收入 {pct}%",
            "summary": lambda total, eligible: f"已完成 {total} 项政策分析。其中，领取可能性在60%以上的政策有 {eligible} 项。",
            "tags": {
                "age": lambda age: f"📅 {age}岁",
                "region": lambda region: f"📍 {region}",
                "income": lambda pct: f"💰 中位收入 {pct}%",
                "household": lambda val: f"🏠 {val}",
                "employment": lambda val: f"👔 {val}",
            },
        },
        "ja": {
            "today": "今日",
            "age_label": lambda age: f"{age}歳",
            "income_label": lambda pct: f"中位所得 {pct}%",
            "summary": lambda total, eligible: f"合計 {total} 件の政策分析が完了しました。受給可能性が60%以上の政策は {eligible} 件です。",
            "tags": {
                "age": lambda age: f"📅 {age}歳",
                "region": lambda region: f"📍 {region}",
                "income": lambda pct: f"💰 中位所得 {pct}%",
                "household": lambda val: f"🏠 {val}",
                "employment": lambda val: f"👔 {val}",
            },
        },
        "vi": {
            "today": "Hôm nay",
            "age_label": lambda age: f"{age} tuổi",
            "income_label": lambda pct: f"Thu nhập trung vị {pct}%",
            "summary": lambda total, eligible: f"Đã hoàn tất phân tích {total} chính sách. Có {eligible} chính sách có khả năng đủ điều kiện từ 60% trở lên.",
            "tags": {
                "age": lambda age: f"📅 {age} tuổi",
                "region": lambda region: f"📍 {region}",
                "income": lambda pct: f"💰 Thu nhập trung vị {pct}%",
                "household": lambda val: f"🏠 {val}",
                "employment": lambda val: f"👔 {val}",
            },
        },
    }
    return packs.get(lang, packs["ko"])


def _build_dashboard_meta(user: dict, lang: str) -> dict:
    pack = _dashboard_pack(lang)

    age = str(_pick(user, "나이", "age", default="-"))
    region = _translate_dashboard_value("region", _pick(user, "거주지역", "region", default="-"), lang)
    income_pct = str(_pick(user, "income_percent", default="-"))
    household_type = _translate_dashboard_value("household_type", _pick(user, "가구유형", "household_type", default="-"), lang)
    employment_status = _translate_dashboard_value("employment_status", _pick(user, "고용상태", "employment_status", default="-"), lang)
    education_level = _translate_dashboard_value("education_level", user.get("education_level", user.get("학력", "-")), lang)

    return {
        "updated_at_label": pack["today"],
        "region_label": region,
        "tags": [
            pack["tags"]["age"](age),
            pack["tags"]["region"](region),
            pack["tags"]["income"](income_pct),
            pack["tags"]["household"](household_type),
            pack["tags"]["employment"](employment_status),
        ],
        "condition_values": {
            "age_label": pack["age_label"](age),
            "region": region,
            "income_label": pack["income_label"](income_pct),
            "household_type": household_type,
            "employment_status": employment_status,
            "education_level": education_level,
        },
    }



def analyze(user: dict, policies: list[dict]) -> dict:
    pipeline = _get_pipeline()
    target_lang = str(user.get("language", "ko")).strip().lower() or "ko"
    dashboard_meta = _build_dashboard_meta(user, target_lang)

    portfolio = []
    total_score = 0

    for idx, policy in enumerate(policies[:10], start=1):
        policy_name = str(policy.get("서비스명") or f"정책-{idx}")
        policy_text = str(
            policy.get("원문")
            or policy.get("지원내용")
            or policy.get("서비스목적요약")
            or policy.get("지원대상")
            or policy_name
        ).strip()

        score_raw = policy.get("score", 0)
        try:
            score_pct = int(round(float(score_raw) * 100)) if float(score_raw) <= 1 else int(round(float(score_raw)))
        except Exception:
            score_pct = 0

        try:
            result = pipeline.process(
                policy_text=policy_text,
                user_condition=_build_user_condition_text(user),
                target_lang=target_lang,
            )
        except Exception as e:
            log.warning("AI 분석 실패: %s / %s", policy_name, e)
            result = {
                "summary": str(policy.get("서비스목적요약") or policy.get("지원내용") or "")[:150],
                "rejection_reason": "",
                "guide": "",
            }

        summary_text = _postprocess_text(result.get("summary", ""), target_lang)
        reason_text = _postprocess_text(result.get("rejection_reason", ""), target_lang)
        guide_text = _postprocess_text(result.get("guide", ""), target_lang)

        reason_items = _make_reason_items(
            reason_text,
            score_pct,
            target_lang,
        )
        guide_items = _make_guide_items(
            guide_text,
            score_pct,
            target_lang,
        )

        item = {
            "policy_id": _make_slug(policy_name, idx),
            "서비스명": policy_name,
            "icon": _pick_icon(policy),
            "subtitle": _make_subtitle(policy),
            "benefit_label": _extract_benefit(policy),
            "source_label": str(policy.get("소관기관명") or "복지 정책"),
            "eligibility_percent": score_pct,
            "수급확률": score_pct,
            "개인요약": _make_personal_summary(
                summary_text,
                reason_text,
                guide_text,
                score_pct,
                target_lang,
            ),
            "탈락사유": reason_items,
            "해결방법": guide_items,
            "우선순위": idx,
            "중복수급주의": False,
            "_css": _score_to_css(score_pct),
            "_matched": policy.get("matched", []),
            "_failed": policy.get("failed", []),
            "_issues": reason_items,
            "_guides": guide_items,
            "_raw": policy,
        }
        portfolio.append(item)
        total_score += score_pct

    avg_score = round(total_score / len(portfolio)) if portfolio else 0
    immediate_count = sum(1 for x in portfolio if x.get("수급확률", 0) >= 80)

    result = {
        "포트폴리오": portfolio,
        "종합요약": (
            f"총 {len(portfolio)}개의 정책을 분석했습니다. "
            f"평균 수급 확률은 {avg_score}%이며, "
            f"즉시 신청 가능 수준의 정책은 {immediate_count}건입니다."
        ),
        "대시보드통계": {
            "해당정책수": len(portfolio),
            "평균확률": avg_score,
            "예상수혜액": "정책별 지원내용 확인",
            "즉시신청가능": immediate_count,
        },
        "cards": portfolio,
        "dashboard_data": {
            "user_profile": {
                "user_name": str(user.get("user_name", user.get("이름", "사용자"))),
                "updated_at_label": dashboard_meta["updated_at_label"],
                "region_label": dashboard_meta["region_label"],
                "total_score": avg_score,
                "score_max": 100,
                "tags": dashboard_meta["tags"],
            },
            "condition_form": {
                "current_values": dashboard_meta["condition_values"]
            },
            "recommendation_cards": portfolio,
            "dashboard_stats": {
                "matched_policy_count": len(portfolio),
                "average_probability_percent": avg_score,
                "expected_total_benefit_label": "-",
                "ready_apply_count": immediate_count,
            },
            "stats": {
                "해당정책수": len(portfolio),
                "평균확률": avg_score,
                "예상수혜액": "정책별 지원내용 확인",
                "즉시신청가능": immediate_count,
            },
            "portfolio_preview": {
                "total_expected_benefit_label": "-",
                "items": [
                    {
                        "icon": x.get("icon", "📋"),
                        "label": x.get("서비스명", ""),
                        "benefit_label": x.get("benefit_label", "지원내용 확인"),
                    }
                    for x in portfolio[:4]
                ],
            },
            "summary": _dashboard_pack(target_lang)["summary"](len(portfolio), sum(1 for x in portfolio if x.get('수급확률', 0) >= 60)),
        },
    }
    return result