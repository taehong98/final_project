import json
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

from .prompt_builder import PromptBuilder
from .text_preprocessor import clean_policy_text


class QwenReasoner:
    REQUIRED_COLUMNS = ["행정 용어", "영어", "베트남어", "중국어", "일본어"]

    def __init__(
        self,
        csv_path: str = "benepick_dict.csv",
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        load_dotenv()

        self.model_name = model_name or os.getenv("QWEN_MODEL", "qwen3.5:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT", "300"))
        self.prompt_path = prompt_path or os.getenv("REJECT_GUIDE_PROMPT_PATH", "prompts/prompt_reject_guide.txt")

        print("Loading glossary...")
        self.glossary_df = self._load_glossary(csv_path)
        self.prompt_builder = self._build_prompt_builder()
        print(f"Connecting Qwen model: {self.model_name}")
        print("Qwen reasoner ready.")

    def _build_prompt_builder(self) -> PromptBuilder:
        prompt_dir = os.path.dirname(self.prompt_path) or "prompts"
        reject_guide_filename = os.path.basename(self.prompt_path) or "prompt_reject_guide.txt"
        return PromptBuilder(prompt_dir=prompt_dir, reject_guide_filename=reject_guide_filename)

    def _load_glossary(self, csv_path: str) -> pd.DataFrame:
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            df = pd.read_csv(csv_path, encoding="cp949")
        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"CSV에 필요한 컬럼이 없습니다: {missing}")
        df = df[self.REQUIRED_COLUMNS].fillna("")
        for col in self.REQUIRED_COLUMNS:
            df[col] = df[col].astype(str).str.strip()
        return df[df["행정 용어"] != ""].reset_index(drop=True)

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
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        outer = self._post_to_ollama(payload)
        content = str(outer.get("message", {}).get("content", "")).strip()
        if not content:
            raise RuntimeError(f"모델 JSON 응답이 비어 있습니다: {json.dumps(outer, ensure_ascii=False)[:500]}")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"모델 content JSON 파싱 실패: {content}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"모델 JSON 응답 형식이 잘못되었습니다: {parsed}")
        return parsed

    @staticmethod
    def _dedupe_keep_order(items: list[str], *, limit: int = 3) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            out.append(value)
            seen.add(value)
            if len(out) >= limit:
                break
        return out

    def _heuristic_guides(self, reasons: list[str]) -> list[str]:
        joined = " ".join(reasons)
        guides: list[str] = []
        if "소득" in joined:
            guides.append("소득 산정 기준과 가구원 수 반영 방식이 공고문과 일치하는지 다시 확인해 주세요.")
        if "연령" in joined or "나이" in joined:
            guides.append("정책의 연령 기준과 신청일 기준 나이를 다시 확인해 주세요.")
        if "지역" in joined or "거주" in joined:
            guides.append("거주 지역 제한과 주민등록 기준일을 다시 확인해 주세요.")
        if "주택" in joined or "무주택" in joined:
            guides.append("무주택 기준과 세대원 주택 보유 여부 반영 방식을 다시 확인해 주세요.")
        if not guides:
            guides.append("정책 원문에서 세부 자격 요건과 제한 대상을 다시 확인해 주세요.")
        guides.append("신청 기간과 제출 서류를 함께 확인한 뒤 다시 판단해 보세요.")
        return self._dedupe_keep_order(guides)

    def _fallback_analysis(self, rule_result_text: str) -> Dict[str, List[str]]:
        lines = [line.strip(" -•	") for line in str(rule_result_text or "").splitlines() if line.strip()]
        reasons = self._dedupe_keep_order(lines) or ["판정 가능한 핵심 조건을 추가로 확인해야 합니다."]
        guides = self._heuristic_guides(reasons)
        return {"rejection_reasons": reasons, "guides": guides}

    def _analyze_in_korean(self, policy_text: str, user_condition: str, rule_result_text: str = "") -> Dict[str, List[str]]:
        schema = self.prompt_builder.get_analysis_schema()
        messages = self.prompt_builder.build_analysis_messages(policy_text, user_condition, rule_result_text)
        try:
            data = self._call_model_json(messages, schema)
            reasons = self._dedupe_keep_order(data.get("rejection_reasons") or [])
            guides = self._dedupe_keep_order(data.get("guides") or [])
            if reasons and guides:
                return {"rejection_reasons": reasons, "guides": guides}
        except Exception:
            pass
        return self._fallback_analysis(rule_result_text)

    def analyze_rejection_and_guide(
        self,
        policy_text: str,
        user_condition: str,
        rule_result_text: str = "",
        target_lang: str = "ko",
    ) -> Dict[str, object]:
        policy_text = clean_policy_text(policy_text)
        user_condition = str(user_condition or "").strip()
        rule_result_text = str(rule_result_text or "").strip()
        target_lang = str(target_lang or "ko").strip().lower()

        if not policy_text:
            raise ValueError("policy_text가 비어 있습니다.")
        if target_lang != "ko":
            raise ValueError("QwenReasoner는 한국어 분석 결과만 반환합니다.")

        analyzed = self._analyze_in_korean(policy_text=policy_text, user_condition=user_condition, rule_result_text=rule_result_text)
        reasons = self._dedupe_keep_order(analyzed.get("rejection_reasons") or [])
        guides = self._dedupe_keep_order(analyzed.get("guides") or [])
        return {
            "language": "ko",
            "rejection_reasons": reasons,
            "guides": guides,
            "rejection_reason": reasons[0] if reasons else "",
            "guide": guides[0] if guides else "",
            "analysis_source": "qwen",
        }


