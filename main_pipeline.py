import json
from typing import Dict, Optional

from output_guard import OutputGuard
from qwen_reasoner import QwenReasoner
from rule_engine import PolicyRuleEngine
from summary_service import PolicySummaryService
from translation_service import PolicyTranslationService


class BenePickPipeline:
    def __init__(self, csv_path: str = "benepick_dict.csv") -> None:
        print("=== 베네픽 통합 파이프라인 초기화 시작 ===")
        self.rule_engine = PolicyRuleEngine()
        self.reasoner = QwenReasoner(csv_path=csv_path)
        self.summary_service = PolicySummaryService()
        self.translation_service = PolicyTranslationService(csv_path=csv_path)
        self.output_guard = OutputGuard()
        print("=== 초기화 완료! ===")

    def _rule_result_to_analysis(self, rule_result, source: str) -> Dict[str, str]:
        return {
            "rejection_reason": str(getattr(rule_result, "rejection_reason_ko", "") or "").strip(),
            "guide": str(getattr(rule_result, "guide_ko", "") or "").strip(),
            "analysis_source": source,
        }

    def _make_rule_result_text(self, rule_result) -> str:
        parts = [
            f"- eligible: {getattr(rule_result, 'eligible', None)}",
            f"- status: {getattr(rule_result, 'status', 'unknown')}",
            f"- rejection_reason_ko: {str(getattr(rule_result, 'rejection_reason_ko', '')).strip()}",
            f"- guide_ko: {str(getattr(rule_result, 'guide_ko', '')).strip()}",
        ]

        matched_rules = getattr(rule_result, "matched_rules", []) or []
        if matched_rules:
            parts.append("- matched_rules:")
            for rule in matched_rules:
                parts.append(
                    f"  * field={getattr(rule, 'field_name', '')}, "
                    f"source='{getattr(rule, 'source_text', '')}', "
                    f"user_value={getattr(rule, 'user_value', '')}, "
                    f"passed={getattr(rule, 'passed', '')}, "
                    f"message='{getattr(rule, 'message_ko', '')}'"
                )

        return "\n".join(parts)

    def _analyze_with_fallback(
        self,
        policy_text: str,
        user_condition: str,
        rule_result,
        target_lang: str,
    ) -> Dict[str, str]:
        if getattr(rule_result, "eligible", None) is False:
            result = self._rule_result_to_analysis(rule_result, "rule_engine")
            result["language"] = "ko"
            return result

        try:
            rule_result_text = self._make_rule_result_text(rule_result)
            analyzed = self.reasoner.analyze_rejection_and_guide(
                policy_text=policy_text,
                user_condition=user_condition,
                rule_result_text=rule_result_text,
                target_lang=target_lang,
            )
            return analyzed
        except Exception as exc:
            print(f"⚠️ Qwen 분석 실패. 룰 엔진 결과로 폴백합니다: {exc}")
            fallback = self._rule_result_to_analysis(rule_result, "rule_engine_fallback")
            fallback["language"] = "ko"

            if not fallback["rejection_reason"]:
                fallback["rejection_reason"] = "판정 가능한 핵심 조건을 추가로 확인해야 합니다."
            if not fallback["guide"]:
                fallback["guide"] = "정책 원문에서 세부 자격 요건과 신청 조건을 다시 확인해 주세요."

            return fallback

    def _summarize_with_fallback(self, policy_text: str) -> Dict[str, str]:
        try:
            return self.summary_service.summarize_policy(policy_text)
        except Exception as exc:
            print(f"⚠️ 요약 생성 실패. 기본 요약으로 폴백합니다: {exc}")
            fallback_summary = policy_text[:180] + "..." if len(policy_text) > 180 else policy_text
            return {
                "language": "ko",
                "summary": fallback_summary,
                "summary_source": "fallback",
            }

    def _translate_summary_with_fallback(
        self,
        summary_text: str,
        policy_text: str,
        target_lang: str,
    ) -> Dict[str, str]:
        try:
            return self.translation_service.translate_text(
                text=summary_text,
                policy_text=policy_text,
                target_lang=target_lang,
            )
        except Exception as exc:
            print(f"⚠️ 요약 번역 실패. 원문 요약으로 폴백합니다: {exc}")
            return {
                "language": "ko",
                "translated_text": summary_text,
                "translation_source": "fallback",
            }

    def _translate_analysis_fields_with_fallback(
        self,
        analyzed: Dict[str, str],
        policy_text: str,
        target_lang: str,
    ) -> Dict[str, str]:
        target_lang = str(target_lang or "ko").strip().lower() or "ko"
        result = dict(analyzed or {})

        if target_lang == "ko":
            result["language"] = "ko"
            return result

        rejection_reason = str(result.get("rejection_reason", "") or "").strip()
        guide = str(result.get("guide", "") or "").strip()

        if not rejection_reason and not guide:
            result["language"] = target_lang
            return result

        combined = f"{rejection_reason} {guide}".strip()
        if combined and self.output_guard.looks_like_target_language(combined, target_lang):
            result["language"] = target_lang
            return result

        translated_any = False

        if rejection_reason:
            try:
                rr = self.translation_service.translate_text(
                    text=rejection_reason,
                    policy_text=policy_text,
                    target_lang=target_lang,
                )
                translated_rr = str(rr.get("translated_text", "") or "").strip()
                if translated_rr and self.output_guard.looks_like_target_language(translated_rr, target_lang):
                    result["rejection_reason"] = translated_rr
                    translated_any = True
            except Exception as exc:
                print(f"⚠️ rejection_reason 번역 실패. 기존 값을 유지합니다: {exc}")

        if guide:
            try:
                gd = self.translation_service.translate_text(
                    text=guide,
                    policy_text=policy_text,
                    target_lang=target_lang,
                )
                translated_gd = str(gd.get("translated_text", "") or "").strip()
                if translated_gd and self.output_guard.looks_like_target_language(translated_gd, target_lang):
                    result["guide"] = translated_gd
                    translated_any = True
            except Exception as exc:
                print(f"⚠️ guide 번역 실패. 기존 값을 유지합니다: {exc}")

        result["language"] = target_lang if translated_any else str(analyzed.get("language", "ko") or "ko")
        return result

    def process(
        self,
        policy_text: str,
        user_condition: str,
        target_lang: str = "ko",
    ) -> Dict[str, Optional[str]]:
        policy_text = str(policy_text or "").strip()
        user_condition = str(user_condition or "").strip()
        target_lang = str(target_lang or "ko").strip().lower() or "ko"

        if not policy_text:
            raise ValueError("policy_text가 비어 있습니다.")
        if target_lang not in self.reasoner.LANG_MAP:
            raise ValueError(f"지원하지 않는 언어입니다: {target_lang}")

        rule_result = self.rule_engine.evaluate(policy_text, user_condition)

        analyzed = self._analyze_with_fallback(
            policy_text=policy_text,
            user_condition=user_condition,
            rule_result=rule_result,
            target_lang=target_lang,
        )
        analyzed = self._translate_analysis_fields_with_fallback(
            analyzed=analyzed,
            policy_text=policy_text,
            target_lang=target_lang,
        )
        analyzed = self.output_guard.guard_analysis(
            analyzed,
            target_lang=target_lang,
            fallback_reason=str(analyzed.get("rejection_reason", "") or "판정 가능한 핵심 조건을 추가로 확인해야 합니다."),
            fallback_guide=str(analyzed.get("guide", "") or "정책 원문에서 세부 자격 요건과 신청 조건을 다시 확인해 주세요."),
            source_if_valid=str(analyzed.get("analysis_source", "") or "qwen"),
            source_if_fallback=str(analyzed.get("analysis_source", "") or "guard_fallback"),
        )

        summary_result = self._summarize_with_fallback(policy_text)
        summary_result = self.output_guard.guard_summary(
            summary_result,
            fallback_text=policy_text,
            expected_lang="ko",
        )

        translated_summary_result = self._translate_summary_with_fallback(
            summary_text=summary_result["summary"],
            policy_text=policy_text,
            target_lang=target_lang,
        )
        translated_summary_result = self.output_guard.guard_translation(
            translated_summary_result,
            original_text=summary_result["summary"],
            target_lang=target_lang,
        )

        return {
            "language": target_lang,
            "rule_eligible": getattr(rule_result, "eligible", None),
            "rule_status": getattr(rule_result, "status", "unknown"),
            "analysis_source": analyzed["analysis_source"],
            "summary_source": summary_result["summary_source"],
            "translation_source": translated_summary_result["translation_source"],
            "summary": translated_summary_result["translated_text"],
            "rejection_reason": analyzed["rejection_reason"],
            "guide": analyzed["guide"],
        }


