from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


class PromptBuilder:
    LANG_MAP = {
        "ko": "한국어",
        "en": "English",
        "vi": "Tiếng Việt",
        "zh": "中文",
        "ja": "日本語",
    }

    DEFAULT_ANALYSIS_PROMPT = """너는 대한민국 복지 정책 탈락 사유 설명 도우미다.

[목표]
- 사용자 조건과 정책 원문, 규칙 엔진 결과를 함께 보고 탈락 가능 사유와 확인/보완 가이드를 정리한다.

[핵심 규칙]
1. 규칙 엔진 결과를 가장 우선 근거로 삼는다.
2. 정책 원문에 없는 기관, 금액, 기간, 서류, 다른 제도는 추측하지 않는다.
3. rejection_reasons에는 핵심 이유를 1~3개까지 짧게 쓴다.
4. guides에는 지금 확인하거나 보완할 행동을 1~3개까지 짧게 쓴다.
5. 반드시 한국어 JSON만 출력한다.
6. 출력 키는 반드시 rejection_reasons, guides만 사용한다.
"""

    DEFAULT_SUMMARY_PROMPT = """너는 대한민국 복지 정책 요약 도우미다.

[목표]
- 복지 정책 원문을 구조화해서 일반 사용자에게 핵심만 전달한다.

[핵심 규칙]
1. 정책 원문에 있는 정보만 사용한다.
2. 정책 원문에 없는 금액, 기간, 기관, 자격, 서류를 추측하지 않는다.
3. 문장을 길게 복사하지 말고 항목별 핵심만 짧게 정리한다.
4. 반드시 한국어 JSON만 출력한다.
5. 출력 키는 반드시 policy_name, target, benefit, conditions, how_to_apply만 사용한다.
"""

    DEFAULT_TRANSLATION_PROMPT = """너는 대한민국 복지 정책 번역 도우미다.

[목표]
- 한국어 복지 정책 문장을 지정된 언어로 자연스럽고 정확하게 번역한다.

[핵심 규칙]
1. 원문의 의미를 추가하거나 삭제하지 않는다.
2. 한국어를 섞지 않는다.
3. 용어 사전이 있으면 우선 반영한다.
4. 문체는 안내문/행정문에 맞게 간결하게 유지한다.
5. 반드시 JSON만 출력한다.
6. 출력 키는 반드시 translated_text만 사용한다.
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

    def _get_translation_examples(self, target_lang: str) -> str:
        examples = {
            "en": (
                "- 무주택 청년 -> young adults without home ownership\n"
                "- 기준 중위소득 60% 이하 -> households with income at or below 60% of the median income standard\n"
                "- 신청 방법 -> application method"
            ),
            "zh": (
                "- 무주택 청년 -> 无住房青年\n"
                "- 기준 중위소득 60% 이하 -> 收入不高于基准中位收入60%的家庭\n"
                "- 신청 방법 -> 申请方式"
            ),
            "ja": (
                "- 무주택 청년 -> 住宅を所有していない青年\n"
                "- 기준 중위소득 60% 이하 -> 基準中位所得の60%以下の世帯\n"
                "- 신청 방법 -> 申請方法"
            ),
            "vi": (
                "- 무주택 청년 -> thanh niên chưa sở hữu nhà ở\n"
                "- 기준 중위소득 60% 이하 -> hộ gia đình có thu nhập không vượt quá 60% mức thu nhập trung vị chuẩn\n"
                "- 신청 방법 -> cách thức nộp hồ sơ"
            ),
        }
        return examples.get(target_lang, "")

    def build_analysis_context(self, policy_text: str, user_condition: str, rule_result_text: str = "") -> str:
        return f"""
[사용자 조건]
{str(user_condition or '').strip()}

[정책 원문]
{str(policy_text or '').strip()}

[규칙 엔진 참고 결과]
{str(rule_result_text or '').strip() or '없음'}
""".strip()

    def build_analysis_messages(self, policy_text: str, user_condition: str, rule_result_text: str = "") -> list[Dict[str, str]]:
        context = self.build_analysis_context(policy_text, user_condition, rule_result_text)
        user_prompt = f"{self.analysis_prompt_base}\n\n{context}"
        return [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON matching the schema. "
                    "Use Korean only. Keys must be rejection_reasons and guides."
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
                    "Use Korean only. Keys must be policy_name, target, benefit, conditions, how_to_apply."
                ),
            },
            {"role": "user", "content": self.build_summary_user_prompt(policy_text)},
        ]

    def build_translation_user_prompt(self, text: str, target_lang: str, glossary_text: Optional[str] = None) -> str:
        lang_name = self.get_lang_name(target_lang)
        glossary_text = str(glossary_text or "").strip() or "해당 문서에 매핑되는 용어 없음"
        examples = self._get_translation_examples(target_lang)
        return f"""
{self.translation_prompt_base}

[목표 언어]
{lang_name}

[용어 사전]
{glossary_text}

[번역 예시]
{examples or '없음'}

[원문]
{str(text or '').strip()}
""".strip()

    def build_translation_messages(self, text: str, target_lang: str, glossary_text: Optional[str] = None) -> list[Dict[str, str]]:
        lang_name = self.get_lang_name(target_lang)
        user_prompt = self.build_translation_user_prompt(text=text, target_lang=target_lang, glossary_text=glossary_text)
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
                "rejection_reasons": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                },
                "guides": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 3,
                },
            },
            "required": ["rejection_reasons", "guides"],
            "additionalProperties": False,
        }

    @staticmethod
    def get_summary_schema() -> Dict:
        return {
            "type": "object",
            "properties": {
                "policy_name": {"type": "string"},
                "target": {"type": "string"},
                "benefit": {"type": "string"},
                "conditions": {"type": "string"},
                "how_to_apply": {"type": "string"},
            },
            "required": ["policy_name", "target", "benefit", "conditions", "how_to_apply"],
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
