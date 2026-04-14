import pandas as pd

# ── 지역 목록 ──
REGIONS = [
    '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
    '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
]


def clean_field(val) -> str | None:
    """NaN, 빈 값, 의미 없는 값 제거"""
    if val is None:
        return None
    s = str(val).strip()
    if s in ('nan', 'NaN', 'None', '-', '없음', '해당없음', '해당사항없음', ''):
        return None
    return s


def extract_region(text: str, name: str = '') -> str:
    """텍스트/정책명에서 지역 추출, 없으면 '전국'"""
    combined = f"{name} {text}"
    for r in REGIONS:
        if r in combined:
            return r
    return '전국'


def extract_region_from_sojaiji(sojaiji: str) -> str:
    """
    정부24 소재지 컬럼 파싱
    예) '전국(전국)' → '전국', '서울특별시(서울)' → '서울'
    """
    if not sojaiji or sojaiji == '전국(전국)':
        return '전국'
    for r in REGIONS:
        if r in sojaiji:
            return r
    return '전국'


# ── 복지로 ──
def load_data(path="data/raw/welfare_policies.csv"):
    df = pd.read_csv(path, encoding="utf-8-sig")
    print(f"복지로 데이터 로드 완료! {len(df)}건")
    return df


def process_policies(df) -> list[dict]:
    """복지로 정책 데이터 정제 (NaN 제거, 지역 추출)"""
    records = []
    skipped = 0

    for _, row in df.iterrows():
        policy_name = clean_field(row.get('서비스명'))
        if not policy_name:
            skipped += 1
            continue

        policy_id  = str(row['서비스아이디'])
        summary    = clean_field(row.get('서비스요약'))
        department = clean_field(row.get('소관부처명'))
        org        = clean_field(row.get('소관조직명'))
        contact    = clean_field(row.get('대표문의'))
        source_url = clean_field(row.get('서비스URL')) or ''

        lines = [f"정책명: {policy_name}"]
        if department:
            lines.append(f"소관부처: {department}")
        if org:
            lines.append(f"소관조직: {org}")
        if summary:
            lines.append(f"서비스요약: {summary}")
        if contact:
            lines.append(f"대표문의: {contact}")

        text   = '\n'.join(lines)
        region = extract_region(text, policy_name)

        records.append({
            "chunk_id":    policy_id,
            "policy_id":   policy_id,
            "text":        text,
            "policy_name": policy_name,
            "category":    department or '기타',
            "region":      region,
            "source_url":  source_url,
        })

    print(f"복지로 처리 완료! {len(records)}건 (스킵: {skipped}건)")
    return records


# ── 정부24 ──
def load_gov24_data(path="data/raw/gov24_policies.csv"):
    df = pd.read_csv(path, encoding="utf-8-sig")
    print(f"정부24 데이터 로드 완료! {len(df)}건")
    return df


def process_gov24_policies(df) -> list[dict]:
    """정부24 정책 데이터 정제 (NaN 제거, 지역 추출)"""
    records = []
    skipped = 0

    for _, row in df.iterrows():
        policy_name = clean_field(row.get('서비스명'))
        if not policy_name:
            skipped += 1
            continue

        policy_id  = str(row['서비스ID'])
        category   = clean_field(row.get('서비스분야'))
        target     = clean_field(row.get('지원대상'))
        content    = clean_field(row.get('지원내용'))
        criteria   = clean_field(row.get('선정기준'))
        method     = clean_field(row.get('신청방법'))
        deadline   = clean_field(row.get('신청기한'))
        org        = clean_field(row.get('소관기관명'))
        contact    = clean_field(row.get('전화문의'))
        source_url = clean_field(row.get('상세조회URL')) or ''
        sojaiji    = clean_field(row.get('소재지')) or ''
        subtitle   = clean_field(row.get('서비스명부제목'))

        lines = [f"정책명: {policy_name}"]
        if subtitle:
            lines.append(f"부제목: {subtitle}")
        if category:
            lines.append(f"서비스분야: {category}")
        if target:
            lines.append(f"지원대상: {target}")
        if content:
            lines.append(f"지원내용: {content}")
        if criteria:
            lines.append(f"선정기준: {criteria}")
        if method:
            lines.append(f"신청방법: {method}")
        if deadline:
            lines.append(f"신청기한: {deadline}")
        if org:
            lines.append(f"소관기관: {org}")
        if contact:
            lines.append(f"전화문의: {contact}")

        text   = '\n'.join(lines)
        region = extract_region_from_sojaiji(sojaiji) if sojaiji else extract_region(text, policy_name)

        records.append({
            "chunk_id":    policy_id,
            "policy_id":   policy_id,
            "text":        text,
            "policy_name": policy_name,
            "category":    category or '기타',
            "region":      region,
            "source_url":  source_url,
        })

    print(f"정부24 처리 완료! {len(records)}건 (스킵: {skipped}건)")
    return records


if __name__ == "__main__":
    df = load_data()
    records = process_policies(df)
    print(f"\n샘플 (복지로):")
    print(records[0]["text"])
    print(f"region: {records[0]['region']}")

    df_gov24 = load_gov24_data()
    records_gov24 = process_gov24_policies(df_gov24)
    print(f"\n샘플 (정부24):")
    print(records_gov24[0]["text"])
    print(f"region: {records_gov24[0]['region']}")
