from __future__ import annotations

import re
from typing import Dict, Optional


class OutputGuard:
    VI_MARKERS = (
        " ho tro ",
        " dieu kien ",
        " dang ky ",
        " nguoi ",
        " thoi han ",
        " khong ",
        " duoc ",
        " thanh ",
    )
    EN_MARKERS = (
        " the ",
        " and ",
        " for ",
        " with ",
        " support ",
        " apply ",
        " eligible ",
    )
    JA_MARKERS = ("\u3067\u3059", "\u307E\u3059", "\u306E", "\u3092", "\u306B", "\u7533\u8ACB")

    @staticmethod
    def _count(pattern: str, text: str) -> int:
        return len(re.findall(pattern, str(text or "")))

    @staticmethod
    def _normalize_marker_text(text: str) -> str:
        lowered = str(text or "").lower()
        lowered = re.sub(r"[^a-z\u00C0-\u024F]+", " ", lowered)
        return f" {lowered.strip()} "

    def _looks_like_english(self, text: str) -> bool:
        markers = self._normalize_marker_text(text)
        latin = self._count(r"[A-Za-z]", text)
        accented = self._count(r"[\u00C0-\u024F]", text)
        return latin >= 3 and accented == 0 and any(marker in markers for marker in self.EN_MARKERS)

    def _looks_like_vietnamese(self, text: str) -> bool:
        markers = self._normalize_marker_text(text)
        latin = self._count(r"[A-Za-z]", text)
        accented = self._count(r"[\u00C0-\u024F]", text)
        return latin >= 3 and (accented >= 1 or any(marker in markers for marker in self.VI_MARKERS))

    def looks_like_target_language(self, text: str, target_lang: str) -> bool:
        text = str(text or "").strip()
        if not text:
            return False

        hangul = self._count(r"[\uAC00-\uD7A3]", text)
        han = self._count(r"[\u4E00-\u9FFF]", text)
        kana = self._count(r"[\u3040-\u30FF]", text)
        latin = self._count(r"[A-Za-z]", text)

        if target_lang == "ko":
            return hangul >= 2
        if target_lang == "en":
            return hangul <= 6 and han == 0 and kana == 0 and self._looks_like_english(text)
        if target_lang == "zh":
            return han >= 6 and hangul <= 6 and kana == 0
        if target_lang == "ja":
            return hangul <= 40 and (kana >= 2 or any(marker in text for marker in self.JA_MARKERS)) and (kana + han) >= 8
        if target_lang == "vi":
            return hangul <= 6 and han == 0 and kana == 0 and self._looks_like_vietnamese(text)
        return latin > 0 or hangul > 0 or han > 0 or kana > 0

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
                "is_fallback": False,
            }

        if translated_text and self.looks_like_target_language(translated_text, target_lang):
            return {
                "language": target_lang,
                "translated_text": translated_text,
                "translation_source": str(data.get("translation_source", "") or source_if_valid),
                "is_fallback": False,
            }

        return {
            "language": target_lang,
            "translated_text": str(original_text or "").strip(),
            "translation_source": source_if_fallback,
            "is_fallback": True,
        }

    def guard_analysis(
        self,
        data: Optional[Dict],
        *,
        target_lang: str = "ko",
        fallback_reason: str = "\uC608\uC815 \uAC00\uB2A5\uD55C \uBCF4\uC644 \uC870\uAC74\uC744 \uCD94\uAC00\uB85C \uD655\uC778\uD574\uC57C \uD569\uB2C8\uB2E4.",
        fallback_guide: str = "\uC815\uCC45 \uC6D0\uBB38\uC5D0\uC11C \uC138\uBD80 \uC790\uACA9 \uC694\uAC74\uACFC \uC2E0\uCCAD \uC870\uAC74\uC744 \uB2E4\uC2DC \uD655\uC778\uD574 \uC8FC\uC138\uC694.",
        source_if_valid: str = "qwen",
        source_if_fallback: str = "guard_fallback",
    ) -> Dict[str, object]:
        data = data or {}
        target_lang = str(target_lang or "ko").strip().lower() or "ko"

        reasons = [str(x).strip() for x in (data.get("rejection_reasons") or []) if str(x).strip()]
        guides = [str(x).strip() for x in (data.get("guides") or []) if str(x).strip()]

        if not reasons and data.get("rejection_reason"):
            reasons = [str(data.get("rejection_reason")).strip()]
        if not guides and data.get("guide"):
            guides = [str(data.get("guide")).strip()]

        combined = " ".join(reasons + guides).strip()
        if reasons and guides and self.looks_like_target_language(combined, target_lang):
            return {
                "language": target_lang,
                "rejection_reasons": reasons[:3],
                "guides": guides[:3],
                "rejection_reason": reasons[0],
                "guide": guides[0],
                "analysis_source": str(data.get("analysis_source", "") or source_if_valid),
            }

        return {
            "language": target_lang,
            "rejection_reasons": [fallback_reason],
            "guides": [fallback_guide],
            "rejection_reason": fallback_reason,
            "guide": fallback_guide,
            "analysis_source": source_if_fallback,
        }

    def guard_pipeline_result(self, data: Optional[Dict], *, target_lang: str, fallback_summary_text: str) -> Dict[str, object]:
        data = data or {}
        guarded_analysis = self.guard_analysis(
            data,
            target_lang=target_lang,
            fallback_reason=str(data.get("rejection_reason", "") or "\uC608\uC815 \uAC00\uB2A5\uD55C \uBCF4\uC644 \uC870\uAC74\uC744 \uCD94\uAC00\uB85C \uD655\uC778\uD574\uC57C \uD569\uB2C8\uB2E4."),
            fallback_guide=str(data.get("guide", "") or "\uC815\uCC45 \uC6D0\uBB38\uC5D0\uC11C \uC138\uBD80 \uC790\uACA9 \uC694\uAC74\uACFC \uC2E0\uCCAD \uC870\uAC74\uC744 \uB2E4\uC2DC \uD655\uC778\uD574 \uC8FC\uC138\uC694."),
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
            "rejection_reasons": guarded_analysis["rejection_reasons"],
            "guides": guarded_analysis["guides"],
            "rejection_reason": guarded_analysis["rejection_reason"],
            "guide": guarded_analysis["guide"],
        }
