## 정책 설명 파이프라인

이 파이프라인은 복지 정책 원문과 사용자 조건을 입력받아 아래 정보를 반환합니다.

1. 정책 핵심 요약(summary)
2. 탈락 사유 또는 추가 확인 필요 사유(rejection_reason)
3. 보완 가이드(guide)

현재 다국어 지원 구조는 다음과 같습니다.
- 정책 요약은 한국어로 먼저 생성한 뒤 target_lang 기준으로 번역합니다.
- 탈락 사유와 보완 가이드는 한국어로 먼저 분석한 뒤 target_lang 기준으로 번역합니다.
- 명확한 수치 조건 탈락은 rule_engine이 먼저 처리합니다.
- 수치만으로 판단하기 어려운 경우 Qwen이 설명을 생성합니다.

구성 요소
- rule_engine.py: 나이, 소득 등 명확한 수치 조건 우선 판정
- qwen_reasoner.py: 탈락 사유 및 보완 가이드 생성
- summary_service.py: 정책 원문 핵심 요약 생성
- translation_service.py: 요약 결과 다국어 번역
- main_pipeline.py: 전체 통합 실행

입력값
- policy_text: 정책 원문
- user_condition: 사용자 조건
- target_lang: 출력 언어 코드 (ko / en / vi / zh / ja)

최종 반환값
- language
- rule_eligible
- rule_status
- analysis_source
- summary_source
- translation_source
- summary
- rejection_reason
- guide