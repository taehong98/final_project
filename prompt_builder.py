from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


class PromptBuilder:
    """Qwen 요약/번역/분석 프롬프트를 한곳에서 관리하는 유틸."""

    LANG_MAP = {
        "ko": "한국어",
        "en": "영어",
        "vi": "베트남어",
        "zh": "중국어",
        "ja": "일본어",
    }

    DEFAULT_ANALYSIS_PROMPT = """너는 대한민국 복지 정책 탈락 사유 설명 도우미다.

[스타일]
- 설명은 간결하고 기술적으로 작성한다.
- 핵심 조건 위주로 짧게 쓴다.
- 감정적 표현은 사용하지 않는다.

[핵심 규칙]
1. 정책 원문에 있는 정보만 근거로 작성한다.
2. 정책 원문에 없는 서류, 기관, 금액, 기간, 대체 상품, 다른 정책을 추측하지 않는다.
3. rejection_reason에는 탈락 핵심 이유 또는 추가 확인이 필요한 핵심 이유만 짧게 쓴다.
4. guide에는 현재 정책 기준 안에서 보완 가능한 행동 또는 확인 방향만 1~2문장으로 쓴다.
5. 다른 카드, 적금, 금융상품, 다른 복지제도를 추천하지 않는다.
6. 반드시 한국어 JSON만 출력한다.
7. 출력 키는 반드시 rejection_reason, guide만 사용한다.
"""

    DEFAULT_SUMMARY_PROMPT = """너는 대한민국 복지 정책 요약 도우미다.

[목표]
- 복지 정책 원문을 일반 사용자도 이해하기 쉽게 3~5문장으로 요약한다.

[스타일]
- 쉬운 한국어로 쓴다.
- 핵심 정보만 남긴다.
- 불필요하게 길게 쓰지 않는다.
- 추측하지 않는다.

[핵심 규칙]
1. 정책 원문에 있는 정보만 사용한다.
2. 정책 원문에 없는 기관, 금액, 기간, 자격, 서류를 추가하지 않는다.
3. 반드시 한국어 JSON만 출력한다.
4. 출력 키는 반드시 summary만 사용한다.
5. summary는 3~5문장으로 작성한다.
"""

    DEFAULT_TRANSLATION_PROMPT = """너는 대한민국 복지 정책 번역 도우미다.

[목표]
- 한국어 복지 정책 설명 문장을 지정된 언어로 자연스럽고 정확하게 번역한다.

[핵심 규칙]
1. 원문의 의미를 추가하거나 삭제하지 않는다.
2. 한국어를 섞지 않는다.
3. 용어 사전이 있으면 우선 반영한다.
4. 반드시 JSON만 출력한다.
5. 출력 키는 반드시 translated_text만 사용한다.
"""

    def __init__(
        self,
        prompt_dir: str = "prompts",
        reject_guide_filename: str = "prompt_reject_guide.txt",
        summary_filename: str = "prompt_summary.txt",
        translation_filename: str = "prompt_translation.txt",
    ) -> None:
        self.prompt_dir = Path(prompt_dir)
        self.analysis_prompt_base = self._load_prompt(
            self.prompt_dir / reject_guide_filename,
            self.DEFAULT_ANALYSIS_PROMPT,
        )
        self.summary_prompt_base = self._load_prompt(
            self.prompt_dir / summary_filename,
            self.DEFAULT_SUMMARY_PROMPT,
        )
        self.translation_prompt_base = self._load_prompt(
            self.prompt_dir / translation_filename,
            self.DEFAULT_TRANSLATION_PROMPT,
        )

    def _load_prompt(self, path: Path, default: str) -> str:
        try:
            text = path.read_text(encoding="utf-8").strip()
            return text or default
        except Exception:
            return default

    def get_lang_name(self, lang_code: str) -> str:
        lang_code = str(lang_code or "ko").strip().lower()
        if lang_code not in self.LANG_MAP:
            raise ValueError(f"지원하지 않는 언어입니다: {lang_code}")
        return self.LANG_MAP[lang_code]

    def build_analysis_context(
        self,
        policy_text: str,
        user_condition: str,
        rule_result_text: str = "",
    ) -> str:
        return f"""
[사용자 조건]
{str(user_condition or '').strip()}

[정책 원문]
{str(policy_text or '').strip()}

[규칙 엔진 참고 결과]
{str(rule_result_text or '').strip() or '없음'}
""".strip()

    def build_analysis_user_prompt(
        self,
        policy_text: str,
        user_condition: str,
        rule_result_text: str = "",
    ) -> str:
        context = self.build_analysis_context(
            policy_text=policy_text,
            user_condition=user_condition,
            rule_result_text=rule_result_text,
        )
        return f"{self.analysis_prompt_base}\n\n{context}".strip()

    def build_analysis_messages(
        self,
        policy_text: str,
        user_condition: str,
        rule_result_text: str = "",
    ) -> list[Dict[str, str]]:
        user_prompt = self.build_analysis_user_prompt(
            policy_text=policy_text,
            user_condition=user_condition,
            rule_result_text=rule_result_text,
        )
        return [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON matching the schema. "
                    "Use Korean only. Keys must be rejection_reason and guide."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]

    def build_summary_user_prompt(self, policy_text: str) -> str:
        return f"""
{self.summary_prompt_base}

[정책 원문]
{str(policy_text or '').strip()}
""".strip()

    def build_summary_messages(self, policy_text: str) -> list[Dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON matching the schema. "
                    "Use Korean only. Key must be summary."
                ),
            },
            {"role": "user", "content": self.build_summary_user_prompt(policy_text)},
        ]

    def build_translation_user_prompt(
        self,
        text: str,
        target_lang: str,
        glossary_text: Optional[str] = None,
    ) -> str:
        lang_name = self.get_lang_name(target_lang)
        glossary_text = str(glossary_text or "").strip() or "해당 문서에 매핑되는 용어 없음"
        return f"""
{self.translation_prompt_base}

[목표 언어]
{lang_name}

[용어 사전]
{glossary_text}

[원문]
{str(text or '').strip()}
""".strip()

    def build_translation_messages(
        self,
        text: str,
        target_lang: str,
        glossary_text: Optional[str] = None,
    ) -> list[Dict[str, str]]:
        lang_name = self.get_lang_name(target_lang)
        user_prompt = self.build_translation_user_prompt(
            text=text,
            target_lang=target_lang,
            glossary_text=glossary_text,
        )
        return [
            {
                "role": "system",
                "content": f"Return only valid JSON matching the schema. Use only {lang_name}.",
            },
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def get_analysis_schema() -> Dict:
        return {
            "type": "object",
            "properties": {
                "rejection_reason": {"type": "string"},
                "guide": {"type": "string"},
            },
            "required": ["rejection_reason", "guide"],
            "additionalProperties": False,
        }

    @staticmethod
    def get_summary_schema() -> Dict:
        return {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
            "required": ["summary"],
            "additionalProperties": False,
        }

    @staticmethod
    def get_translation_schema() -> Dict:
        return {
            "type": "object",
            "properties": {
                "translated_text": {"type": "string"},
            },
            "required": ["translated_text"],
            "additionalProperties": False,
        }


if __name__ == "__main__":
    builder = PromptBuilder(prompt_dir="prompts")

    sample_policy = "청년월세지원은 만 19세~34세 이하이면서 소득 60% 이하인 무주택 청년에게 월세 일부를 지원합니다."
    sample_user = "저는 27살이고 소득은 65%입니다. 무주택 세대주입니다."

    print("[analysis]")
    print(builder.build_analysis_user_prompt(sample_policy, sample_user))
    print("\n[summary]")
    print(builder.build_summary_user_prompt(sample_policy))
    print("\n[translation]")
    print(builder.build_translation_user_prompt(sample_policy, "en", "- 청년월세지원 -> Youth Monthly Rent Support"))
