from __future__ import annotations

import re
from typing import Dict, Optional


class OutputGuard:
    """Qwen 결과의 구조/언어/빈 값 검사를 담당하는 후처리 가드.

    목적
    - LLM 응답이 비어 있거나 형식이 이상할 때 기본값으로 보정
    - 한국어 요약 / 다국어 번역 / 분석 결과를 일관된 형태로 반환
    - main_pipeline 폴백 전에 한 번 더 안전하게 정리
    """

    LANG_MAP = {
        "ko": "한국어",
        "en": "영어",
        "vi": "베트남어",
        "zh": "중국어",
        "ja": "일본어",
    }

    def _contains_hangul(self, text: str) -> bool:
        return bool(re.search(r"[가-힣]", str(text or "")))

    def looks_like_target_language(self, text: str, target_lang: str) -> bool:
        text = str(text or "").strip()
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

    def guard_summary(
        self,
        data: Optional[Dict],
        *,
        fallback_text: str,
        expected_lang: str = "ko",
        source_if_valid: str = "qwen",
        source_if_fallback: str = "guard_fallback",
        max_fallback_len: int = 180,
    ) -> Dict[str, str]:
        data = data or {}
        summary = str(data.get("summary", "") or "").strip()

        if summary and self.looks_like_target_language(summary, expected_lang):
            return {
                "language": expected_lang,
                "summary": summary,
                "summary_source": str(data.get("summary_source", "") or source_if_valid),
            }

        fallback_text = str(fallback_text or "").strip()
        fallback_summary = fallback_text[:max_fallback_len] + "..." if len(fallback_text) > max_fallback_len else fallback_text
        return {
            "language": expected_lang,
            "summary": fallback_summary,
            "summary_source": source_if_fallback,
        }

    def guard_translation(
        self,
        data: Optional[Dict],
        *,
        original_text: str,
        target_lang: str,
        source_if_valid: str = "qwen",
        source_if_fallback: str = "guard_fallback",
    ) -> Dict[str, str]:
        data = data or {}
        target_lang = str(target_lang or "ko").strip().lower() or "ko"
        translated_text = str(data.get("translated_text", "") or "").strip()

        if target_lang == "ko":
            return {
                "language": "ko",
                "translated_text": translated_text or str(original_text or "").strip(),
                "translation_source": str(data.get("translation_source", "") or "original"),
            }

        if translated_text and self.looks_like_target_language(translated_text, target_lang):
            return {
                "language": target_lang,
                "translated_text": translated_text,
                "translation_source": str(data.get("translation_source", "") or source_if_valid),
            }

        return {
            "language": "ko",
            "translated_text": str(original_text or "").strip(),
            "translation_source": source_if_fallback,
        }

    def guard_analysis(
        self,
        data: Optional[Dict],
        *,
        target_lang: str = "ko",
        fallback_reason: str = "판정 가능한 핵심 조건을 추가로 확인해야 합니다.",
        fallback_guide: str = "정책 원문에서 세부 자격 요건과 신청 조건을 다시 확인해 주세요.",
        source_if_valid: str = "qwen",
        source_if_fallback: str = "guard_fallback",
    ) -> Dict[str, str]:
        data = data or {}
        target_lang = str(target_lang or "ko").strip().lower() or "ko"

        rejection_reason = str(data.get("rejection_reason", "") or "").strip()
        guide = str(data.get("guide", "") or "").strip()
        combined = f"{rejection_reason} {guide}".strip()

        if rejection_reason and guide and self.looks_like_target_language(combined, target_lang):
            return {
                "language": target_lang,
                "rejection_reason": rejection_reason,
                "guide": guide,
                "analysis_source": str(data.get("analysis_source", "") or source_if_valid),
            }

        return {
            "language": target_lang,
            "rejection_reason": fallback_reason,
            "guide": fallback_guide,
            "analysis_source": source_if_fallback,
        }

    def guard_pipeline_result(
        self,
        data: Optional[Dict],
        *,
        target_lang: str,
        fallback_summary_text: str,
    ) -> Dict[str, object]:
        data = data or {}
        guarded_analysis = self.guard_analysis(
            data,
            target_lang=target_lang,
            fallback_reason=str(data.get("rejection_reason", "") or "판정 가능한 핵심 조건을 추가로 확인해야 합니다."),
            fallback_guide=str(data.get("guide", "") or "정책 원문에서 세부 자격 요건과 신청 조건을 다시 확인해 주세요."),
            source_if_valid=str(data.get("analysis_source", "") or "qwen"),
        )
        guarded_translation = self.guard_translation(
            {"translated_text": data.get("summary", ""), "translation_source": data.get("translation_source", "")},
            original_text=fallback_summary_text,
            target_lang=target_lang,
        )

        return {
            "language": guarded_analysis["language"],
            "rule_eligible": data.get("rule_eligible"),
            "rule_status": data.get("rule_status", "unknown"),
            "analysis_source": guarded_analysis["analysis_source"],
            "summary_source": data.get("summary_source", "unknown"),
            "translation_source": guarded_translation["translation_source"],
            "summary": guarded_translation["translated_text"],
            "rejection_reason": guarded_analysis["rejection_reason"],
            "guide": guarded_analysis["guide"],
        }


if __name__ == "__main__":
    guard = OutputGuard()
    print(
        guard.guard_analysis(
            {"rejection_reason": "소득 기준 초과 가능성이 있습니다.", "guide": "소득 산정 기준을 다시 확인하세요.", "analysis_source": "qwen"},
            target_lang="ko",
        )
    )