if __name__ == "__main__":
    reasoner = QwenReasoner()
    sample_policy = "청년월세지원은 만 19세~34세 이하이면서 소득 60% 이하인 무주택자만 신청 가능합니다."
    sample_user = "저는 27살이고 소득은 65%입니다. 무주택 세대주입니다."
    sample_rule_result = "소득 기준 60% 이하 조건 미충족 가능성 있음"
    result = reasoner.analyze_rejection_and_guide(
        policy_text=sample_policy,
        user_condition=sample_user,
        rule_result_text=sample_rule_result,
        target_lang="ko",
    )
    print(json.dumps(result, ensure_ascii=False, indent=4))

# ── 카드 사유/가이드 헬퍼 ───────────────────────────────
from typing import Any


def build_reason_items(policy: dict[str, Any], score_pct: int) -> list[dict[str, str]]:
    failed = list(policy.get("failed") or [])
    soft_failed = list(policy.get("soft_failed") or [])

    reasons = failed or soft_failed
    if not reasons:
        reasons = ["정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다."]

    items = []
    for reason in reasons[:3]:
        items.append({
            "icon": "⚠️" if "없습니다" not in reason else "✅",
            "html": f"<strong>핵심 사유:</strong> {reason}",
        })
    return items


def build_guide_items(policy: dict[str, Any], reason_items: list[dict[str, str]]) -> list[dict[str, str]]:
    guides: list[dict[str, str]] = []

    target = str(policy.get("지원대상") or "").strip()
    deadline = str(policy.get("신청기한") or "").strip()
    method = str(policy.get("신청방법") or "").strip()

    first_reason = reason_items[0]["html"] if reason_items else ""
    reason_text = re.sub(r"<[^>]+>", "", first_reason)

    if "지역 조건 미충족" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 거주지역 기준을 다시 확인하고, 해당 지자체 거주자 전용 정책인지 확인하세요."})
    elif "소득 조건 미충족" in reason_text or "소득 한도" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 소득 기준과 가구원 수 기준표를 공고문에서 다시 확인하세요."})
    elif "가구 조건 미충족" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 가구 유형 전용 정책인지 확인하고, 본인 가구 형태와 일치하는지 점검하세요."})
    elif "고용 상태 불일치" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 미취업·구직중·재직중 등 고용 상태 기준을 공고문에서 다시 확인하세요."})
    elif "정책 기준상 뚜렷한 탈락 사유" in reason_text:
        if target:
            guides.append({"icon": "✅", "html": f"<strong>1단계:</strong> 지원대상과 세부 자격을 다시 확인하세요: {target}"})
    else:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 공고문 원문에서 세부 자격 요건을 다시 확인하세요."})

    if deadline:
        guides.append({"icon": "📎", "html": f"<strong>2단계:</strong> 신청기한을 확인하세요: {deadline}"})
    if method:
        guides.append({"icon": "🚀", "html": f"<strong>3단계:</strong> 신청방법을 확인하세요: {method}"})

    return guides[:3]


def build_reason_bundle(policy: dict[str, Any], score_pct: int) -> dict[str, Any]:
    reason_items = build_reason_items(policy, score_pct)
    guide_items = build_guide_items(policy, reason_items)
    return {
        "탈락사유": reason_items,
        "해결방법": guide_items,
        "_issues": reason_items,
        "_guides": guide_items,
    }
