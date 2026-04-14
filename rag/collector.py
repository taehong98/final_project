import requests
import pandas as pd
import time
import os
from dotenv import load_dotenv

load_dotenv()

# ── 복지로 API ──
API_KEY  = os.getenv("BOKJIRO_API_KEY")
BASE_URL = "https://api.odcloud.kr/api/15083323/v1/uddi:3929b807-3420-44d7-a851-cc741fce65a1"

# ── 정부24 API ──
GOV24_URL        = "https://api.odcloud.kr/api/gov24/v3/serviceList"
GOV24_DETAIL_URL = "https://api.odcloud.kr/api/gov24/v3/serviceDetail"
GOV24_COND_URL   = "https://api.odcloud.kr/api/gov24/v3/supportConditions"
GOV24_API_KEY    = os.getenv("GOV24_API_KEY")


# ── 복지로 함수들 ──
def test_connection():
    print("복지로 API 연결 테스트 중...")
    params = {
        "serviceKey": API_KEY,
        "page":       1,
        "perPage":    3,
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=15)
        print(f"상태코드: {res.status_code}")
        print(f"응답 내용 (앞 500자):\n{res.text[:500]}")
        return res
    except Exception as e:
        print(f"연결 오류: {e}")
        return None

def collect_policies():
    all_data = []
    page = 1

    print("\n복지 정책 수집 시작...")

    while True:
        try:
            params = {
                "serviceKey": API_KEY,
                "page":       page,
                "perPage":    100,
            }
            res = requests.get(BASE_URL, params=params, timeout=15)
            print(f"  {page}페이지 상태코드: {res.status_code}")

            if res.status_code != 200:
                print(f"  오류: {res.text[:300]}")
                break

            data = res.json()

            if page == 1:
                print(f"\n  응답 키 목록: {list(data.keys())}")
                print(f"  전체 데이터 수: {data.get('totalCount', '알 수 없음')}")

            items = data.get("data", [])

            if not items:
                print(f"  {page}페이지 끝")
                break

            all_data.extend(items)
            print(f"  {page}페이지 → {len(items)}건 (누적: {len(all_data)}건)")

            total = data.get("totalCount", 0)
            if len(all_data) >= total:
                print("  모든 데이터 수집 완료!")
                break

            page += 1
            time.sleep(0.3)

            if page > 100:
                break

        except Exception as e:
            print(f"오류 (페이지 {page}): {e}")
            break

    print(f"\n수집 완료! 총 {len(all_data)}건")
    return all_data

def save_csv(data, path="data/raw/welfare_policies.csv"):
    if not data:
        print("저장할 데이터 없음!")
        return None

    df = pd.DataFrame(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")

    print(f"\n저장 완료! → {path}")
    print(f"총 {len(df)}건, {len(df.columns)}개 컬럼")
    print(f"\n컬럼 목록:\n{df.columns.tolist()}")
    print(f"\n샘플:\n{df.head(2).to_string()}")
    return df


# ── 정부24 함수들 ──
def collect_gov24_policies():
    """정부24 서비스 목록 수집"""
    all_data = []
    page = 1

    print("\n정부24 정책 수집 시작...")

    while True:
        try:
            params = {
                "serviceKey": GOV24_API_KEY,
                "page":       page,
                "perPage":    100,
            }
            res = requests.get(GOV24_URL, params=params, timeout=15)
            print(f"  {page}페이지 상태코드: {res.status_code}")

            if res.status_code != 200:
                print(f"  오류: {res.text[:300]}")
                break

            data = res.json()

            if page == 1:
                print(f"  전체 데이터 수: {data.get('totalCount', '알 수 없음')}")

            items = data.get("data", [])
            if not items:
                print(f"  {page}페이지 끝")
                break

            all_data.extend(items)
            print(f"  {page}페이지 → {len(items)}건 (누적: {len(all_data)}건)")

            total = data.get("totalCount", 0)
            if len(all_data) >= total:
                print("  모든 데이터 수집 완료!")
                break

            page += 1
            time.sleep(0.3)

            if page > 100:
                break

        except Exception as e:
            print(f"오류 (페이지 {page}): {e}")
            break

    print(f"\n수집 완료! 총 {len(all_data)}건")
    return all_data


def collect_gov24_conditions(service_ids: list) -> dict:
    """
    정부24 지원조건 수집 (연령, 소득, 가구 형태 등)
    service_ids: 서비스ID 리스트
    반환: {서비스ID: 조건 딕셔너리}
    """
    conditions = {}
    print(f"\n지원조건 수집 중... ({len(service_ids)}건)")

    for i, sid in enumerate(service_ids):
        try:
            params = {
                "serviceKey":        GOV24_API_KEY,
                "page":              1,
                "perPage":           1,
                "cond[서비스ID::EQ]": sid,
            }
            res = requests.get(GOV24_COND_URL, params=params, timeout=15)
            if res.status_code == 200:
                data = res.json().get("data", [])
                if data:
                    conditions[sid] = data[0]

            if (i + 1) % 50 == 0:
                print(f"  {i+1}/{len(service_ids)}건 완료")

            time.sleep(0.1)  # API 호출 제한 방지

        except Exception as e:
            print(f"  오류 ({sid}): {e}")

    print(f"지원조건 수집 완료! {len(conditions)}건")
    return conditions


def save_gov24_csv(policies, conditions, path="data/raw/gov24_policies.csv"):
    """정책 + 지원조건 합쳐서 저장"""
    if not policies:
        print("저장할 데이터 없음!")
        return None

    df = pd.DataFrame(policies)

    # 지원조건 컬럼 추가
    cond_cols = [
        'JA0110', 'JA0111',  # 대상연령 시작/종료
        'JA0201', 'JA0202', 'JA0203', 'JA0204', 'JA0205',  # 중위소득
        'JA0404',  # 1인가구
        'JA0403',  # 한부모가정
        'JA0326',  # 근로자
        'JA0327',  # 구직자/실업자
        'JA0328',  # 장애인
    ]
    for col in cond_cols:
        df[col] = df['서비스ID'].map(
            lambda sid: conditions.get(sid, {}).get(col, None)
        )

    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")

    print(f"\n저장 완료! → {path}")
    print(f"총 {len(df)}건, {len(df.columns)}개 컬럼")
    return df


# ── 실행 ──
if __name__ == "__main__":
    # 복지로 수집
    test_connection()
    data = collect_policies()
    df = save_csv(data)

    # 정부24 수집
    gov24_data = collect_gov24_policies()
    service_ids = [d['서비스ID'] for d in gov24_data]
    conditions = collect_gov24_conditions(service_ids)
    save_gov24_csv(gov24_data, conditions)