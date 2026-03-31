from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RuleCheck:
    field_name: str
    rule_type: str
    source_text: str
    policy_min: Optional[float] = None
    policy_max: Optional[float] = None
    min_inclusive: bool = True
    max_inclusive: bool = True
    user_value: Optional[float] = None
    passed: Optional[bool] = None
    message_ko: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationResult:
    # eligible: True / False / None(판정불가)
    eligible: Optional[bool]
    status: str
    rejection_reason_ko: str
    guide_ko: str
    matched_rules: List[RuleCheck] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["matched_rules"] = [rule.to_dict() for rule in self.matched_rules]
        return data


class PolicyRuleEngine:
    AGE_RANGE_PATTERNS = [
        re.compile(r"(?:만\s*)?(\d+)\s*(?:세|살)\s*(?:이상|초과)\s*[~〜\-부터및, ]+\s*(?:만\s*)?(\d+)\s*(?:세|살)\s*(?:이하|미만)"),
        re.compile(r"(?:만\s*)?(\d+)\s*(?:세|살)\s*[~〜\-]\s*(?:만\s*)?(\d+)\s*(?:세|살)"),
    ]
    AGE_SINGLE_PATTERNS = [
        (re.compile(r"(?:만\s*)?(\d+)\s*(?:세|살)\s*이하"), None, "max", True),
        (re.compile(r"(?:만\s*)?(\d+)\s*(?:세|살)\s*미만"), None, "max", False),
        (re.compile(r"(?:만\s*)?(\d+)\s*(?:세|살)\s*이상"), None, "min", True),
        (re.compile(r"(?:만\s*)?(\d+)\s*(?:세|살)\s*초과"), None, "min", False),
    ]

    INCOME_RANGE_PATTERNS = [
        re.compile(
            r"(?:(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*)?"
            r"(?:기준\s*)?중위소득\s*(\d+)\s*(?:%|퍼센트)\s*(?:이상|초과)\s*[~〜\-부터및, ]+\s*(\d+)\s*(?:%|퍼센트)\s*(?:이하|미만)"
        ),
        re.compile(
            r"(?:(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*)?"
            r"(?:기준\s*)?중위소득\s*(\d+)\s*(?:%|퍼센트)\s*[~〜\-]\s*(\d+)\s*(?:%|퍼센트)"
        ),
        re.compile(
            r"(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*(\d+)\s*(?:%|퍼센트)\s*(?:이상|초과)\s*[~〜\-부터및, ]+\s*(\d+)\s*(?:%|퍼센트)\s*(?:이하|미만)"
        ),
        re.compile(
            r"(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*(\d+)\s*(?:%|퍼센트)\s*[~〜\-]\s*(\d+)\s*(?:%|퍼센트)"
        ),
    ]
    INCOME_SINGLE_PATTERNS = [
        (re.compile(r"(?:(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*)?(?:기준\s*)?중위소득\s*(\d+)\s*(?:%|퍼센트)\s*이하"), "max", True),
        (re.compile(r"(?:(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*)?(?:기준\s*)?중위소득\s*(\d+)\s*(?:%|퍼센트)\s*미만"), "max", False),
        (re.compile(r"(?:(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*)?(?:기준\s*)?중위소득\s*(\d+)\s*(?:%|퍼센트)\s*이상"), "min", True),
        (re.compile(r"(?:(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*)?(?:기준\s*)?중위소득\s*(\d+)\s*(?:%|퍼센트)\s*초과"), "min", False),
        (re.compile(r"(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*(\d+)\s*(?:%|퍼센트)\s*이하"), "max", True),
        (re.compile(r"(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*(\d+)\s*(?:%|퍼센트)\s*미만"), "max", False),
        (re.compile(r"(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*(\d+)\s*(?:%|퍼센트)\s*이상"), "min", True),
        (re.compile(r"(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*(\d+)\s*(?:%|퍼센트)\s*초과"), "min", False),
    ]

    def evaluate(self, policy_text: str, user_condition: str) -> EvaluationResult:
        policy_text = str(policy_text or "").strip()
        user_condition = str(user_condition or "").strip()

        rules = self._extract_rules(policy_text)
        user_values = self._extract_user_values(user_condition)

        if not rules:
            return EvaluationResult(
                eligible=None,
                status="unknown",
                rejection_reason_ko="정책 원문에서 판정 가능한 핵심 수치 조건을 찾지 못했습니다.",
                guide_ko="나이, 소득, 지역, 주거 형태 등 추가 조건을 함께 확인해 주세요.",
                matched_rules=[],
                notes=["수치 규칙 미검출"],
            )

        checks: List[RuleCheck] = []
        missing_fields: List[str] = []
        missing_field_seen = set()

        for rule in rules:
            user_value = user_values.get(rule.field_name)
            if user_value is None:
                if rule.field_name in missing_field_seen:
                    continue
                rule.user_value = None
                rule.passed = None
                rule.message_ko = self._missing_message(rule.field_name)
                missing_fields.append(rule.field_name)
                checks.append(rule)
                missing_field_seen.add(rule.field_name)
                continue

            rule.user_value = user_value
            rule.passed, rule.message_ko = self._evaluate_rule(rule, user_value)
            checks.append(rule)

        # 판정 우선순위: 실패 > 사용자 정보 부족 > 모두 통과
        failed = [c for c in checks if c.passed is False]
        unknown = [c for c in checks if c.passed is None]

        if failed:
            return EvaluationResult(
                eligible=False,
                status="ineligible",
                rejection_reason_ko="; ".join(c.message_ko for c in failed),
                guide_ko=self._guide_for_failed_checks(failed),
                matched_rules=checks,
                missing_fields=missing_fields,
            )

        if unknown:
            return EvaluationResult(
                eligible=None,
                status="unknown",
                rejection_reason_ko="입력된 사용자 조건만으로는 일부 필수 조건을 판정할 수 없습니다.",
                guide_ko=self._guide_for_missing_fields(missing_fields),
                matched_rules=checks,
                missing_fields=missing_fields,
            )

        return EvaluationResult(
            eligible=True,
            status="eligible",
            rejection_reason_ko="현재 입력한 핵심 수치 조건에서는 탈락 사유가 확인되지 않았습니다.",
            guide_ko="세부 요건(지역, 가구, 주거, 신청 기간, 무주택 여부 등)은 원문 공고를 추가로 확인하세요.",
            matched_rules=checks,
            missing_fields=[],
        )

    def _extract_rules(self, policy_text: str) -> List[RuleCheck]:
        rules: List[RuleCheck] = []
        rules.extend(self._parse_age_rules(policy_text))
        rules.extend(self._parse_income_rules(policy_text))
        return rules

    def _parse_age_rules(self, text: str) -> List[RuleCheck]:
        rules: List[RuleCheck] = []

        for pattern in self.AGE_RANGE_PATTERNS:
            for match in pattern.finditer(text):
                a, b = int(match.group(1)), int(match.group(2))
                low, high = sorted([a, b])
                rules.append(
                    RuleCheck(
                        field_name="age",
                        rule_type="range",
                        source_text=match.group(0),
                        policy_min=float(low),
                        policy_max=float(high),
                        min_inclusive=True,
                        max_inclusive=True,
                    )
                )

        if rules:
            return self._dedupe_rules(rules)

        for pattern, _, bound_type, inclusive in self.AGE_SINGLE_PATTERNS:
            for match in pattern.finditer(text):
                value = float(match.group(1))
                if bound_type == "min":
                    rules.append(
                        RuleCheck(
                            field_name="age",
                            rule_type="min",
                            source_text=match.group(0),
                            policy_min=value,
                            min_inclusive=inclusive,
                        )
                    )
                else:
                    rules.append(
                        RuleCheck(
                            field_name="age",
                            rule_type="max",
                            source_text=match.group(0),
                            policy_max=value,
                            max_inclusive=inclusive,
                        )
                    )

        return self._merge_same_field_rules(rules, "age")

    def _parse_income_rules(self, text: str) -> List[RuleCheck]:
        rules: List[RuleCheck] = []

        for pattern in self.INCOME_RANGE_PATTERNS:
            for match in pattern.finditer(text):
                a, b = float(match.group(1)), float(match.group(2))
                low, high = sorted([a, b])
                rules.append(
                    RuleCheck(
                        field_name="income_ratio",
                        rule_type="range",
                        source_text=match.group(0),
                        policy_min=low,
                        policy_max=high,
                        min_inclusive=True,
                        max_inclusive=True,
                    )
                )

        if rules:
            return self._dedupe_rules(rules)

        for pattern, bound_type, inclusive in self.INCOME_SINGLE_PATTERNS:
            for match in pattern.finditer(text):
                value = float(match.group(1))
                if bound_type == "min":
                    rules.append(
                        RuleCheck(
                            field_name="income_ratio",
                            rule_type="min",
                            source_text=match.group(0),
                            policy_min=value,
                            min_inclusive=inclusive,
                        )
                    )
                else:
                    rules.append(
                        RuleCheck(
                            field_name="income_ratio",
                            rule_type="max",
                            source_text=match.group(0),
                            policy_max=value,
                            max_inclusive=inclusive,
                        )
                    )

        return self._merge_same_field_rules(rules, "income_ratio")

    def _merge_same_field_rules(self, rules: List[RuleCheck], field_name: str) -> List[RuleCheck]:
        rules = [r for r in rules if r.field_name == field_name]
        if not rules:
            return []

        min_rule = None
        max_rule = None
        others = []
        for rule in rules:
            if rule.policy_min is not None and rule.policy_max is None and min_rule is None:
                min_rule = rule
            elif rule.policy_max is not None and rule.policy_min is None and max_rule is None:
                max_rule = rule
            else:
                others.append(rule)

        if min_rule and max_rule:
            return [
                RuleCheck(
                    field_name=field_name,
                    rule_type="range",
                    source_text=f"{min_rule.source_text} / {max_rule.source_text}",
                    policy_min=min_rule.policy_min,
                    policy_max=max_rule.policy_max,
                    min_inclusive=min_rule.min_inclusive,
                    max_inclusive=max_rule.max_inclusive,
                )
            ]

        return self._dedupe_rules(rules + others)

    def _dedupe_rules(self, rules: List[RuleCheck]) -> List[RuleCheck]:
        seen = set()
        deduped = []
        for rule in rules:
            key = (
                rule.field_name,
                rule.rule_type,
                rule.policy_min,
                rule.policy_max,
                rule.min_inclusive,
                rule.max_inclusive,
            )
            if key not in seen:
                seen.add(key)
                deduped.append(rule)
        return deduped

    def _extract_user_values(self, user_condition: str) -> Dict[str, float]:
        values: Dict[str, float] = {}

        age_match = re.search(r"(?:나이\s*)?(?:만\s*)?(\d+)\s*(?:세|살)", user_condition)
        if age_match:
            values["age"] = float(age_match.group(1))

        income_match = re.search(
            r"(?:(?:소득평가액|소득인정액|소득)\s*(?:이|은|는)?\s*)?(?:기준\s*)?(?:중위소득\s*)?(\d+)\s*(?:%|퍼센트)",
            user_condition,
        )
        if income_match:
            values["income_ratio"] = float(income_match.group(1))

        return values

    def _evaluate_rule(self, rule: RuleCheck, user_value: float) -> Tuple[bool, str]:
        if rule.policy_min is not None:
            if rule.min_inclusive:
                min_ok = user_value >= rule.policy_min
            else:
                min_ok = user_value > rule.policy_min
        else:
            min_ok = True

        if rule.policy_max is not None:
            if rule.max_inclusive:
                max_ok = user_value <= rule.policy_max
            else:
                max_ok = user_value < rule.policy_max
        else:
            max_ok = True

        passed = min_ok and max_ok
        if passed:
            return True, self._pass_message(rule, user_value)
        return False, self._fail_message(rule, user_value)

    def _missing_message(self, field_name: str) -> str:
        label = self._field_label(field_name)
        return f"{label} 정보를 확인할 수 없어 판정할 수 없습니다."

    def _field_label(self, field_name: str) -> str:
        return {
            "age": "나이",
            "income_ratio": "소득평가액 비율",
        }.get(field_name, field_name)

    def _format_bound(self, value: float, inclusive: bool, kind: str, field_name: str) -> str:
        suffix = "%" if field_name == "income_ratio" else "세"
        if kind == "min":
            return f"{value:.0f}{suffix} {'이상' if inclusive else '초과'}"
        return f"{value:.0f}{suffix} {'이하' if inclusive else '미만'}"

    def _pass_message(self, rule: RuleCheck, user_value: float) -> str:
        label = self._field_label(rule.field_name)
        suffix = "%" if rule.field_name == "income_ratio" else "세"
        if rule.policy_min is not None and rule.policy_max is not None:
            return (
                f"{label}이(가) 정책 기준 범위 내입니다. "
                f"(기준: {self._format_bound(rule.policy_min, rule.min_inclusive, 'min', rule.field_name)} ~ "
                f"{self._format_bound(rule.policy_max, rule.max_inclusive, 'max', rule.field_name)}, 현재: {user_value:.0f}{suffix})"
            )
        if rule.policy_min is not None:
            return f"{label}이(가) 정책 기준을 충족합니다. (기준: {self._format_bound(rule.policy_min, rule.min_inclusive, 'min', rule.field_name)}, 현재: {user_value:.0f}{suffix})"
        return f"{label}이(가) 정책 기준을 충족합니다. (기준: {self._format_bound(rule.policy_max, rule.max_inclusive, 'max', rule.field_name)}, 현재: {user_value:.0f}{suffix})"

    def _fail_message(self, rule: RuleCheck, user_value: float) -> str:
        label = self._field_label(rule.field_name)
        suffix = "%" if rule.field_name == "income_ratio" else "세"

        if rule.policy_min is not None and user_value < rule.policy_min:
            return f"{label}이(가) 최소 기준보다 낮습니다. (기준: {self._format_bound(rule.policy_min, rule.min_inclusive, 'min', rule.field_name)}, 현재: {user_value:.0f}{suffix})"
        if rule.policy_min is not None and (not rule.min_inclusive) and user_value == rule.policy_min:
            return f"{label}이(가) 최소 기준을 충족하지 못합니다. (기준: {self._format_bound(rule.policy_min, rule.min_inclusive, 'min', rule.field_name)}, 현재: {user_value:.0f}{suffix})"
        if rule.policy_max is not None and user_value > rule.policy_max:
            return f"{label}이(가) 최대 기준을 초과합니다. (기준: {self._format_bound(rule.policy_max, rule.max_inclusive, 'max', rule.field_name)}, 현재: {user_value:.0f}{suffix})"
        if rule.policy_max is not None and (not rule.max_inclusive) and user_value == rule.policy_max:
            return f"{label}이(가) 최대 기준을 충족하지 못합니다. (기준: {self._format_bound(rule.policy_max, rule.max_inclusive, 'max', rule.field_name)}, 현재: {user_value:.0f}{suffix})"
        return f"{label}이(가) 정책 기준을 충족하지 못합니다. (현재: {user_value:.0f}{suffix})"

    def _guide_for_failed_checks(self, failed_checks: List[RuleCheck]) -> str:
        messages = []
        for check in failed_checks:
            if check.field_name == "income_ratio":
                messages.append("소득평가액이 기준 범위에 들어가는지 다시 확인하고, 공고문상 예외 기준이나 공제 항목이 있는지 확인하세요.")
            elif check.field_name == "age":
                messages.append("정책의 연령 기준을 다시 확인하고, 공고문에 출생연도 기준이나 예외 조건이 있는지 확인하세요.")
            else:
                messages.append(f"{self._field_label(check.field_name)} 조건을 다시 확인하세요.")
        return " ".join(dict.fromkeys(messages))

    def _guide_for_missing_fields(self, missing_fields: List[str]) -> str:
        labels = [self._field_label(f) for f in dict.fromkeys(missing_fields)]
        joined = ", ".join(labels)
        return f"{joined} 정보를 입력한 뒤 다시 확인하세요. 세부 기준은 공고문 원문과 관할 기관 안내를 함께 확인하세요."


if __name__ == "__main__":
    engine = PolicyRuleEngine()

    sample_user = "저는 27살이고 월세 거주 중이며 소득은 65%입니다."
    sample_policy = "청년월세지원은 만 19세 이상 34세 이하이면서 소득 60% 이하인 자만 신청 가능하며, 신청은 관할 주민센터에서 받습니다."

    result = engine.evaluate(sample_policy, sample_user)
    print(result.to_dict())
