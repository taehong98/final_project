"""
/rag/search/v2 엔드포인트 테스트 — evaluate.py 30개 질문
실행: python test_v2.py
"""
import json
import httpx
from evaluate import TEST_QUESTIONS

BASE_URL = "http://localhost:8001"

print("=" * 60)
print(f"/rag/search/v2 테스트 ({len(TEST_QUESTIONS)}개 질문)")
print("=" * 60)

success, fail = 0, 0
scores = []

for i, q in enumerate(TEST_QUESTIONS, 1):
    try:
        r = httpx.post(
            f"{BASE_URL}/rag/search/v2",
            json={"query": q, "lang_code": "ko"},
            timeout=120,
        )
        data = r.json()
        if data.get("success"):
            results = data["data"]["search_results"]
            top_score = results[0]["score"] if results else 0
            scores.append(top_score)
            print(f"  ({i:02d}/30) OK {len(results)}개 | top score: {top_score:.4f} | {q[:30]}...")
            success += 1
        else:
            print(f"  ({i:02d}/30) FAIL: {data.get('error_message')} | {q[:30]}...")
            fail += 1
    except Exception as e:
        print(f"  ({i:02d}/30) ERROR: {e} | {q[:30]}...")
        fail += 1

print("\n" + "=" * 60)
print(f"성공: {success}/30  실패: {fail}/30")
if scores:
    print(f"평균 top score: {sum(scores)/len(scores):.4f}")
    print(f"최고 score:     {max(scores):.4f}")
    print(f"최저 score:     {min(scores):.4f}")
print("=" * 60)
