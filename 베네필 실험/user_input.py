"""
05 사용자 입력
=============
input() 기반 사용자 정보 수집 모듈

수정 사항:
  - [BUG FIX] 재입력 처리를 재귀 호출 → while 루프로 교체
    (기존: return get_user_input() 재귀 → 입력 반복 시 스택 오버플로 가능)
"""

# ──────────────────────────────────────────────
# 선택지 상수
# ──────────────────────────────────────────────
FAMILY_TYPES = {
    "1": "1인 가구",
    "2": "2인 가구",
    "3": "3인 가구",
    "4": "4인 이상 가구",
    "5": "한부모 가구",
    "6": "다자녀 가구",
}

EMPLOYMENT_TYPES = {
    "1": "취업자 (정규직)",
    "2": "취업자 (비정규직/계약직)",
    "3": "자영업자",
    "4": "구직자 (실업)",
    "5": "학생",
    "6": "육아휴직 중",
    "7": "무직",
}

DISABILITY_TYPES = {
    "1": "없음",
    "2": "장애 1~3급 (심한 장애)",
    "3": "장애 4~6급 (심하지 않은 장애)",
}


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────
def _ask_int(prompt: str, min_val: int = 0, max_val: int = 999) -> int:
    while True:
        try:
            val = int(input(prompt).strip())
            if min_val <= val <= max_val:
                return val
            print(f"  ⚠️  {min_val} ~ {max_val} 사이 숫자를 입력하세요.\n")
        except ValueError:
            print("  ⚠️  숫자를 입력하세요.\n")


def _ask_choice(prompt: str, choices: dict[str, str]) -> str:
    print(prompt)
    for key, label in choices.items():
        print(f"  {key}. {label}")
    while True:
        val = input("  선택 (번호): ").strip()
        if val in choices:
            return choices[val]
        print(f"  ⚠️  {', '.join(choices.keys())} 중에서 입력하세요.\n")


def _ask_bool(prompt: str) -> bool:
    while True:
        val = input(f"{prompt} (y/n): ").strip().lower()
        if val in ("y", "yes", "예"):
            return True
        if val in ("n", "no", "아니오"):
            return False
        print("  ⚠️  y 또는 n 으로 입력하세요.\n")


def _collect_once() -> dict:
    """사용자 정보를 한 번 수집해 dict 반환"""
    print()
    print("=" * 50)
    print("  베네픽 — 사용자 정보 입력")
    print("=" * 50)
    print()

    age    = _ask_int("나이 (만 나이): ", 0, 120)
    income = _ask_int("\n연소득 (만원, 없으면 0): ", 0, 99999)

    family_type = _ask_choice("\n가구 유형을 선택하세요:", FAMILY_TYPES)
    family_size = _ask_int("\n가구원 수 (본인 포함): ", 1, 20)

    print("\n거주 지역을 입력하세요 (예: 서울, 경기, 부산)")
    region = input("  거주지역: ").strip() or "전국"

    employment  = _ask_choice("\n고용 상태를 선택하세요:", EMPLOYMENT_TYPES)

    print()
    disability    = _ask_choice("장애 여부:", DISABILITY_TYPES)
    veteran       = _ask_bool("\n국가유공자 여부")
    multicultural = _ask_bool("다문화 가구 여부")

    return {
        "나이":      age,
        "연소득":    income,
        "가구유형":  family_type,
        "가구원수":  family_size,
        "거주지역":  region,
        "고용상태":  employment,
        "장애여부":  disability,
        "국가유공자": veteran,
        "다문화가구": multicultural,
    }


# ──────────────────────────────────────────────
# 메인 입력 함수
# ──────────────────────────────────────────────
def get_user_input() -> dict:
    """
    사용자 정보를 input()으로 수집하여 dict 반환

    [수정] 재입력 시 재귀 호출 → while 루프로 교체
    기존: confirm == False → return get_user_input()  (스택 계속 쌓임)
    수정: confirm == False → continue  (같은 스택 프레임 재사용)
    """
    while True:
        user = _collect_once()

        # 확인 출력
        print()
        print("─" * 50)
        print("  입력 정보 확인")
        print("─" * 50)
        for k, v in user.items():
            print(f"  {k:10s}: {v}")
        print("─" * 50)
        print()

        if _ask_bool("이 정보로 검색을 진행할까요?"):
            return user

        print("\n다시 입력합니다.\n")


# ──────────────────────────────────────────────
if __name__ == "__main__":
    user_info = get_user_input()
    print("\n✅ 수집 완료:", user_info)
