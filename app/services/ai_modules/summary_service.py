import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from dotenv import load_dotenv

from .prompt_builder import PromptBuilder
from .text_preprocessor import clean_policy_text


class PolicySummaryService:
    def __init__(
        self,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        load_dotenv()

        self.model_name = model_name or os.getenv("QWEN_MODEL", "qwen3.5:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT", "300"))
        self.prompt_path = prompt_path or os.getenv("SUMMARY_PROMPT_PATH", "prompts/prompt_summary.txt")

        prompt_dir = os.path.dirname(self.prompt_path) or "prompts"
        summary_filename = os.path.basename(self.prompt_path) or "prompt_summary.txt"
        self.prompt_builder = PromptBuilder(prompt_dir=prompt_dir, summary_filename=summary_filename)

        print(f"Summary model ready: {self.model_name}")

    def _post_to_ollama(self, payload: Dict) -> Dict:
        url = self.base_url + "/api/chat"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Ollama HTTP 오류: {exc.code} / {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"Ollama 호출 실패: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama 응답 파싱 실패: {raw[:500]}") from exc

    def _call_model_json(self, messages: List[Dict[str, str]], schema: Dict) -> Dict:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0},
        }

        outer = self._post_to_ollama(payload)
        content = str(outer.get("message", {}).get("content", "")).strip()
        if not content:
            raise RuntimeError(f"모델 응답이 비어 있습니다: {json.dumps(outer, ensure_ascii=False)[:500]}")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"모델 content JSON 파싱 실패: {content}") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(f"모델 JSON 응답 형식이 잘못되었습니다: {parsed}")
        return parsed

    def _looks_like_korean(self, text: str) -> bool:
        return bool(re.search(r"[가-힣]", str(text)))

    @staticmethod
    def _assemble_summary(policy_name: str, target: str, benefit: str, conditions: str, how_to_apply: str) -> str:
        name = (policy_name or "이 정책").strip()
        pieces: list[str] = []

        if target:
            pieces.append(f"{name}은(는) {target}을 위한 정책입니다.")
        else:
            pieces.append(f"{name}에 대한 안내입니다.")

        if benefit:
            pieces.append(f"지원 내용은 {benefit}입니다.")
        if conditions:
            pieces.append(f"주요 조건은 {conditions}입니다.")
        if how_to_apply:
            pieces.append(f"신청은 {how_to_apply} 방식으로 진행합니다.")

        return " ".join(pieces[:4]).strip()

    def summarize_policy(self, policy_text: str) -> Dict[str, str]:
        policy_text = clean_policy_text(policy_text)
        if not policy_text:
            raise ValueError("policy_text가 비어 있습니다.")

        messages = self.prompt_builder.build_summary_messages(policy_text)
        schema = self.prompt_builder.get_summary_schema()
        data = self._call_model_json(messages, schema)

        policy_name = str(data.get("policy_name", "")).strip()
        target = str(data.get("target", "")).strip()
        benefit = str(data.get("benefit", "")).strip()
        conditions = str(data.get("conditions", "")).strip()
        how_to_apply = str(data.get("how_to_apply", "")).strip()

        summary = self._assemble_summary(policy_name, target, benefit, conditions, how_to_apply)
        if not summary:
            raw_summary = str(data.get("summary", "")).strip()
            summary = raw_summary

        if not summary:
            raise RuntimeError("요약 결과가 비어 있습니다.")
        if not self._looks_like_korean(summary):
            raise RuntimeError(f"요약 결과가 한국어가 아닙니다: {summary}")

        return {
            "language": "ko",
            "summary": summary,
            "summary_source": "qwen",
            "policy_name": policy_name,
            "target": target,
            "benefit": benefit,
            "conditions": conditions,
            "how_to_apply": how_to_apply,
        }


if __name__ == "__main__":
    service = PolicySummaryService()

    sample_policy = """
청년월세지원은 만 19세~34세 이하이면서 소득 60% 이하인 무주택 청년에게 월세 일부를 지원합니다.
신청은 지정된 기간 내 온라인으로 가능하며, 세부 자격 요건은 공고문을 확인해야 합니다.
""".strip()

    result = service.summarize_policy(sample_policy)
    print(json.dumps(result, ensure_ascii=False, indent=4))

# ── 카드 요약/혜택 라벨 헬퍼 ───────────────────────────────
from typing import Any, Tuple

AMOUNT_IGNORES = [
    "소득", "재산", "보증금", "임차보증금", "자동차", "건강보험료", "금융재산",
    "중위소득", "연소득", "총소득", "기준중위소득", "재산기준", "소득기준",
]
SUPPORT_SECTION_HINTS = ["지원내용", "지원방법", "지급기준", "지원금", "바우처", "수당", "장려금", "급여", "월세"]
HOUSEHOLD_HINTS = ["인 가구", "인기준", "인 기준", "가구당", "1인당", "세대당"]