if __name__ == "__main__":
    pipeline = BenePickPipeline(csv_path="benepick_dict.csv")

    sample_user = "저는 27살이고 소득은 65%입니다. 무주택 세대주입니다."

    supported_langs = {"ko", "en", "vi", "zh", "ja"}
    selected_lang = input("테스트 언어를 입력하세요 (ko/en/vi/zh/ja) [기본값: ko]: ").strip().lower()
    if not selected_lang:
        selected_lang = "ko"
    if selected_lang not in supported_langs:
        print(f"⚠️ 지원하지 않는 입력입니다: {selected_lang}. 기본값 ko를 사용합니다.")
        selected_lang = "ko"

    print("정책 원문을 붙여넣으세요. 붙여넣은 뒤 엔터를 누르세요.")
    sample_policy = input("> ").strip()

    if not sample_policy:
        print("⚠️ 원문이 비어 있어서 기본 샘플 정책으로 테스트합니다.")
        sample_policy = "청년월세지원은 만 19세~34세 이하이면서 소득 60% 이하인 무주택자만 신청 가능합니다."

    result = pipeline.process(
        policy_text=sample_policy,
        user_condition=sample_user,
        target_lang=selected_lang,
    )

    print("\n[최종 파이프라인 결과]")
    print(json.dumps(result, ensure_ascii=False, indent=4))
