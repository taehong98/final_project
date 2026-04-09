from __future__ import annotations

from pathlib import Path

from app.services.ai_modules.output_guard import OutputGuard
from app.services.ai_modules.qwen_reasoner import QwenReasoner
from app.services.ai_modules.summary_service import PolicySummaryService
from app.services.ai_modules.text_preprocessor import clean_policy_text
from app.services.ai_modules.translation_service import PolicyTranslationService


SUPPORTED_LANGS = {"ko", "en", "zh", "ja", "vi"}


class PolicyAIEnricher:
    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parent / "ai_modules"
        prompt_dir = base_dir / "prompts"
        csv_path = str(base_dir / "benepick_dict.csv")

        self.guard = OutputGuard()
        self.enabled = True
        self.init_error: str | None = None

        try:
            self.summary_service = PolicySummaryService(
                model_name="qwen3.5:4b",
                prompt_path=str(prompt_dir / "prompt_summary.txt"),
            )
            self.translation_service = PolicyTranslationService(
                csv_path=csv_path,
                model_name="qwen3.5:4b",
                prompt_path=str(prompt_dir / "prompt_translation.txt"),
            )
            self.reasoner = QwenReasoner(
                csv_path=csv_path,
                model_name="qwen3.5:4b",
                prompt_path=str(prompt_dir / "prompt_reject_guide.txt"),
            )
        except Exception as exc:
            self.enabled = False
            self.init_error = str(exc)

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

    def _translate_list(self, items: list[str], policy_text: str, target_lang: str) -> list[str]:
        if target_lang == "ko" or not items or not self.enabled:
            return items

        translated: list[str] = []
        for item in items:
            try:
                result = self.translation_service.translate_text(
                    text=item,
                    policy_text=policy_text,
                    target_lang=target_lang,
                )
                guarded = self.guard.guard_translation(
                    result,
                    original_text=item,
                    target_lang=target_lang,
                )
                translated.append(guarded["translated_text"])
            except Exception:
                translated.append(item)
        return self._dedupe_keep_order(translated)

    def enrich_detail(
        self,
        *,
        policy_text: str,
        user_condition_text: str = "",
        target_lang: str = "ko",
        fallback_reasons: list[str] | None = None,
        fallback_actions: list[str] | None = None,
    ) -> dict:
        fallback_reasons = self._dedupe_keep_order(fallback_reasons or [], limit=3)
        fallback_actions = self._dedupe_keep_order(fallback_actions or [], limit=3)
        target_lang = (target_lang or "ko").lower().strip()
        if target_lang not in SUPPORTED_LANGS:
            target_lang = "ko"

        policy_text = clean_policy_text(policy_text)
        user_condition_text = str(user_condition_text or "").strip()

        summary_data: dict = {}
        if self.enabled:
            try:
                summary_data = self.summary_service.summarize_policy(policy_text)
            except Exception:
                summary_data = {}

        summary_guarded = self.guard.guard_summary(
            summary_data,
            fallback_text=policy_text,
            expected_lang="ko",
        )
        summary_text = summary_guarded["summary"]

        reasons = fallback_reasons[:]
        actions = fallback_actions[:]
        if self.enabled and user_condition_text:
            try:
                analyzed = self.reasoner.analyze_rejection_and_guide(
                    policy_text=policy_text,
                    user_condition=user_condition_text,
                    rule_result_text="\n".join(fallback_reasons),
                    target_lang="ko",
                )
                reasons = self._dedupe_keep_order(analyzed.get("rejection_reasons") or reasons, limit=3)
                actions = self._dedupe_keep_order(analyzed.get("guides") or actions, limit=3)
            except Exception:
                pass

        if not reasons:
            reasons = ["판정 가능한 핵심 조건을 추가로 확인해야 합니다."]
        if not actions:
            actions = ["정책 원문에서 세부 자격 요건과 신청 조건을 다시 확인해 주세요."]

        if target_lang != "ko" and self.enabled:
            try:
                translated = self.translation_service.translate_text(
                    text=summary_text,
                    policy_text=policy_text,
                    target_lang=target_lang,
                )
                summary_text = self.guard.guard_translation(
                    translated,
                    original_text=summary_text,
                    target_lang=target_lang,
                )["translated_text"]
            except Exception:
                pass

            reasons = self._translate_list(reasons, policy_text, target_lang)
            actions = self._translate_list(actions, policy_text, target_lang)

        return {
            "eligibility_summary": summary_text,
            "blocking_reasons": self._dedupe_keep_order(reasons, limit=3),
            "recommended_actions": self._dedupe_keep_order(actions, limit=3),
        }


ai_enricher = PolicyAIEnricher()