def _parse_money_to_manwon(text: str) -> float | None:
    t = str(text or "").replace(",", "")

    m = re.search(r"(\d+)\s*억\s*(\d+)?\s*천?\s*(\d+)?\s*백?\s*만?\s*원?", t)
    if m:
        eok = int(m.group(1))
        cheon = int(m.group(2)) if m.group(2) else 0
        baek = int(m.group(3)) if m.group(3) else 0
        return float(eok * 10000 + cheon * 1000 + baek * 100)

    m = re.search(r"(\d+)\s*천\s*(\d+)\s*백\s*만\s*원", t)
    if m:
        return float(int(m.group(1)) * 1000 + int(m.group(2)) * 100)

    m = re.search(r"(\d+)\s*천\s*만\s*원", t)
    if m:
        return float(int(m.group(1)) * 1000)

    m = re.search(r"(\d+)\s*백\s*만\s*원", t)
    if m:
        return float(int(m.group(1)) * 100)

    m = re.search(r"(\d+)\s*만\s*원", t)
    if m:
        return float(int(m.group(1)))

    m = re.search(r"([\d,]+)\s*원", t)
    if m:
        won = int(m.group(1).replace(",", ""))
        return won / 10000 if won >= 10000 else None

    return None


def _format_manwon(value: float | int | None) -> str:
    if value is None:
        return "지원내용 확인"
    value_f = float(value)
    if abs(value_f - round(value_f)) < 1e-9:
        return f"{int(round(value_f)):,}만원"
    return f"{value_f:.1f}만원".replace(".0만원", "만원")


def _pick_benefit_source_text(policy: dict[str, Any]) -> str:
    return "\n".join([
        str(policy.get("지원내용") or ""),
        str(policy.get("서비스목적요약") or ""),
        str(policy.get("evidence_text") or ""),
    ]).strip()


def _is_benefit_context(line: str, support_section: bool = False) -> bool:
    line = str(line or "")
    if not line:
        return False
    if any(word in line for word in AMOUNT_IGNORES) and not any(h in line for h in ["지원", "지급", "수당", "바우처", "장려금", "월세"]):
        return False
    if support_section:
        return True
    return any(word in line for word in SUPPORT_SECTION_HINTS)


def _extract_monthly_duration_benefit(text: str) -> tuple[str, float | None]:
    compact = re.sub(r"\s+", " ", text)
    patterns = [
        r"월\s*([\d,]+)\s*만\s*원?\s*[×x]\s*최대\s*(\d+)\s*개월",
        r"최대\s*(\d+)\s*개월[^\d]{0,30}?월\s*([\d,]+)\s*만\s*원",
        r"최대\s*(\d+)\s*개월\s*간[^\d]{0,30}?월\s*([\d,]+)\s*만\s*원",
    ]
    for idx, pattern in enumerate(patterns):
        m = re.search(pattern, compact)
        if not m:
            continue
        if idx == 0:
            monthly = int(m.group(1).replace(",", ""))
            months = int(m.group(2))
        else:
            months = int(m.group(1))
            monthly = int(m.group(2).replace(",", ""))
        total = monthly * months
        return (f"최대 {total:,}만원", float(total))

    m = re.search(r"연\s*([\d,]+)\s*만\s*원", compact)
    if m:
        value = float(int(m.group(1).replace(",", "")))
        return (f"연 {_format_manwon(value)}", value)

    m = re.search(r"월\s*([\d,]+)\s*만\s*원", compact)
    if m:
        monthly = float(int(m.group(1).replace(",", "")))
        duration = re.search(r"최대\s*(\d+)\s*개월", compact)
        if duration:
            total = monthly * int(duration.group(1))
            return (f"최대 {_format_manwon(total)}", total)
        return (f"월 {_format_manwon(monthly)}", None)

    return ("", None)


def _extract_household_benefit(text: str, household_size: int) -> tuple[str, float | None]:
    lines = [ln.strip() for ln in re.split(r"[\n\r]", text) if ln.strip()]
    size = max(1, int(household_size or 1))
    household_patterns = [
        rf"{size}\s*인\s*(?:가구|기준)?\s*[:：]?\s*([\d,]+)\s*원",
        rf"{size}\s*인(?:기준)?\s*([\d,]+)\s*원",
    ]

    for line in lines:
        if "증가시마다" in line:
            continue
        for pattern in household_patterns:
            m = re.search(pattern, line)
            if not m:
                continue
            won = int(m.group(1).replace(",", ""))
            value = won / 10000
            label_prefix = f"{size}인 기준"
            if "가구" in line:
                label_prefix = f"{size}인 가구"
            return (f"{label_prefix} {_format_manwon(value)}", value)

    return ("", None)


