from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass
class ReasonPayload:
    rejection_reason_ko: str
    guide_ko: str
    status_notice_ko: str
    action_steps_ko: List[str]
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rejection_reason_ko": self.rejection_reason_ko,
            "guide_ko": self.guide_ko,
            "status_notice_ko": self.status_notice_ko,
            "action_steps_ko": self.action_steps_ko,
            "tags": self.tags,
        }


class ReasonTemplateBuilder:
    """
    규칙 기반 판정 결과를 사용자 안내 문구로 바꿔주는 템플릿 전용 클래스.

    사용 목적
    - rule_engine 결과를 더 읽기 쉬운 문구로 변환
    - 점수 구간별 안내 문구를 통일
    - 향후 qwen_reasoner 폴백 문구를 한 곳에서 관리
    """

    FIELD_LABELS = {
        "age": "나이",
        "income_ratio": "소득 기준",
        "region": "지역",
        "employment_status": "취업 상태",
        "housing_type": "주거 형태",
        "household_type": "가구 유형",
        "nationality": "국적",
        "documents": "제출 서류",
        "application_period": "신청 기간",
    }

    FAILED_GUIDES = {
        "age": "연령 기준을 다시 확인하고, 공고문에 출생연도 기준이나 예외 연령 조건이 있는지 확인하세요.",
        "income_ratio": "소득 기준을 다시 확인하고, 재산 공제나 예외 산정 방식이 있는지 공고문을 확인하세요.",
        "region": "거주 지역 제한이 있는 정책인지 확인하고, 주소지 기준 신청 가능 여부를 확인하세요.",
        "employment_status": "재직·미취업·구직등록 등 고용 상태 요건을 다시 확인하세요.",
        "housing_type": "무주택 여부나 월세·전세 등 주거 형태 기준을 다시 확인하세요.",
        "household_type": "1인 가구·다자녀 가구 등 가구 유형 기준을 다시 확인하세요.",
        "nationality": "국적 또는 체류자격 요건이 있는지 공고문과 관할 기관 안내를 확인하세요.",
        "documents": "필수 서류를 다시 확인하고, 누락 서류가 있으면 보완한 뒤 신청하세요.",
        "application_period": "신청 기간이 현재 열려 있는지 확인하고, 마감된 경우 다음 모집 일정을 확인하세요.",
    }

    SCORE_STATUS_MESSAGES = {
        "ready": "즉시 신청 가능 수준입니다.",
        "almost_ready": "핵심 조건은 대체로 맞지만 일부 보완 후 신청하는 것이 좋습니다.",
        "check_needed": "조건을 조금 더 확인한 뒤 신청 여부를 판단하는 것이 좋습니다.",
        "unlikely": "현재 조건으로는 신청이 어려울 수 있어 핵심 요건부터 다시 확인해야 합니다.",
        "unknown": "입력 정보가 부족해 정확한 판정을 위해 추가 확인이 필요합니다.",
    }

    def build(
        self,
        rule_result: Any,
        score: Optional[float] = None,
        extra_notes: Optional[Sequence[str]] = None,
    ) -> ReasonPayload:
        status = str(self._get(rule_result, "status", "unknown") or "unknown")
        matched_rules = list(self._get(rule_result, "matched_rules", []) or [])
        missing_fields = list(self._get(rule_result, "missing_fields", []) or [])
        failed_checks = [check for check in matched_rules if self._get(check, "passed") is False]

        if status == "eligible":
            rejection_reason = "현재 입력한 핵심 조건 기준으로는 즉시 탈락 사유가 확인되지 않았습니다."
            guide = "세부 자격 요건, 신청 기간, 제출 서류는 공고문 원문을 추가로 확인하세요."
            tags = ["핵심 조건 충족"]
        elif status == "ineligible":
            rejection_reason = self._build_failed_reason(failed_checks)
            guide = self._build_failed_guide(failed_checks)
            tags = ["핵심 조건 미충족"]
        else:
            rejection_reason = self._build_unknown_reason(missing_fields)
            guide = self._build_unknown_guide(missing_fields)
            tags = ["추가 정보 필요"]

        status_notice = self._build_status_notice(status=status, score=score)
        action_steps = self._build_action_steps(status, failed_checks, missing_fields, extra_notes=extra_notes)

        if score is not None:
            tags.append(f"점수 {int(round(score))}%")
        tags.extend(self._tag_fields(failed_checks, missing_fields))

        return ReasonPayload(
            rejection_reason_ko=rejection_reason,
            guide_ko=guide,
            status_notice_ko=status_notice,
            action_steps_ko=action_steps,
            tags=self._dedupe(tags),
        )

    def build_for_pipeline(
        self,
        rule_result: Any,
        score: Optional[float] = None,
        extra_notes: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        payload = self.build(rule_result=rule_result, score=score, extra_notes=extra_notes)
        data = payload.to_dict()
        return {
            "rejection_reason": data["rejection_reason_ko"],
            "guide": self._join_guide(data["guide_ko"], data["status_notice_ko"], data["action_steps_ko"]),
            "analysis_source": "reason_template",
            "tags": data["tags"],
        }

    def _build_failed_reason(self, failed_checks: Sequence[Any]) -> str:
        if not failed_checks:
            return "핵심 조건 일부가 맞지 않아 신청이 어려울 수 있습니다."

        messages: List[str] = []
        for check in failed_checks:
            custom_message = str(self._get(check, "message_ko", "") or "").strip()
            if custom_message:
                messages.append(custom_message)
                continue

            field_name = str(self._get(check, "field_name", "") or "")
            label = self.FIELD_LABELS.get(field_name, field_name or "조건")
            messages.append(f"{label} 조건이 정책 기준과 맞지 않습니다.")

        return " ".join(self._dedupe(messages))

    def _build_failed_guide(self, failed_checks: Sequence[Any]) -> str:
        if not failed_checks:
            return "정책 원문에서 핵심 요건을 다시 확인한 뒤 신청 여부를 판단하세요."

        guides: List[str] = []
        for check in failed_checks:
            field_name = str(self._get(check, "field_name", "") or "")
            guides.append(self.FAILED_GUIDES.get(field_name, f"{self.FIELD_LABELS.get(field_name, field_name or '조건')}을 다시 확인하세요."))

        return " ".join(self._dedupe(guides))

    def _build_unknown_reason(self, missing_fields: Sequence[str]) -> str:
        if not missing_fields:
            return "현재 입력 정보만으로는 판정 가능한 핵심 조건이 부족합니다."
        labels = ", ".join(self.FIELD_LABELS.get(field, field) for field in self._dedupe(missing_fields))
        return f"{labels} 정보를 확인할 수 없어 정확한 판정이 어렵습니다."

    def _build_unknown_guide(self, missing_fields: Sequence[str]) -> str:
        if not missing_fields:
            return "나이, 소득, 지역 같은 핵심 정보를 더 입력한 뒤 다시 확인하세요."
        labels = ", ".join(self.FIELD_LABELS.get(field, field) for field in self._dedupe(missing_fields))
        return f"{labels} 정보를 추가 입력한 뒤 다시 확인하세요. 세부 기준은 공고문 원문과 관할 기관 안내를 함께 확인하세요."

    def _build_status_notice(self, status: str, score: Optional[float]) -> str:
        if status == "unknown":
            return self.SCORE_STATUS_MESSAGES["unknown"]

        if score is None:
            return {
                "eligible": self.SCORE_STATUS_MESSAGES["ready"],
                "ineligible": self.SCORE_STATUS_MESSAGES["unlikely"],
            }.get(status, self.SCORE_STATUS_MESSAGES["unknown"])

        if score >= 90:
            return self.SCORE_STATUS_MESSAGES["ready"]
        if score >= 70:
            return self.SCORE_STATUS_MESSAGES["almost_ready"]
        if score >= 50:
            return self.SCORE_STATUS_MESSAGES["check_needed"]
        return self.SCORE_STATUS_MESSAGES["unlikely"]

    def _build_action_steps(
        self,
        status: str,
        failed_checks: Sequence[Any],
        missing_fields: Sequence[str],
        extra_notes: Optional[Sequence[str]] = None,
    ) -> List[str]:
        steps: List[str] = []

        if status == "eligible":
            steps.extend(
                [
                    "정책 공고문에서 신청 기간과 접수 기관을 먼저 확인하세요.",
                    "필수 서류가 있는지 확인한 뒤 온라인 또는 방문 신청 경로를 선택하세요.",
                ]
            )
        elif status == "ineligible":
            for check in failed_checks:
                field_name = str(self._get(check, "field_name", "") or "")
                if field_name == "income_ratio":
                    steps.append("소득 산정 기준과 공제 항목을 다시 확인하세요.")
                elif field_name == "age":
                    steps.append("연령 기준이 출생연도 기준인지 함께 확인하세요.")
                elif field_name == "application_period":
                    steps.append("현재 모집 중인지 확인하고, 마감 시 다음 공고 일정을 확인하세요.")
                else:
                    label = self.FIELD_LABELS.get(field_name, field_name or "조건")
                    steps.append(f"{label} 관련 세부 요건을 다시 확인하세요.")
        else:
            for field in self._dedupe(missing_fields):
                label = self.FIELD_LABELS.get(field, field)
                steps.append(f"{label} 정보를 먼저 입력하거나 확인하세요.")

        for note in extra_notes or []:
            note = str(note or "").strip()
            if note:
                steps.append(note)

        if not steps:
            steps.append("정책 원문을 다시 확인하고, 애매한 경우 관할 기관에 문의하세요.")

        return self._dedupe(steps)[:5]

    def _tag_fields(self, failed_checks: Sequence[Any], missing_fields: Sequence[str]) -> List[str]:
        tags: List[str] = []
        for check in failed_checks:
            field_name = str(self._get(check, "field_name", "") or "")
            if field_name:
                tags.append(self.FIELD_LABELS.get(field_name, field_name))
        for field in missing_fields:
            if field:
                tags.append(f"{self.FIELD_LABELS.get(field, field)} 확인 필요")
        return self._dedupe(tags)

    def _join_guide(self, guide: str, status_notice: str, action_steps: Sequence[str]) -> str:
        lines = [guide.strip(), status_notice.strip()]
        if action_steps:
            lines.append("실행 단계: " + " / ".join(str(step).strip() for step in action_steps if str(step).strip()))
        return "\n".join(line for line in lines if line)

    def _get(self, obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _dedupe(self, items: Iterable[str]) -> List[str]:
        seen = set()
        output: List[str] = []
        for item in items:
            item = str(item or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            output.append(item)
        return output


if __name__ == "__main__":
    class DummyCheck:
        def __init__(self, field_name: str, passed: Optional[bool], message_ko: str = "") -> None:
            self.field_name = field_name
            self.passed = passed
            self.message_ko = message_ko

    class DummyResult:
        status = "ineligible"
        matched_rules = [
            DummyCheck("income_ratio", False, "소득 기준을 초과합니다. (기준: 60% 이하, 현재: 65%)"),
            DummyCheck("age", True, ""),
        ]
        missing_fields = []

    builder = ReasonTemplateBuilder()
    result = builder.build_for_pipeline(DummyResult(), score=48)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
