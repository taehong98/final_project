import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

from prompt_builder import PromptBuilder


class QwenReasoner:
    REQUIRED_COLUMNS = ["행정 용어", "영어", "베트남어", "중국어", "일본어"]

    LANG_MAP = {
        "ko": "한국어",
        "en": "영어",
        "vi": "베트남어",
        "zh": "중국어",
        "ja": "일본어",
    }

    GLOSSARY_COL_MAP = {
        "en": "영어",
        "vi": "베트남어",
        "zh": "중국어",
        "ja": "일본어",
    }

    def __init__(
        self,
        csv_path: str = "benepick_dict.csv",
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        prompt_path: Optional[str] = None,
    ) -> None:
        load_dotenv()

        self.model_name = model_name or os.getenv("QWEN_MODEL", "qwen3:4b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = float(timeout or os.getenv("OLLAMA_TIMEOUT", "300"))
        self.prompt_path = prompt_path or os.getenv("REJECT_GUIDE_PROMPT_PATH", "prompts/prompt_reject_guide.txt")

        print("1. 📚 [베네픽] 행정 용어 사전 로딩 중...")
        self.glossary_df = self._load_glossary(csv_path)
        self.prompt_builder = self._build_prompt_builder()

        print(f"2. 🤖 [AI 연결] Qwen 모델({self.model_name}) 연결 중...")
        print("3. ✅ Qwen 분석/번역기 준비 완료!")

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

    def _extract_relevant_glossary(self, text: str, target_lang: str) -> str:
        if target_lang == "ko":
            return ""

        text = str(text or "")
        relevant_terms: List[str] = []
        target_col = self.GLOSSARY_COL_MAP[target_lang]

        for _, row in self.glossary_df.iterrows():
            term = row["행정 용어"]
            translated = row[target_col]
            if term and translated and term in text:
                relevant_terms.append(f"- {term} -> {translated}")

        return "\n".join(relevant_terms)

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

    def _call_model_text(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }

        outer = self._post_to_ollama(payload)
        content = str(outer.get("message", {}).get("content", "")).strip()
        if not content:
            raise RuntimeError(f"모델 텍스트 응답이 비어 있습니다: {json.dumps(outer, ensure_ascii=False)[:500]}")
        return content

    def _contains_hangul(self, text: str) -> bool:
        return bool(re.search(r"[가-힣]", text))

    def _looks_like_target_language(self, text: str, target_lang: str) -> bool:
        text = str(text).strip()
        if not text:
            return False

        if target_lang == "ko":
            return self._contains_hangul(text)
        if target_lang == "en":
            return bool(re.search(r"[A-Za-z]", text)) and not self._contains_hangul(text)
        if target_lang == "zh":
            return bool(re.search(r"[\u4e00-\u9fff]", text)) and not self._contains_hangul(text)
        if target_lang == "ja":
            return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text)) and not self._contains_hangul(text)
        if target_lang == "vi":
            return bool(re.search(r"[A-Za-zÀ-ỹ]", text)) and not self._contains_hangul(text)
        return True

    def _parse_tag_response(self, text: str) -> Dict[str, str]:
        text = str(text).strip()
        reason_match = re.search(
            r"REJECTION_REASON\s*:\s*(.+?)(?=\nGUIDE\s*:|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        guide_match = re.search(r"GUIDE\s*:\s*(.+)", text, re.DOTALL | re.IGNORECASE)

        if not reason_match or not guide_match:
            raise RuntimeError(f"태그 형식 파싱 실패: {text}")

        return {
            "rejection_reason": reason_match.group(1).strip(),
            "guide": guide_match.group(1).strip(),
        }

    def _build_analysis_text_messages(
        self,
        policy_text: str,
        user_condition: str,
        rule_result_text: str = "",
    ) -> List[Dict[str, str]]:
        context_block = self.prompt_builder.build_analysis_context(policy_text, user_condition, rule_result_text)
        prompt = f"""
{self.prompt_builder.analysis_prompt_base}

[출력 형식]
REJECTION_REASON: ...
GUIDE: ...

{context_block}
""".strip()

        return [
            {
                "role": "system",
                "content": "Answer in Korean only. Do not use JSON. Follow the two-line format exactly.",
            },
            {"role": "user", "content": prompt},
        ]

    def _build_reason_translation_messages(
        self,
        rejection_reason_ko: str,
        guide_ko: str,
        policy_text: str,
        target_lang: str,
    ) -> List[Dict[str, str]]:
        lang_name = self.LANG_MAP[target_lang]
        glossary_str = self._extract_relevant_glossary(policy_text, target_lang)

        prompt = f"""
너는 대한민국 복지 정책 번역 도우미다.

아래 한국어 결과를 {lang_name}로만 번역하라.

[핵심 규칙]
1. 의미를 추가하거나 삭제하지 않는다.
2. 한국어를 섞지 않는다.
3. 아래 용어 사전이 있으면 우선 사용한다.
4. 반드시 JSON만 출력한다.
5. 출력 키는 반드시 rejection_reason, guide만 사용한다.

[용어 사전]
{glossary_str if glossary_str else "해당 문서에 매핑되는 용어 없음"}

[한국어 rejection_reason]
{rejection_reason_ko}

[한국어 guide]
{guide_ko}
""".strip()

        return [
            {
                "role": "system",
                "content": f"Return only valid JSON matching the schema. The values must be only in {lang_name}.",
            },
            {"role": "user", "content": prompt},
        ]

    @staticmethod
    def _get_reason_translation_schema() -> Dict:
        return {
            "type": "object",
            "properties": {
                "rejection_reason": {"type": "string"},
                "guide": {"type": "string"},
            },
            "required": ["rejection_reason", "guide"],
            "additionalProperties": False,
        }

    def _analyze_in_korean(
        self,
        policy_text: str,
        user_condition: str,
        rule_result_text: str = "",
    ) -> Dict[str, str]:
        schema = self.prompt_builder.get_analysis_schema()
        last_error: Optional[Exception] = None

        messages = self.prompt_builder.build_analysis_messages(policy_text, user_condition, rule_result_text)
        for _ in range(2):
            try:
                data = self._call_model_json(messages, schema)
                rejection_reason = str(data.get("rejection_reason", "")).strip()
                guide = str(data.get("guide", "")).strip()
                combined = rejection_reason + " " + guide
                if rejection_reason and guide and self._looks_like_target_language(combined, "ko"):
                    return {
                        "rejection_reason": rejection_reason,
                        "guide": guide,
                    }
                last_error = RuntimeError(f"한국어 분석 결과가 비정상입니다: {data}")
            except Exception as exc:
                last_error = exc

        text_messages = self._build_analysis_text_messages(policy_text, user_condition, rule_result_text)
        for _ in range(2):
            try:
                raw = self._call_model_text(text_messages)
                data = self._parse_tag_response(raw)
                rejection_reason = data["rejection_reason"].strip()
                guide = data["guide"].strip()
                combined = rejection_reason + " " + guide
                if rejection_reason and guide and self._looks_like_target_language(combined, "ko"):
                    return {
                        "rejection_reason": rejection_reason,
                        "guide": guide,
                    }
                last_error = RuntimeError(f"태그 분석 결과가 비정상입니다: {data}")
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"한국어 분석 단계 실패: {last_error}")

    def _translate_from_korean(
        self,
        rejection_reason_ko: str,
        guide_ko: str,
        policy_text: str,
        target_lang: str,
    ) -> Dict[str, str]:
        if target_lang == "ko":
            return {
                "rejection_reason": rejection_reason_ko,
                "guide": guide_ko,
            }

        schema = self._get_reason_translation_schema()
        last_error: Optional[Exception] = None
        messages = self._build_reason_translation_messages(
            rejection_reason_ko=rejection_reason_ko,
            guide_ko=guide_ko,
            policy_text=policy_text,
            target_lang=target_lang,
        )

        for _ in range(2):
            try:
                data = self._call_model_json(messages, schema)
                rejection_reason = str(data.get("rejection_reason", "")).strip()
                guide = str(data.get("guide", "")).strip()
                combined = rejection_reason + " " + guide

                if not rejection_reason or not guide:
                    raise RuntimeError(f"번역 결과가 비어 있습니다: {data}")
                if not self._looks_like_target_language(combined, target_lang):
                    raise RuntimeError(f"목표 언어({target_lang})가 아닙니다: {data}")

                return {
                    "rejection_reason": rejection_reason,
                    "guide": guide,
                }
            except Exception as exc:
                last_error = exc

        raise RuntimeError(f"{self.LANG_MAP[target_lang]} 번역 단계 실패: {last_error}")

    def analyze_rejection_and_guide(
        self,
        policy_text: str,
        user_condition: str,
        rule_result_text: str = "",
        target_lang: str = "ko",
    ) -> Dict[str, str]:
        policy_text = str(policy_text or "").strip()
        user_condition = str(user_condition or "").strip()
        rule_result_text = str(rule_result_text or "").strip()
        target_lang = str(target_lang or "ko").strip().lower()

        if not policy_text:
            raise ValueError("policy_text가 비어 있습니다.")
        if target_lang not in self.LANG_MAP:
            raise ValueError(f"지원하지 않는 언어입니다: {target_lang}")

        analyzed = self._analyze_in_korean(
            policy_text=policy_text,
            user_condition=user_condition,
            rule_result_text=rule_result_text,
        )

        translated = self._translate_from_korean(
            rejection_reason_ko=analyzed["rejection_reason"],
            guide_ko=analyzed["guide"],
            policy_text=policy_text,
            target_lang=target_lang,
        )

        return {
            "language": target_lang,
            "rejection_reason": translated["rejection_reason"],
            "guide": translated["guide"],
            "analysis_source": "qwen",
        }


if __name__ == "__main__":
    reasoner = QwenReasoner()

    sample_policy = (
        "청년월세지원은 만 19세~34세 이하이면서 소득 60% 이하인 무주택자만 신청 가능합니다."
    )
    sample_user = "저는 27살이고 소득은 65%입니다. 무주택 세대주입니다."
    sample_rule_result = "소득 기준 60% 이하 조건 미충족 가능성 있음"

    result = reasoner.analyze_rejection_and_guide(
        policy_text=sample_policy,
        user_condition=sample_user,
        rule_result_text=sample_rule_result,
        target_lang="ko",
    )
    print(json.dumps(result, ensure_ascii=False, indent=4))