def _extract_contextual_amounts(text: str) -> tuple[str, float | None]:
    lines = [ln.strip() for ln in re.split(r"[\n\r]", text) if ln.strip()]
    support_section = False
    best_value: float | None = None
    best_label: str | None = None

    for line in lines:
        if any(hint in line for hint in SUPPORT_SECTION_HINTS):
            support_section = True

        if not _is_benefit_context(line, support_section=support_section):
            continue
        if any(ignore in line for ignore in AMOUNT_IGNORES) and not any(key in line for key in ["지원", "지급", "장려금", "바우처", "월세"]):
            continue
        if "증가시마다" in line:
            continue

        max_match = re.search(r"최대\s*([\d,]+\s*억\s*[\d\s천백]*만?\s*원|[\d,]+\s*만\s*원|[\d,]+\s*원)", line)
        if max_match:
            value = _parse_money_to_manwon(max_match.group(1))
            if value is not None and (best_value is None or value > best_value):
                best_value = value
                best_label = f"최대 {_format_manwon(value)}"
            continue

        for prefix in ["가구당", "1인당", "1가정 당", "1가정당"]:
            m = re.search(rf"{prefix}\s*([\d,]+\s*만\s*원|[\d,]+\s*원)", line)
            if m:
                value = _parse_money_to_manwon(m.group(1))
                if value is not None and (best_value is None or value > best_value):
                    best_value = value
                    best_label = f"{prefix} {_format_manwon(value)}"

        if any(h in line for h in HOUSEHOLD_HINTS) or any(k in line for k in ["지원", "지급", "바우처", "장려금", "월세"]):
            raw_amounts = re.findall(r"([\d,]+\s*억\s*[\d\s천백]*만?\s*원|[\d,]+\s*만\s*원|[\d,]+\s*원)", line)
            for raw in raw_amounts:
                value = _parse_money_to_manwon(raw)
                if value is not None and (best_value is None or value > best_value):
                    best_value = value
                    best_label = f"최대 {_format_manwon(value)}"

    return (best_label or "", best_value)


def extract_benefit_info(policy: dict[str, Any], user: dict[str, Any] | None = None) -> tuple[str, float | None]:
    text = _pick_benefit_source_text(policy)
    if not text:
        return (policy.get("지원유형") or "지원내용 확인", None)

    label, value = _extract_monthly_duration_benefit(text)
    if label:
        return (label, value)

    household_size = 1
    if user:
        household_size = int(user.get("가구원수", user.get("household_size", 1)) or 1)
    label, value = _extract_household_benefit(text, household_size)
    if label:
        return (label, value)

    label, value = _extract_contextual_amounts(text)
    if label:
        return (label, value)

    return (policy.get("지원유형") or "지원내용 확인", None)


def format_total_benefit(total_manwon: float | int | None) -> str:
    if not total_manwon or total_manwon <= 0:
        return "정책별 지원내용 확인"
    total_int = int(round(float(total_manwon)))
    if total_int >= 10000:
        eok = total_int // 10000
        rest = total_int % 10000
        if rest == 0:
            return f"{eok}억원"
        return f"{eok}억 {rest:,}만원"
    return f"{total_int:,}만원"


def make_subtitle(policy: dict[str, Any]) -> str:
    target = str(policy.get("지원대상") or "").strip()
    criteria = str(policy.get("선정기준") or "").strip()
    org = str(policy.get("소관기관명") or "").strip()
    parts = []
    if target:
        parts.append(target[:20])
    if criteria:
        parts.append(criteria[:20])
    elif org:
        parts.append(org[:20])
    return " · ".join(parts[:2]) if parts else "세부 조건 확인 필요"


def _clean_field(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def build_summary_text(policy: dict[str, Any], score_pct: int) -> str:
    name = str(policy.get("서비스명") or policy.get("policy_name") or "정책")
    target = _clean_field(policy.get("지원대상") or "")
    content = _clean_field(policy.get("지원내용") or "")
    deadline = _clean_field(policy.get("신청기한") or "")

    sentences: list[str] = []
    if target:
        sentences.append(f"{name}은(는) {target} 대상 정책입니다.")
    else:
        sentences.append(f"{name} 정책입니다.")

    if content:
        sentences.append(f"지원 내용은 {content}입니다.")

    if deadline and deadline != "상시신청":
        sentences.append(f"신청기한은 {deadline}입니다.")

    if score_pct < 60:
        sentences.append("현재 입력 조건으로는 바로 신청 가능성이 낮아 세부 자격을 다시 확인하는 것이 좋습니다.")
    elif score_pct < 80:
        sentences.append("기본 조건은 대체로 맞지만 일부 확인이 더 필요합니다.")
    else:
        sentences.append("현재 입력 조건 기준으로 우선 검토해볼 만한 정책입니다.")

    return " ".join(sentences[:4]).strip()


def build_card_summary(policy: dict[str, Any], user: dict[str, Any] | None, score_pct: int) -> dict[str, Any]:
    benefit_label, benefit_value = extract_benefit_info(policy, user=user)
    institution = str(policy.get("소관기관명") or "복지 정책")
    return {
        "subtitle": make_subtitle(policy),
        "benefit_label": benefit_label,
        "source_label": institution[:8],
        "개인요약": build_summary_text(policy, score_pct),
        "_benefit_value_manwon": benefit_value,
    }
