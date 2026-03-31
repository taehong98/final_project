const TAB_PAGE_MAP = {
  'dashboard': 'index.html',
  'search':    'search.html',
  'detail':    'analysis.html',
  'portfolio': 'portfolio.html',
  'apply':     'apply.html',
  'community': 'community.html',
};

function showTab(tab) {
  const page = TAB_PAGE_MAP[tab];
  if (page) {
    window.location.href = page;
    return;
  }

  // Update screens
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const screenEl = document.getElementById('screen-' + tab);
  if (screenEl) screenEl.classList.add('active');

  // Update tabs
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const tabEl = document.getElementById('tab-' + tab);
  if (tabEl) tabEl.classList.add('active');

  // detail-panel visibility: detail 탭일 때만 visible
  const detailPanel = document.querySelector('.detail-panel');
  if (detailPanel) {
    if (tab === 'detail') detailPanel.classList.add('visible');
    else detailPanel.classList.remove('visible');
  }

  // 포트폴리오 탭 전환 시 자동 로드
  if (tab === 'portfolio') loadPortfolio();

  // FAB visibility
  const fab = document.getElementById('fabWrite');
  if (tab === 'community') {
    fab.classList.add('visible');
    renderCommPosts();
    // sync insight widget stats
    const p = document.getElementById('iStatPosts');
    const l = document.getElementById('iStatLikes');
    if(p) p.textContent = commPosts.length;
    if(l) l.textContent = commPosts.reduce((s,post) => s + post.likes, 0);
    insightAnimateBars();
  } else {
    fab.classList.remove('visible');
  }

  // Scroll to top
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ══════════════════════════════════════════════════════════════
// 베네픽 API 클라이언트 v2.1
// ══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════
// 베네픽 v2.3 — Claude AI 직접 연동 (백엔드 불필요)
// ══════════════════════════════════════════════════════════════

// 현재 분석 세션
let _currentQueryId = null;

// _currentPortfolio: localStorage 영속화 (페이지 이동 후에도 유지)
function _savePortfolio(data) {
  try { localStorage.setItem('benefic_portfolio', JSON.stringify(data)); } catch(e) {}
}
function _scoreToCSS(score) {
  if (score >= 80) return { card_class:'top', percent_class:'high', progress_color:'green', badge_class:'badge-green', badge_label:'✅ 조건 충족' };
  if (score >= 60) return { card_class:'mid', percent_class:'mid', progress_color:'blue', badge_class:'badge-blue', badge_label:'⚡ 확인 필요' };
  return { card_class:'low', percent_class:'low', progress_color:'orange', badge_class:'badge-orange', badge_label:'⚠️ 조건 부족' };
}
function _loadPortfolio() {
  try {
    const s = localStorage.getItem('benefic_portfolio');
    if (!s) return [];
    const arr = JSON.parse(s);
    // _css 누락 시 재계산
    return arr.map(card => {
      if (!card._css) card._css = _scoreToCSS(card.수급확률 || card.eligibility_percent || 60);
      return card;
    });
  } catch(e) { return []; }
}
let _currentPortfolio = _loadPortfolio();  // 분석 결과 캐시 (페이지 간 공유)

// ── 한국 공공복지 정책 데이터베이스 (내장) ──────────────────
const POLICY_DB = [
  { 서비스명:'청년 월세 한시 특별지원', 서비스분야:'주거', 지원유형:'현금', 소관기관명:'국토교통부', 지원대상:'만 19~34세 무주택 청년, 부모와 별도 거주, 월세 60만원 이하', 선정기준:'중위소득 60% 이하, 원가구 중위소득 100% 이하', 신청방법:'복지로 또는 주민센터', 신청기한:'연중 상시', 전화문의:'1600-0777', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'월 최대 20만원, 최대 12개월 지원' },
  { 서비스명:'국민내일배움카드', 서비스분야:'고용', 지원유형:'이용권', 소관기관명:'고용노동부', 지원대상:'실업자, 이직 예정자, 비정규직, 단기근로자, 자영업자', 선정기준:'재직자 중 일부 제외, 고소득 재직자 제외', 신청방법:'고용24(work24.go.kr) 온라인 신청', 신청기한:'연중 상시', 전화문의:'1350', 상세조회url:'https://www.work24.go.kr', 지원내용:'훈련비 최대 500만원, 자부담 15~55%' },
  { 서비스명:'청년도약계좌', 서비스분야:'금융', 지원유형:'현금', 소관기관명:'금융위원회', 지원대상:'만 19~34세, 개인소득 6,000만원 이하, 가구소득 중위 180% 이하', 선정기준:'병역 이행기간 최대 6년 제외, 직전 3년 금융소득종합과세 제외', 신청방법:'은행 앱 또는 영업점', 신청기한:'연중 신청 가능(월별 모집)', 전화문의:'1332', 상세조회url:'https://www.fsc.go.kr', 지원내용:'월 최대 70만원 납입 시 정부기여금 최대 6%, 5년 만기 최대 5,000만원' },
  { 서비스명:'청년 마음건강 지원사업', 서비스분야:'보건', 지원유형:'이용권', 소관기관명:'보건복지부', 지원대상:'만 19~34세 청년, 소득 기준 없음', 선정기준:'심리상담 필요 청년, 정신건강 복지센터 대상자 우선', 신청방법:'정신건강복지센터 또는 지자체 문의', 신청기한:'연중 상시(예산 소진 시 마감)', 전화문의:'1577-0199', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'전문심리상담 연간 10회 이내 지원, 1회당 최대 8만원' },
  { 서비스명:'청년창업사관학교', 서비스분야:'창업', 지원유형:'현금', 소관기관명:'중소벤처기업부', 지원대상:'만 39세 이하 예비창업자 또는 창업 3년 이내', 선정기준:'창업 아이템 보유, 사업계획서 제출, 서류·면접 심사 통과', 신청방법:'K-Startup 홈페이지 온라인 접수', 신청기한:'연 1회 공고(보통 1~2월)', 전화문의:'1357', 상세조회url:'https://www.k-startup.go.kr', 지원내용:'창업지원금 최대 1억원, 사무공간·멘토링 제공' },
  { 서비스명:'기초생활보장 생계급여', 서비스분야:'기초생활', 지원유형:'현금', 소관기관명:'보건복지부', 지원대상:'소득인정액이 기준 중위소득 30% 이하 가구', 선정기준:'부양의무자 기준 완화 적용, 재산·소득 종합 심사', 신청방법:'주민센터 방문 신청, 복지로 온라인 신청', 신청기한:'연중 상시', 전화문의:'129', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'1인 가구 월 최대 713,102원(2024년 기준)' },
  { 서비스명:'기초생활보장 주거급여', 서비스분야:'주거', 지원유형:'현금', 소관기관명:'국토교통부', 지원대상:'소득인정액 기준 중위소득 48% 이하 가구', 선정기준:'임차가구: 기준임대료 내 실제 임차료 지급, 자가가구: 수선비 지원', 신청방법:'주민센터 방문 또는 복지로 신청', 신청기한:'연중 상시', 전화문의:'1600-0777', 상세조회url:'https://www.myhome.go.kr', 지원내용:'서울 1인 가구 월 최대 341,000원' },
  { 서비스명:'실업급여(구직급여)', 서비스분야:'고용', 지원유형:'현금', 소관기관명:'고용노동부', 지원대상:'이직 전 18개월 중 피보험 단위기간 180일 이상, 비자발적 이직자', 선정기준:'적극적 구직활동 의무, 재취업 활동 인정 기준 충족', 신청방법:'고용24 온라인 신청 후 고용센터 방문', 신청기한:'이직일 다음 날부터 12개월 이내', 전화문의:'1350', 상세조회url:'https://www.work24.go.kr', 지원내용:'퇴직 전 평균임금 60%, 최소 1일 63,104원~최대 66,000원' },
  { 서비스명:'아동수당', 서비스분야:'가족', 지원유형:'현금', 소관기관명:'보건복지부', 지원대상:'만 8세 미만(0~95개월) 아동', 선정기준:'소득·재산 기준 없이 연령 조건만 충족하면 지급', 신청방법:'복지로, 정부24, 주민센터', 신청기한:'출생일로부터 60일 이내 신청 시 소급 지급', 전화문의:'129', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'월 10만원 지급' },
  { 서비스명:'한부모가족 아동양육비', 서비스분야:'가족', 지원유형:'현금', 소관기관명:'여성가족부', 지원대상:'소득 기준 중위소득 63% 이하 한부모가족, 만 18세 미만 자녀', 선정기준:'한부모 가구 인정, 소득·재산 심사', 신청방법:'주민센터 방문 신청', 신청기한:'연중 상시', 전화문의:'1577-2514', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'아동 1인당 월 21만원(2024년 기준)' },
  { 서비스명:'노인 기초연금', 서비스분야:'노인', 지원유형:'현금', 소관기관명:'보건복지부', 지원대상:'만 65세 이상, 소득하위 70% 이하 어르신', 선정기준:'단독가구 월 소득인정액 202만원 이하(2024년)', 신청방법:'주민센터, 국민연금공단, 복지로', 신청기한:'만 65세 생일 1개월 전부터 신청 가능', 전화문의:'1355', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'단독가구 최대 월 334,810원(2024년)' },
  { 서비스명:'장애인 활동지원서비스', 서비스분야:'장애인', 지원유형:'서비스', 소관기관명:'보건복지부', 지원대상:'만 6세~만 65세 미만 장애인, 장애등급 1~3급', 선정기준:'활동지원 인정조사 점수 42점 이상', 신청방법:'주민센터 방문 신청', 신청기한:'연중 상시', 전화문의:'129', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'활동지원급여 월 최대 1,869천원(구간별 차등)' },
  { 서비스명:'청년내일저축계좌', 서비스분야:'금융', 지원유형:'현금', 소관기관명:'보건복지부', 지원대상:'만 19~34세 수급자·차상위 청년, 소득 기준 중위소득 100% 이하 근로·사업소득자', 선정기준:'기준 중위소득 50% 이하 가구 우선, 근로·사업소득 월 10만원 이상', 신청방법:'복지로 온라인 또는 주민센터', 신청기한:'연 1회 공고(보통 5~6월)', 전화문의:'129', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'본인 적립 월 10만원 시 정부 지원금 월 10~30만원 매칭, 3년 만기' },
  { 서비스명:'국가장학금(한국장학재단)', 서비스분야:'교육', 지원유형:'현금', 소관기관명:'교육부', 지원대상:'국내 대학 재학생, 소득 기준 충족자', 선정기준:'소득분위 1~8구간, 성적 기준(C학점 이상), 국내 대학 재학', 신청방법:'한국장학재단 홈페이지(www.kosaf.go.kr)', 신청기한:'학기별 신청(2월/8월)', 전화문의:'1599-2000', 상세조회url:'https://www.kosaf.go.kr', 지원내용:'소득 1~3구간 전액, 4구간 390만원, 8구간 67.5만원(학기당)' },
  { 서비스명:'자활근로사업', 서비스분야:'고용', 지원유형:'서비스', 소관기관명:'보건복지부', 지원대상:'기초생활수급자 및 차상위계층 중 근로능력자', 선정기준:'자활센터 상담 후 자활 참여 의사 있는 자', 신청방법:'지역자활센터 또는 주민센터', 신청기한:'연중 상시', 전화문의:'129', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'근로 유형별 급여(시장형: 최저임금 100%, 근로유지형: 최저임금 80%)' },
  { 서비스명:'긴급복지지원', 서비스분야:'기초생활', 지원유형:'현금', 소관기관명:'보건복지부', 지원대상:'위기상황 발생으로 생계유지 곤란한 가구', 선정기준:'갑작스러운 실직·질병·사고 등 위기사유, 소득·재산 기준', 신청방법:'주민센터 또는 복지부 상담 전화', 신청기한:'위기사유 발생 즉시', 전화문의:'129', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'생계지원 1인 가구 월 683,400원, 의료·주거·교육지원 등 연계' },
  { 서비스명:'다문화가족 방문교육서비스', 서비스분야:'가족', 지원유형:'서비스', 소관기관명:'여성가족부', 지원대상:'결혼이민자 및 귀화자로 구성된 다문화가족', 선정기준:'입국 5년 이하 우선 지원, 한국어 교육 미이수자', 신청방법:'다문화가족지원센터 신청', 신청기한:'연중 상시', 전화문의:'1577-1366', 상세조회url:'https://www.mogef.go.kr', 지원내용:'한국어교육·부모교육·자녀생활지원 등 가정방문 교육 서비스 제공' },
  { 서비스명:'노인 일자리 및 사회활동 지원사업', 서비스분야:'노인', 지원유형:'현금', 소관기관명:'보건복지부', 지원대상:'만 65세 이상(일부 사업 60세 이상), 기초연금 수급자 우선', 선정기준:'공익형·사회서비스형·시장형 등 유형별 별도 기준', 신청방법:'주민센터, 노인복지관, 시니어클럽', 신청기한:'연초 공고(1~2월 주로 접수)', 전화문의:'1577-1389', 상세조회url:'https://www.bokjiro.go.kr', 지원내용:'공익형 월 27만원, 사회서비스형 월 78.2만원(2024년 기준)' },
  { 서비스명:'청년 취업성공패키지', 서비스분야:'고용', 지원유형:'서비스', 소관기관명:'고용노동부', 지원대상:'만 18~34세 미취업 청년(Ⅰ유형: 중위소득 60% 이하, Ⅱ유형: 소득 무관)', 선정기준:'고용센터 상담 후 참여 결정, 취업 의지 확인', 신청방법:'고용24(work24.go.kr) 또는 고용센터 방문', 신청기한:'연중 상시', 전화문의:'1350', 상세조회url:'https://www.work24.go.kr', 지원내용:'진단·경력설계 수당 25만원, 훈련수당 월 최대 28.4만원, 취업 장려금 최대 150만원' },
  { 서비스명:'에너지바우처', 서비스분야:'기초생활', 지원유형:'이용권', 소관기관명:'산업통상자원부', 지원대상:'기초생활수급자 중 노인·영유아·장애인·임산부·중증질환자 포함 가구', 선정기준:'에너지 취약계층 요건 충족, 소득 기준 충족', 신청방법:'주민센터 방문 신청', 신청기한:'매년 5~6월 신청', 전화문의:'1600-3190', 상세조회url:'https://www.energyv.or.kr', 지원내용:'1인 가구 연간 최대 95,000원, 가구원수 및 계절에 따라 차등' },
];

// ── 검색 상태 ────────────────────────────────────────────────
const _searchCache = {};

// ── Claude AI 직접 호출 ──────────────────────────────────────
async function callClaudeSearch(userMessage) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 1000,
      messages: [{ role: 'user', content: userMessage }]
    })
  });
  if (!res.ok) throw new Error(`Claude API 오류: ${res.status}`);
  const data = await res.json();
  const text = data.content.filter(b => b.type === 'text').map(b => b.text).join('');
  try {
    const clean = text.replace(/```json\n?/g,'').replace(/```\n?/g,'').trim();
    return JSON.parse(clean);
  } catch(e) {
    return { raw: text };
  }
}

// ── 내장 DB 검색 (키워드 기반) ──────────────────────────────
function localKeywordSearch(keyword, category, supportType, limit = 20) {
  const kw = (keyword || '').toLowerCase();
  return POLICY_DB.filter(p => {
    const matchKw = !kw ||
      (p.서비스명||'').toLowerCase().includes(kw) ||
      (p.지원내용||'').toLowerCase().includes(kw) ||
      (p.지원대상||'').toLowerCase().includes(kw) ||
      (p.서비스분야||'').toLowerCase().includes(kw) ||
      (p.소관기관명||'').toLowerCase().includes(kw);
    const matchCat  = !category    || (p.서비스분야||'').includes(category);
    const matchType = !supportType || (p.지원유형||'').includes(supportType);
    return matchKw && matchCat && matchType;
  }).slice(0, limit);
}

// ── AI 자연어 검색 (Claude 활용) ────────────────────────────
async function localNaturalSearch(query, topK = 15) {
  const cacheKey = query + topK;
  if (_searchCache[cacheKey]) return _searchCache[cacheKey];

  const dbSummary = POLICY_DB.map((p,i) =>
    `[${i}] ${p.서비스명} / ${p.서비스분야} / ${p.지원유형} / 대상: ${(p.지원대상||'').substring(0,60)}`
  ).join('\n');

  const prompt = `당신은 한국 복지 정책 검색 전문가입니다.
다음은 복지 정책 데이터베이스입니다:
${dbSummary}

사용자 검색어: "${query}"

위 정책 중 사용자 검색어와 가장 관련 있는 정책의 인덱스 번호를 최대 ${topK}개 골라서,
관련도 높은 순으로 JSON 배열로만 응답하세요. 예: [2, 7, 0, 14]
다른 설명 없이 JSON 배열만 출력하세요.`;

  try {
    const result = await callClaudeSearch(prompt);
    let indices = Array.isArray(result) ? result : (result.raw ? JSON.parse(result.raw) : []);
    const results = indices
      .filter(i => i >= 0 && i < POLICY_DB.length)
      .map(i => ({ ...POLICY_DB[i], score: 1 - (indices.indexOf(i) * 0.05) }));
    _searchCache[cacheKey] = results;
    return results;
  } catch(e) {
    // AI 실패 시 키워드 검색으로 폴백
    return localKeywordSearch(query, '', '', topK);
  }
}

// ── /analyze 대체: Claude AI 분석 ──────────────────────────
async function localAnalyze(payload) {
  const age        = payload.age || payload.나이 || '';
  const region     = payload.region || payload.거주지역 || '';
  const income     = payload.income_percent ? `중위소득 ${payload.income_percent}%` : (payload.income || payload.연소득 || '');
  const family_type= payload.household_type || payload.가구유형 || payload.family_type || '';
  const employment = payload.employment_status || payload.고용상태 || payload.employment || '';
  const disability = payload.disability || payload.장애여부 || '없음';

  const cacheKey = JSON.stringify(payload);
  if (_searchCache[cacheKey]) return _searchCache[cacheKey];

  const dbSummary = POLICY_DB.map((p,i) =>
    `[${i}] ${p.서비스명} | ${p.서비스분야} | ${p.지원유형} | 대상: ${(p.지원대상||'').substring(0,80)} | 내용: ${(p.지원내용||'').substring(0,60)}`
  ).join('\n');

  const prompt = `당신은 한국 복지 정책 수급 가능성 분석 전문가입니다.

사용자 정보:
- 나이: ${age}
- 지역: ${region}
- 소득: ${income}
- 가구 유형: ${family_type}
- 취업 상태: ${employment}
- 장애 여부: ${disability}

복지 정책 목록:
${dbSummary}

위 정책들 중 이 사용자에게 가장 적합한 정책 5개를 선정하고, 각 정책의 수급 가능성을 분석하세요.

다음 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{
  "recommendation_cards": [
    {
      "policy_id": "인덱스번호를_slug으로",
      "서비스명": "정책명",
      "icon": "이모지",
      "subtitle": "한 줄 조건 요약",
      "benefit_label": "혜택 요약",
      "source_label": "기관 약칭",
      "수급확률": 85,
      "탈락사유": [{"icon":"⚠️","html":"<strong>주의:</strong> 설명"}],
      "해결방법": [{"icon":"✅","html":"<strong>1단계:</strong> 설명"},{"icon":"📎","html":"<strong>2단계:</strong> 설명"},{"icon":"🚀","html":"<strong>3단계:</strong> 설명"}],
      "우선순위": 1,
      "_css": {"card_class":"top","percent_class":"high","progress_color":"green","badge_class":"badge-green","badge_label":"✅ 조건 충족"}
    }
  ],
  "stats": {
    "해당정책수": 12,
    "평균확률": 80,
    "예상수혜액": "월 최대 50만원",
    "즉시신청가능": 3
  },
  "summary": "종합 요약 2~3문장"
}

수급확률 80 이상 → card_class: top, percent_class: high, progress_color: green, badge_label: ✅ 조건 충족
수급확률 60~79 → card_class: mid, percent_class: mid, progress_color: blue, badge_label: ⚡ 확인 필요
수급확률 60 미만 → card_class: low, percent_class: low, progress_color: orange, badge_label: ⚠️ 조건 부족`;

  const result = await callClaudeSearch(prompt);
  _searchCache[cacheKey] = { dashboard_data: result, query_id: Date.now().toString() };
  return _searchCache[cacheKey];
}

// ── 카테고리 목록 반환 ────────────────────────────────────────
function getLocalCategories() {
  const cats = [...new Set(POLICY_DB.map(p => p.서비스분야).filter(Boolean))].sort();
  return { categories: cats };
}

// ── API 베이스 설정 ───────────────────────────────────────────
const API_BASE = 'http://localhost:8000';
let _useBackend = null;

async function _checkBackend() {
  if (_useBackend !== null) return _useBackend;
  try {
    const r = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(1500) });
    _useBackend = r.ok;
  } catch { _useBackend = false; }
  return _useBackend;
}

// ── apiFetch: FastAPI 우선 → 폴백(내장 로직) ─────────────────
async function apiFetch(path, options = {}) {
  const body = options.body ? JSON.parse(options.body) : null;
  const useBackend = await _checkBackend();

  if (useBackend) {
    const res = await fetch(API_BASE + path, {
      method: options.method || 'GET',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...(options.body ? { body: options.body } : {}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail?.message || `서버 오류 ${res.status}`);
    }
    return res.json();
  }

  // ── 폴백: 내장 로직 ──
  if (path === '/categories' || path === '/search/categories') {
    return getLocalCategories();
  }
  if (path.startsWith('/search/keyword')) {
    const params = new URLSearchParams(path.split('?')[1] || '');
    const results = localKeywordSearch(
      params.get('keyword') || '', params.get('category') || '',
      params.get('support_type') || '', parseInt(params.get('limit') || '20')
    );
    return { results, count: results.length };
  }
  if (path.startsWith('/search/natural')) {
    const params = new URLSearchParams(path.split('?')[1] || '');
    const results = await localNaturalSearch(params.get('q') || '', parseInt(params.get('top_k') || '15'));
    return { results };
  }
  if (path === '/analyze') {
    return localAnalyze(body);
  }
  if (path.startsWith('/portfolio')) {
    return { items: _currentPortfolio };
  }
  throw new Error(`지원하지 않는 경로: ${path}`);
}

// ── 에러 토스트 ───────────────────────────────────────────────
function showToast(msg, type = 'error') {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
    background:${type === 'error' ? '#E74C3C' : '#2ECC71'};
    color:#fff;padding:12px 24px;border-radius:12px;font-size:14px;
    font-weight:600;z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,.2);
  `;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ── 입력 폼에서 사용자 데이터 수집 ──────────────────────────
function collectFormData() {
  const ageVal        = document.getElementById('sel-age')?.value        || '만 27세';
  const regionVal     = document.getElementById('sel-region')?.value     || '서울특별시';
  const incomeVal     = document.getElementById('sel-income')?.value     || '중위소득 50~60%';
  const familyVal     = document.getElementById('sel-family')?.value     || '1인 가구';
  const empVal        = document.getElementById('sel-employment')?.value || '미취업';
  const disabilityVal = document.getElementById('sel-disability')?.value || '없음';

  // ── 나이 파싱: "만 27세" / "만 65세 이상" → 숫자
  const ageMatch = ageVal.match(/\d+/);
  const age = ageMatch ? parseInt(ageMatch[0]) : 27;

  // ── 소득 파싱 → income_percent
  let income_percent = 55;
  const rangeMatch  = incomeVal.match(/(\d+)[~\-](\d+)/);
  const singleMatch = incomeVal.match(/(\d+)%\s*(이하|초과)/);
  if (rangeMatch) {
    income_percent = Math.round((parseInt(rangeMatch[1]) + parseInt(rangeMatch[2])) / 2);
  } else if (singleMatch) {
    income_percent = singleMatch[2] === '이하'
      ? Math.round(parseInt(singleMatch[1]) * 0.7)
      : parseInt(singleMatch[1]) + 10;
  }

  // ── 가구원수 추정
  const sizeMap = {
    '1인 가구':1, '2인 가구':2, '3인 가구':3, '4인 이상 가구':4,
    '한부모 가구':2, '다자녀 가구':4, '다문화 가구':3,
    '조손 가구':2, '노인 단독 가구':1,
  };
  const household_size = sizeMap[familyVal] || 1;

  // ── 취업상태 → scoring.py 호환
  const empMap = {
    '미취업':                     '구직자 (실업)',
    '취업자 (정규직)':             '취업자 (정규직)',
    '취업자 (비정규직/계약직)':    '취업자 (비정규직/계약직)',
    '자영업자':                    '자영업자',
    '구직자 (실업)':               '구직자 (실업)',
    '학생':                        '학생',
    '육아휴직 중':                 '육아휴직 중',
    '무직':                        '무직',
  };

  // ── 다문화가구 여부 (가구유형에서 자동 판단)
  const multicultural = familyVal === '다문화 가구';

  // ── scoring.py 6개 항목과 완전 일치하는 payload
  return {
    user_name:         document.querySelector('.avatar-name')?.textContent?.replace('님','') || '사용자',
    age,                                          // → 나이
    region:            regionVal,                 // → 거주지역
    income_percent,                               // → 연소득 (중위소득 % 환산)
    household_type:    familyVal,                 // → 가구유형
    household_size,                               // → 가구원수
    employment_status: empMap[empVal] || empVal,  // → 고용상태
    disability:        disabilityVal,             // → 장애여부 ← 새로 추가
    veteran:           false,
    multicultural,
    education_level:   '대졸',
    language:          'ko',
  };
}

// ── 대시보드 렌더링 ───────────────────────────────────────────
function renderDashboard(data) {
  // Claude API 응답 구조와 기존 구조 모두 호환
  const recommendation_cards = data.recommendation_cards || data.포트폴리오 || [];
  const stats = data.stats || data.대시보드통계 || {};
  const summary = data.summary || data.종합요약 || '';

  // 사용자 프로필 업데이트 (폼 값 기반)
  const ageVal    = document.getElementById('sel-age')?.value    || '';
  const regionVal = document.getElementById('sel-region')?.value || '';
  const familyVal = document.getElementById('sel-family')?.value || '';
  const empVal    = document.getElementById('sel-employment')?.value || '';
  const incomeVal = document.getElementById('sel-income')?.value || '';

  const profileH2 = document.querySelector('.profile-info h2');
  if (profileH2) profileH2.textContent = `나의 복지 분석 결과`;

  const profileP = document.querySelector('.profile-info p');
  const now = new Date(); const hm = `${now.getHours()}시 ${now.getMinutes()}분`;
  if (profileP) profileP.textContent = `마지막 업데이트: 오늘 ${hm} · ${regionVal}`;

  const tagsEl = document.querySelector('.profile-tags');
  if (tagsEl && ageVal) {
    tagsEl.innerHTML = [
      ageVal ? `📅 ${ageVal}` : '',
      regionVal ? `📍 ${regionVal}` : '',
      incomeVal ? `💰 ${incomeVal}` : '',
      familyVal ? `🏠 ${familyVal}` : '',
      empVal ? `👔 ${empVal}` : '',
    ].filter(Boolean).map(t => `<span class="profile-tag">${t}</span>`).join('');
  }

  // 통계 업데이트
  const statEl = (sel) => document.querySelector(sel);
  if (stats.해당정책수) {
    const valEls = document.querySelectorAll('.stat-item .val');
    if (valEls[0]) valEls[0].textContent = stats.해당정책수;
    if (valEls[1]) valEls[1].textContent = (stats.평균확률 || 0) + '%';
    if (valEls[2]) valEls[2].innerHTML = (stats.예상수혜액 || '-') + '<span style="font-size:14px">원</span>';
    if (valEls[3]) valEls[3].textContent = stats.즉시신청가능 || 0;
    const scoreNum = document.querySelector('.score-num');
    if (scoreNum) scoreNum.textContent = stats.평균확률 || 0;
  }

  // 정책 카드 목록
  const policyList = document.querySelector('.policy-list');
  if (policyList && recommendation_cards.length) {
    policyList.innerHTML = recommendation_cards.map(card => {
      const css = card._css || {};
      // 두 가지 필드명 모두 지원
      const pct      = card.수급확률 || card.eligibility_percent || 0;
      const name     = card.서비스명 || card.policy_name || '';
      const subtitle = card.subtitle || '';
      const benefit  = card.benefit_label || '';
      const source   = card.source_label || 'Gov24';
      const icon     = card.icon || '📋';
      const pid      = card.policy_id || '';
      const barColor = css.progress_color || 'blue';
      return `
        <div class="policy-card ${css.card_class || 'mid'}" onclick="showDetail('${escHtml(pid)}')">
          <div class="policy-top-row">
            <div class="policy-left">
              <div class="policy-icon ${css.icon_color || css.progress_color || 'blue'}">${icon}</div>
              <div class="policy-meta">
                <h4>${escHtml(name)}</h4>
                <p>${escHtml(subtitle)}</p>
                <div class="policy-badges">
                  <span class="badge ${css.badge_class || 'badge-blue'}">${css.badge_label || '확인 필요'}</span>
                  <span class="badge badge-blue">${escHtml(source)}</span>
                  <span class="badge badge-gray">${escHtml(benefit)}</span>
                </div>
              </div>
            </div>
            <div class="policy-percent">
              <div class="percent-num ${css.percent_class || 'mid'}">${pct}<span style="font-size:18px">%</span></div>
              <div class="percent-label">수급 확률</div>
            </div>
          </div>
          <div class="progress-row">
            <div class="progress-track">
              <div class="progress-fill ${barColor}" style="width:${pct}%"></div>
            </div>
            <div class="benefit-chip">${escHtml(benefit)}</div>
          </div>
          <div class="policy-action">상세 분석 보기 →</div>
        </div>`;
    }).join('');
  }

  // 포트폴리오 프리뷰 사이드바 업데이트 (있을 경우)
  const portTotal = document.querySelector('.portfolio-total .amount');
  if (portTotal && stats.예상수혜액) portTotal.textContent = stats.예상수혜액;

  // 종합요약이 있으면 표시
  if (summary) {
    const summaryEls = document.querySelectorAll('.insight-section-label, .cta-text p');
    summaryEls.forEach(el => { if (el && !el.closest('.inline-ad')) el.textContent = summary; });
  }
}

// ── 상세 분석 화면 렌더링 ─────────────────────────────────────
function renderDetail(detailData) {
  const { policy_header, issues, guides, summary_stats } = detailData;
  const pct   = policy_header.eligibility_percent;
  const color = policy_header.progress_color || (pct >= 80 ? 'green' : pct >= 60 ? 'blue' : 'orange');

  // 정책명
  document.getElementById('detail-policy-name').textContent = policy_header.policy_name;

  // 아이콘
  const iconEl = document.querySelector('#screen-detail .detail-icon');
  if (iconEl && policy_header.icon) iconEl.textContent = policy_header.icon;

  // 수급 확률 숫자 + % 색상
  const pctEl = document.getElementById('detail-pct');
  if (pctEl) pctEl.textContent = pct;
  const pctSign = document.querySelector('#screen-detail .detail-prob span[style]');
  const pctColor = color === 'green' ? 'var(--green)' : color === 'blue' ? 'var(--blue)' : 'var(--orange)';
  if (pctSign) pctSign.style.color = pctColor;

  // 진행바
  const bar = document.getElementById('detail-bar');
  if (bar) {
    bar.className   = `progress-fill ${color}`;
    bar.style.width = pct + '%';
    // 애니메이션
    bar.style.width = '0';
    requestAnimationFrame(() => { setTimeout(() => { bar.style.width = pct + '%'; }, 60); });
  }

  // issue-item 렌더링
  const issueSection = document.getElementById('detail-issue-section');
  if (issueSection) {
    const noIssue = !issues || issues.length === 0 ||
      (issues.length === 1 && (issues[0].icon === '✅' ||
        (issues[0].html || '').includes('탈락 요인 없음') ||
        (issues[0].html || '').includes('분석 전')));
    issueSection.innerHTML = `
      <div class="analysis-label">❌ 탈락 예상 이유</div>
      ${noIssue
        ? `<div class="issue-item"><span class="icon">✅</span><p><strong>탈락 사유 없음</strong> — 조건 충족</p></div>`
        : issues.map(iss => {
            const icon = iss.icon || '⚠️';
            const text = typeof iss.html === 'string' ? iss.html : (iss.html?.html || JSON.stringify(iss.html));
            return `<div class="issue-item"><span class="icon">${icon}</span><p>${text}</p></div>`;
          }).join('')
      }
    `;
  }

  // guide-item 렌더링
  const guideSection = document.getElementById('detail-guide-section');
  if (guideSection) {
    guideSection.innerHTML = `
      <div class="analysis-label">💡 해결 방법 &amp; 행동 가이드</div>
      ${guides.map(g => {
        const icon = g.icon || '✅';
        const text = typeof g.html === 'string' ? g.html : (g.html?.html || JSON.stringify(g.html));
        return `<div class="guide-item"><span class="icon">${icon}</span><p>${text}</p></div>`;
      }).join('')}
    `;
  }

  // 사이드바 통계 (detail 화면)
  const detailStats = document.querySelectorAll('#screen-detail .stat-item .val');
  if (detailStats.length >= 4) {
    detailStats[0].textContent  = pct + '%';
    detailStats[0].className    = `val ${color}`;
    detailStats[1].textContent  = summary_stats.benefit_label;
    detailStats[2].textContent  = summary_stats.processing_period_label;
    detailStats[3].textContent  = summary_stats.issue_count + '건';
  }

  // AI 핵심요약 박스 로드
  renderAiSummary(detailData);
}

// ── 원문 발췌 박스 렌더링 ────────────────────────────────────
async function renderAiSummary(detailData) {
  const box = document.getElementById('ai-summary-content');
  if (!box) return;

  const personalSummary = detailData.개인요약 || detailData.personal_summary || '';
  const policyName = detailData.policy_header?.policy_name || '';
  const raw = POLICY_DB.find(p => p.서비스명 === policyName) || {};
  const rawTarget  = raw.지원대상   || '';
  const rawContent = raw.지원내용   || '';
  const rawMethod  = raw.신청방법   || '';
  const rawPhone   = raw.전화문의   || '';
  const rawUrl     = raw.상세조회url || '';

  if (!personalSummary && !rawTarget && !rawContent && !rawMethod) {
    box.innerHTML = `<div class="ai-summary-row"><span class="ai-summary-icon">📌</span><span style="font-size:12px;color:var(--gray-500)">원문 데이터가 없습니다. 공식 페이지에서 확인하세요.</span></div>`;
    return;
  }

  const md2html = s => (s||'').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  const rows = [
    rawTarget  ? { label:'📌 지원 대상', value: rawTarget.substring(0,120)  + (rawTarget.length>120?'…':'')  } : null,
    rawContent ? { label:'💰 지원 내용', value: rawContent.substring(0,120) + (rawContent.length>120?'…':'') } : null,
    rawMethod  ? { label:'📋 신청 방법', value: rawMethod.substring(0,80)   + (rawMethod.length>80?'…':'')   } : null,
  ].filter(Boolean);

  const personalHtml = personalSummary
    ? `<div class="ai-summary-row" style="border-bottom:1px solid rgba(245,195,60,.15);margin-bottom:8px;padding-bottom:8px;">
        <span class="ai-summary-icon">📄</span>
        <div style="flex:1;font-size:13.5px;font-weight:500;line-height:1.65;color:#2D2200">${md2html(personalSummary)}</div>
      </div>`
    : '';

  box.innerHTML = personalHtml + rows.map(r =>
    `<div class="ai-summary-row">
      <span class="ai-summary-icon" style="font-size:13px;min-width:16px;">▍</span>
      <div style="flex:1;">
        <div class="ai-summary-source-label">${r.label}</div>
        <div class="ai-summary-excerpt">${md2html(r.value)}</div>
      </div>
    </div>`
  ).join('') + (rawPhone || rawUrl ? `
    <div style="margin-top:10px;display:flex;gap:12px;flex-wrap:wrap;padding-top:8px;border-top:1px solid rgba(245,195,60,.2)">
      ${rawPhone ? `<span style="font-size:11px;color:var(--gray-500)">📞 ${rawPhone}</span>` : ''}
      ${rawUrl   ? `<a href="${rawUrl}" target="_blank" style="font-size:11px;color:var(--blue);text-decoration:none;font-weight:600">🔗 공식 페이지 →</a>` : ''}
    </div>` : '');
}

// ── 정적 정책 데이터 (백엔드 없이도 상세 보기 동작) ─────────
const _STATIC_DETAIL = {
  '청년-월세-한시-특별지원': {
    policy_header: {
      policy_name: '청년 월세 한시 특별지원',
      eligibility_percent: 92,
      progress_color: 'green',
      icon: '🏠',
    },
    issues: [
      { icon: '⚠️', html: '<strong>주민등록 전입 미완료:</strong> 현재 거주지 주민등록이 신청 주소와 일치하지 않을 수 있습니다. 서류 심사 시 탈락 요인이 될 수 있습니다.' },
      { icon: '📋', html: '<strong>임대차 계약서 미비:</strong> 월세 계약 기간이 남은 계약서 원본 및 확정일자가 필요합니다.' },
    ],
    guides: [
      { icon: '✅', html: '<strong>1단계: 전입신고 완료하기</strong> — 거주지 주민센터를 방문하여 현 주소로 전입신고를 진행하세요. 처리 기간: 당일' },
      { icon: '📎', html: '<strong>2단계: 임대차 계약서 확인</strong> — 계약서에 확정일자 도장이 찍혀 있는지 확인하고, 없다면 주민센터 방문 시 동시에 신청하세요.' },
      { icon: '🚀', html: '<strong>3단계: 복지로에서 온라인 신청</strong> — 위 서류 준비 후 <a href="https://bokjiro.go.kr" target="_blank" style="color:var(--blue)">bokjiro.go.kr</a>에서 신청서를 제출하세요. 30일 이내 결과를 통보받습니다.' },
    ],
    summary_stats: { benefit_label: '연 240만원', processing_period_label: '1개월', issue_count: 2, source_label: '국토부' },
  },
  '국민내일배움카드': {
    policy_header: { policy_name: '국민내일배움카드', eligibility_percent: 85, progress_color: 'green', icon: '📚' },
    issues: [
      { icon: '⚠️', html: '<strong>재직자 소득 기준 확인 필요:</strong> 연 소득 5,000만원 초과 대기업 재직자는 지원 대상에서 제외됩니다.' },
      { icon: '📋', html: '<strong>훈련 기관 선택 필요:</strong> 지정된 직업훈련기관에서만 카드 사용이 가능합니다. 사전 확인 후 신청하세요.' },
    ],
    guides: [
      { icon: '✅', html: '<strong>1단계: 고용24 회원가입</strong> — <a href="https://www.work24.go.kr" target="_blank" style="color:var(--blue)">work24.go.kr</a>에서 회원가입 후 신청 페이지로 이동하세요.' },
      { icon: '📎', html: '<strong>2단계: 수강 희망 과정 선택</strong> — 직업훈련포털에서 수강 희망 훈련과정을 미리 검색해두세요.' },
      { icon: '🚀', html: '<strong>3단계: 카드 신청 및 발급</strong> — 신청 승인 후 카드 수령까지 약 2주 소요됩니다. 국민은행 또는 우리은행으로 발급됩니다.' },
    ],
    summary_stats: { benefit_label: '최대 500만원', processing_period_label: '2주', issue_count: 2, source_label: '고용부' },
  },
  '청년-취업성공패키지': {
    policy_header: { policy_name: '청년도약계좌', eligibility_percent: 78, progress_color: 'blue', icon: '💼' },
    issues: [
      { icon: '⚠️', html: '<strong>소득 기준 재확인 필요:</strong> 개인소득 6,000만원 이하, 가구소득 중위 180% 이하 조건을 모두 충족해야 합니다.' },
      { icon: '🔎', html: '<strong>5년 유지 의무:</strong> 중도 해지 시 정부기여금 및 비과세 혜택이 소멸됩니다. 장기 납입 계획 수립이 필요합니다.' },
    ],
    guides: [
      { icon: '✅', html: '<strong>1단계: 가입 자격 셀프 체크</strong> — 소득 기준(개인·가구 모두)과 나이(만 19~34세) 조건을 사전에 확인하세요.' },
      { icon: '📎', html: '<strong>2단계: 은행 앱에서 신청</strong> — 취급 은행(국민·신한·하나·우리 등) 앱에서 비대면으로 신청 가능합니다.' },
      { icon: '🚀', html: '<strong>3단계: 매월 40~70만원 납입</strong> — 월 최대 70만원 납입 시 정부기여금 최대 6%를 추가로 받을 수 있습니다.' },
    ],
    summary_stats: { benefit_label: '최대 5,000만원', processing_period_label: '5년 만기', issue_count: 2, source_label: '금융위' },
  },
  '청년-마음건강-지원사업': {
    policy_header: { policy_name: '청년 마음건강 지원사업', eligibility_percent: 74, progress_color: 'blue', icon: '🏥' },
    issues: [
      { icon: '⚠️', html: '<strong>지역별 바우처 공급량 제한:</strong> 거주 지역에 따라 제공 가능한 상담사 및 기관 수가 다릅니다. 조기 신청을 권장합니다.' },
      { icon: '📌', html: '<strong>연 10회 한도:</strong> 회기당 50분 기준이며, 잔여 회기는 다음 연도로 이월되지 않습니다.' },
    ],
    guides: [
      { icon: '✅', html: '<strong>1단계: 거주지 주민센터 방문 신청</strong> — 신분증 지참 후 복지 담당자에게 청년 마음건강 바우처 신청 의사를 밝히세요.' },
      { icon: '📎', html: '<strong>2단계: 상담 기관 선택</strong> — 정신건강복지센터 또는 지정 민간 상담 기관 중 선택 가능합니다.' },
      { icon: '🚀', html: '<strong>3단계: 상담 예약 및 이용</strong> — 바우처 카드 수령 후 지정 기관에서 상담 예약을 진행하세요. 본인부담금은 회당 3,000원입니다.' },
    ],
    summary_stats: { benefit_label: '연 80만원 상당', processing_period_label: '상시', issue_count: 2, source_label: '복지부' },
  },
  '청년창업사관학교': {
    policy_header: { policy_name: '청년창업사관학교', eligibility_percent: 41, progress_color: 'orange', icon: '🚀' },
    issues: [
      { icon: '❗', html: '<strong>사업계획서 준비 미흡:</strong> 서류 심사 + 발표 심사 2단계로 진행되며, 구체적인 매출 계획과 시장 분석이 필수입니다.' },
      { icon: '⚠️', html: '<strong>창업 아이템 구체성 부족:</strong> 단순 아이디어 수준이 아닌, MVP(최소 기능 제품) 또는 프로토타입이 있을 경우 합격률이 크게 높아집니다.' },
      { icon: '🔎', html: '<strong>경쟁률 높음:</strong> 연간 선발 인원이 제한되어 있어 평균 경쟁률이 5:1 이상입니다.' },
    ],
    guides: [
      { icon: '✅', html: '<strong>1단계: 창업 아이템 구체화</strong> — 문제 정의 → 솔루션 → 목표 시장 → 수익 모델 순서로 사업계획서의 뼈대를 작성하세요.' },
      { icon: '📎', html: '<strong>2단계: K-스타트업 포털에서 공고 확인</strong> — <a href="https://www.k-startup.go.kr" target="_blank" style="color:var(--blue)">k-startup.go.kr</a>에서 모집 일정과 지원 자격을 확인하세요.' },
      { icon: '🚀', html: '<strong>3단계: 서류·면접 준비</strong> — 사전에 창업진흥원 무료 컨설팅(창업 교육 프로그램)을 받으면 합격률이 올라갑니다.' },
    ],
    summary_stats: { benefit_label: '최대 1억원', processing_period_label: '1년', issue_count: 3, source_label: '중기부' },
  },
};

// ── showDetail: 캐시 → POLICY_DB → 정적 fallback 순서 ────────
async function showDetail(policyId) {
  const _onAnalysisPage = (location.pathname.split('/').pop() || 'index.html') === 'analysis.html';
  if (!_onAnalysisPage) {
    // 다른 페이지에서 호출: policyId 저장 후 analysis.html로 이동
    try { localStorage.setItem('benefic_detail_id', policyId); } catch(e) {}
    showTab('detail');
    return; // analysis.html의 load 핸들러가 showDetail을 재호출함
  }
  // analysis.html에서 직접 호출된 경우: 이동 없이 바로 렌더링

  // 1) AI 분석 후 _currentPortfolio 캐시 우선
  const card = _currentPortfolio.find(c => c.policy_id === policyId);
  if (card) {
    const pct   = card.수급확률 || card.eligibility_percent || 60;
    const css   = card._css || {};
    const color = css.progress_color || (pct>=80?'green':pct>=60?'blue':'orange');
    renderDetail({
      policy_header: {
        policy_name:         card.서비스명 || card.policy_name || policyId,
        eligibility_percent: pct,
        progress_color:      color,
        icon:                card.icon || '📋',
        percent_class:       css.percent_class || 'mid',
        badge_label:         css.badge_label || '',
        badge_class:         css.badge_class || 'badge-blue',
        subtitle:            card.subtitle || '',
      },
      개인요약: card.개인요약 || card.personal_summary || '',
      issues: (card.탈락사유 !== undefined ? card.탈락사유 : null) || card.issues || _buildIssuesFromDB(card.서비스명 || card.policy_name),
      guides: card.해결방법 || card.guides || _buildGuidesFromDB(card.서비스명 || card.policy_name),
      summary_stats: {
        benefit_label:           card.benefit_label || '-',
        processing_period_label: '1~2개월',
        issue_count:             (card.탈락사유||[]).length || 1,
        source_label:            card.source_label || 'Gov24',
      },
    });
    return;
  }

  // 2) _STATIC_DETAIL에 있으면 사용
  if (_STATIC_DETAIL[policyId]) {
    renderDetail(_STATIC_DETAIL[policyId]);
    return;
  }

  // 3) POLICY_DB 기반 동적 생성
  renderDetail(_buildDetailFromDB(policyId));
}

// POLICY_DB slug 매칭
function _findPolicyBySlug(policyId) {
  return POLICY_DB.find(p => {
    const slug = (p.서비스명||'').replace(/[^\w가-힣]/g,'-').replace(/-+/g,'-').replace(/^-|-$/g,'').toLowerCase();
    return slug === policyId || p.서비스명 === policyId;
  });
}

// POLICY_DB → issue-item 생성
function _buildIssuesFromDB(policyName) {
  const p = POLICY_DB.find(r => r.서비스명 === policyName);
  if (!p) return [{ icon:'ℹ️', html:'<strong>분석 전:</strong> 상단 분석 버튼을 눌러 AI 수급 가능성 분석을 실행하세요.' }];
  const issues = [];
  if (p.선정기준) issues.push({ icon:'📋', html:`<strong>선정 기준:</strong> ${p.선정기준.substring(0,100)}${p.선정기준.length>100?'…':''}` });
  if (p.지원대상) issues.push({ icon:'👤', html:`<strong>지원 대상:</strong> ${p.지원대상.substring(0,100)}${p.지원대상.length>100?'…':''}` });
  if (!issues.length) issues.push({ icon:'ℹ️', html:'<strong>분석 전:</strong> 상단 분석 버튼을 눌러 AI 수급 가능성 분석을 실행하세요.' });
  return issues;
}

// POLICY_DB → guide-item 생성
function _buildGuidesFromDB(policyName) {
  const p = POLICY_DB.find(r => r.서비스명 === policyName);
  if (!p) return [
    { icon:'✅', html:'<strong>1단계: AI 분석 실행</strong> — 상단 "수급 가능성 AI 분석 시작하기" 버튼을 누르세요.' },
    { icon:'🔗', html:'<strong>2단계: 복지로 신청</strong> — <a href="https://www.bokjiro.go.kr" target="_blank" style="color:var(--blue)">bokjiro.go.kr</a>에서 신청하세요.' },
  ];
  const guides = [];
  if (p.신청방법) guides.push({ icon:'📋', html:`<strong>1단계: 신청 방법</strong> — ${p.신청방법}` });
  if (p.접수기관) guides.push({ icon:'🏛️', html:`<strong>2단계: 접수 기관</strong> — ${p.접수기관}` });
  if (p.신청기한) guides.push({ icon:'📅', html:`<strong>신청 기한</strong> — ${p.신청기한}` });
  const url = p.상세조회url || 'https://www.bokjiro.go.kr';
  guides.push({ icon:'🚀', html:`<strong>${guides.length+1}단계: 온라인 신청</strong> — <a href="${url}" target="_blank" style="color:var(--blue)">${url.replace('https://','').split('/')[0]}</a>에서 신청 ${p.전화문의?'/ 문의: '+p.전화문의:''}` });
  return guides;
}

// POLICY_DB → 전체 detailData 생성
function _buildDetailFromDB(policyId) {
  const p = _findPolicyBySlug(policyId);
  const policyName = p?.서비스명 || policyId;
  const iconMap = {'현금':'💰','이용권':'🎫','서비스':'🛎️','주거':'🏠','고용':'💼','교육':'🎓','의료':'🏥','노인':'👴','장애인':'♿','가족':'👨‍👩‍👧','기초생활':'🛡️','금융':'🏦','창업':'🚀','보건':'💊'};
  const icon = p ? (iconMap[p.지원유형]||iconMap[p.서비스분야]||'📋') : '📋';
  let benefitLabel = '-';
  if (p?.지원내용) {
    const m = p.지원내용.match(/(최대|월|연)?\s*([\d,]+)\s*만\s*원/);
    if (m) benefitLabel = `${m[1]?m[1]+' ':''}${m[2]}만원`;
  }
  return {
    policy_header: { policy_name: policyName, eligibility_percent: 60, progress_color: 'blue', icon,
      percent_class: 'mid', badge_label: '⚡ 확인 필요', badge_class: 'badge-blue',
      subtitle: p ? `${p.서비스분야||''} · ${p.지원유형||''}`.replace(/^ · | · $/,'') : '' },
    issues:  _buildIssuesFromDB(policyName),
    guides:  _buildGuidesFromDB(policyName),
    summary_stats: { benefit_label: benefitLabel, processing_period_label: '1~2개월', issue_count: 1,
      source_label: p ? (p.소관기관명||'Gov24').substring(0,6) : 'Gov24' },
  };
}

function _makeFallbackDetail(policyId) {
  return _buildDetailFromDB(policyId);
}

// ── 포트폴리오 화면 렌더링 ────────────────────────────────────
async function loadPortfolio() {
  _renderPortfolioStatic();
}

function _renderPortfolioData(data) {
  const hero = data.portfolio_hero;

  // hero 총 수혜액
  const bigNum = document.querySelector('.portfolio-hero .big-num');
  if (bigNum) bigNum.textContent = hero.total_expected_benefit_label;

  // hero 설명 p 태그 (두 번째 p)
  const heroPs = document.querySelectorAll('.portfolio-hero p');
  if (heroPs.length >= 2) heroPs[1].textContent = hero.portfolio_basis_label;
  else if (heroPs.length === 1) heroPs[0].textContent = hero.portfolio_basis_label;

  // hero 배지: 즉시 신청 N건 / 조건 보완 후 M건
  const heroBadges = document.querySelectorAll('.portfolio-hero span');
  if (heroBadges.length >= 2) {
    heroBadges[0].textContent = `✅ 즉시 신청 가능 ${hero.ready_count}건`;
    heroBadges[1].textContent = `⚡ 조건 보완 후 ${hero.conditional_count}건`;
  }

  // port-grid 카드 렌더링
  const portGrid = document.querySelector('.port-grid');
  if (portGrid) {
    const statusBadge = s =>
      s === 'ready'       ? '<span class="badge badge-green">즉시 신청</span>' :
      s === 'conditional' ? '<span class="badge badge-blue">조건 확인 필요</span>' :
                            '<span class="badge badge-orange">조건 부족</span>';

    const cards = data.portfolio_items.map(item => `
      <div class="port-grid-card" onclick="showDetail('${item.policy_id}')" style="cursor:pointer;">
        <div class="icon">${item.icon}</div>
        <h4>${item.policy_name}</h4>
        <div class="amount">${item.expected_benefit_label}</div>
        <div class="period">${item.benefit_period_label}</div>
        <div style="margin-top:10px;">${statusBadge(item.status)}</div>
      </div>`).join('');

    // 마지막에 "정책 더 추가하기" 카드 유지
    portGrid.innerHTML = cards + `
      <div class="port-grid-card" style="background:var(--gray-50);border-style:dashed;cursor:pointer;" onclick="showTab('dashboard')">
        <div class="icon">➕</div>
        <h4 style="color:var(--gray-500);">정책 더 보기</h4>
        <div class="amount" style="color:var(--gray-300);font-size:14px">대시보드로 이동</div>
        <div class="period" style="color:var(--gray-400)">전체 목록 확인</div>
      </div>`;
  }

  // CTA 섹션
  const ctaH3 = document.querySelector('.cta-text h3');
  const ctaP  = document.querySelector('.cta-text p');
  if (ctaH3) ctaH3.textContent = data.portfolio_cta.headline;
  if (ctaP)  ctaP.textContent  = data.portfolio_cta.description;
}

// 백엔드 없을 때 하드코딩 정적 화면 유지 (기존 HTML 그대로)
function _renderPortfolioStatic() {
  // runAnalysis 후 _currentPortfolio 캐시가 있으면 그걸로 렌더링
  if (_currentPortfolio && _currentPortfolio.length > 0) {
    const statusBadge = s =>
      s === 'ready'       ? '<span class="badge badge-green">즉시 신청</span>' :
      s === 'conditional' ? '<span class="badge badge-blue">조건 확인 필요</span>' :
                            '<span class="badge badge-orange">조건 부족</span>';

    const portGrid = document.querySelector('.port-grid');
    if (portGrid) {
      const cards = _currentPortfolio.map(card => {
        const score  = card.수급확률 || card.eligibility_percent || 0;
        const name   = card.서비스명 || card.policy_name || '';
        const status = score >= 80 ? 'ready' : score >= 60 ? 'conditional' : 'blocked';
        return `
          <div class="port-grid-card" onclick="showDetail('${card.policy_id}')" style="cursor:pointer;">
            <div class="icon">${card.icon || '📋'}</div>
            <h4>${escHtml(name)}</h4>
            <div class="amount">${escHtml(card.benefit_label || '-')}</div>
            <div class="period">${escHtml(card.subtitle || '-')}</div>
            <div style="margin-top:10px;">${statusBadge(status)}</div>
          </div>`;
      }).join('');
      portGrid.innerHTML = cards + `
        <div class="port-grid-card" style="background:var(--gray-50);border-style:dashed;cursor:pointer;" onclick="showTab('dashboard')">
          <div class="icon">➕</div>
          <h4 style="color:var(--gray-500);">정책 더 보기</h4>
          <div class="amount" style="color:var(--gray-300);font-size:14px">대시보드로 이동</div>
          <div class="period" style="color:var(--gray-400)">전체 목록 확인</div>
        </div>`;
    }
  }
  // 정적 HTML 카드는 그대로 두고 아무것도 안 함
}

// ── runAnalysis: API 호출로 교체 ─────────────────────────────
async function runAnalysis() {
  const overlay = document.getElementById('aiLoading');
  overlay.classList.add('show');

  try {
    const payload = collectFormData();
    const data    = await apiFetch('/analyze', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    _currentQueryId  = data.query_id;
    // FastAPI: data.cards / 폴백: data.dashboard_data.recommendation_cards
    const rawCards = data.cards || data.dashboard_data?.recommendation_cards || [];

    // policy_id를 서비스명 기반 슬러그로 강제 정규화 (AI가 임의 ID 반환해도 일치 보장)
    _currentPortfolio = rawCards.map(card => {
      const name = card.서비스명 || card.policy_name || '';
      const slug = name.replace(/[^\w가-힣]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '').toLowerCase();
      if (!card._css) card._css = _scoreToCSS(card.수급확률 || card.eligibility_percent || 60);
      return { ...card, policy_id: slug || card.policy_id };
    });
    _savePortfolio(_currentPortfolio); // 페이지 이동 후에도 유지

    renderDashboard(data.dashboard_data);

    // 진행바 재애니메이션
    document.querySelectorAll('.progress-fill').forEach(bar => {
      const w = bar.style.width;
      bar.style.width = '0';
      setTimeout(() => { bar.style.width = w; }, 100);
    });

    showToast('분석이 완료되었습니다! ✅', 'success');

  } catch (e) {
    showToast('분석 실패: ' + e.message);
    console.error('runAnalysis error:', e);
  } finally {
    overlay.classList.remove('show');
  }
}



function toggleCheck(el) {
  el.classList.toggle('done');
  const box = el.querySelector('.check-box');
  box.textContent = el.classList.contains('done') ? '✓' : '';
}

// ══════════════════════════════════════════════════════════════
// 검색 모듈 — DB 연동 버전
// ══════════════════════════════════════════════════════════════

let _searchLoading     = false;
let _dashSearchLoading = false;
const _perPage         = 20;

function initSearch() {
  document.getElementById('search-results').innerHTML   = '';
  document.getElementById('search-status').textContent = '';
  const pag = document.getElementById('search-pagination');
  if (pag) pag.style.display = 'none';

  const qw = document.getElementById('quick-tags');
  if (qw && !qw.dataset.init) {
    qw.dataset.init = '1';
    ['청년 월세','기초생활','실업급여','국민내일배움카드','노인 일자리','아동수당','장애인 지원','한부모 가족'].forEach(t => {
      const b = document.createElement('button');
      b.textContent = t;
      b.style.cssText = 'background:var(--gray-100);border:none;border-radius:20px;padding:4px 12px;font-size:12px;font-weight:600;color:var(--gray-700);cursor:pointer;font-family:inherit;transition:all .15s';
      b.onmouseover = () => b.style.background = 'var(--blue-light)';
      b.onmouseout  = () => b.style.background = 'var(--gray-100)';
      b.onclick = () => { document.getElementById('search-input').value = t; doSearch(); };
      qw.appendChild(b);
    });
  }

  // 대시보드에서 검색어를 넘겨받은 경우 자동 실행
  try {
    const pending = sessionStorage.getItem('benefic_search_query');
    if (pending) {
      sessionStorage.removeItem('benefic_search_query');
      const searchInput = document.getElementById('search-input');
      if (searchInput) {
        searchInput.value = pending;
        doSearch();
        return;
      }
    }
  } catch(e) {}

  loadBrowse(1);
}

function initDashSearch() {}

async function loadBrowse(page = 1) {
  const wrap  = document.getElementById('search-browse-wrap');
  const list  = document.getElementById('browse-list');
  const pag   = document.getElementById('browse-pagination');
  const badge = document.getElementById('browse-total-badge');
  if (!wrap || !list) return;
  wrap.style.display = 'block';
  list.innerHTML = _loadingHTML('정책 목록을 불러오는 중...');
  try {
    const useBackend = await _checkBackend();
    let results = [], total = 0, totalPages = 1;
    if (useBackend) {
      const data = await apiFetch(`/browse?page=${page}&per_page=${_perPage}`);
      results = data.results||[]; total = data.total||0; totalPages = data.total_pages||1;
    } else {
      total = POLICY_DB.length; totalPages = Math.ceil(total/_perPage);
      results = POLICY_DB.slice((page-1)*_perPage, page*_perPage);
    }
    if (badge) badge.textContent = `(총 ${total.toLocaleString()}건)`;
    list.innerHTML = results.length ? results.map(_renderPolicyCard).join('') : _emptyHTML('정책이 없습니다.');
    if (pag) pag.innerHTML = _paginationHTML(page, totalPages, 'loadBrowse');
  } catch(e) {
    list.innerHTML = _errorHTML('목록 로드 실패: ' + e.message);
  }
}

async function doSearch(page = 1) {
  if (_searchLoading && page === 1) return;
  const q = (document.getElementById('search-input')?.value || '').trim();
  if (!q) {
    document.getElementById('search-results').innerHTML   = '';
    document.getElementById('search-status').textContent = '';
    document.getElementById('search-pagination').style.display = 'none';
    document.getElementById('search-browse-wrap').style.display = 'block';
    return;
  }
  _searchLoading = true;
  document.getElementById('search-browse-wrap').style.display = 'none';
  document.getElementById('search-status').textContent = '검색 중…';
  document.getElementById('search-results').innerHTML  = _loadingHTML('DB에서 검색 중...');
  document.getElementById('search-pagination').style.display = 'none';

  const isNatural = (q.length >= 10 && /\s/.test(q)) ||
                    /싶어|하고 싶|받고|알려|찾아|뭐가|어떤|어디서/.test(q);
  try {
    let results = [], statusMsg = '', total = 0, totalPages = 1;
    const useBackend = await _checkBackend();
    if (isNatural) {
      document.getElementById('search-status').textContent = '🤖 AI 분석 중…';
      let all = useBackend
        ? (await apiFetch('/search/natural?' + new URLSearchParams({q, top_k:100}))).results||[]
        : await localNaturalSearch(q, 100);
      total = all.length; totalPages = Math.ceil(total/_perPage)||1;
      results = all.slice((page-1)*_perPage, page*_perPage);
      statusMsg = `🤖 AI 검색 결과 ${total}건`;
    } else {
      if (useBackend) {
        const p = new URLSearchParams({keyword:q, limit:String(_perPage), offset:String((page-1)*_perPage)});
        const data = await apiFetch('/search/keyword?'+p.toString());
        results = data.results||[]; total = data.count||results.length;
        totalPages = Math.ceil(total/_perPage)||1; statusMsg = `DB 검색 결과 ${total}건`;
      } else {
        const all = localKeywordSearch(q,'','',500);
        total = all.length; totalPages = Math.ceil(total/_perPage)||1;
        results = all.slice((page-1)*_perPage, page*_perPage); statusMsg = `검색 결과 ${total}건`;
      }
      if (results.length < 5 && page === 1) {
        document.getElementById('search-status').textContent = '🤖 AI 보완 검색 중…';
        const extras = useBackend
          ? (await apiFetch('/search/natural?'+new URLSearchParams({q,top_k:20}))).results||[]
          : await localNaturalSearch(q, 20);
        const names = new Set(results.map(r=>r['서비스명']||r.서비스명));
        results = [...results, ...extras.filter(r=>!names.has(r['서비스명']||r.서비스명))];
        total = results.length; totalPages = 1;
        statusMsg = `검색 결과 ${total}건 (AI 보완 포함)`;
      }
    }
    document.getElementById('search-status').textContent = statusMsg;
    renderSearchResults(results);
    const pag = document.getElementById('search-pagination');
    if (pag && totalPages > 1) { pag.style.display='block'; pag.innerHTML=_paginationHTML(page,totalPages,'doSearch'); }
  } catch(e) {
    showToast('검색 오류: ' + e.message);
    document.getElementById('search-status').textContent = '';
    document.getElementById('search-results').innerHTML = _errorHTML(e.message);
  } finally { _searchLoading = false; }
}

async function doDashSearch() {
  const q = (document.getElementById('dash-search-input')?.value || '').trim();
  if (!q) { showToast('검색어를 입력하세요.'); return; }

  // 검색어를 sessionStorage에 저장한 뒤 search.html로 이동
  // (페이지 이동 후 main.js가 재실행되면서 아래 initSearch()가 이를 감지해 자동 검색)
  try { sessionStorage.setItem('benefic_search_query', q); } catch(e) {}
  window.location.href = 'search.html';
}

function _renderPolicyCard(p) {
  const name    = escHtml(p['서비스명']    ||p.서비스명    ||'-');
  const field   = escHtml(p['서비스분야']  ||p.서비스분야  ||'');
  const stype   = escHtml(p['지원유형']    ||p.지원유형    ||'');
  const org     = escHtml((p['소관기관명'] ||p.소관기관명  ||'Gov24').substring(0,14));
  const ddline  = escHtml(p['신청기한']    ||p.신청기한    ||'');
  const target  = p['지원대상']    ||p.지원대상    ||'';
  const content = p['지원내용']    ||p.지원내용    ||'';
  const tel     = escHtml(p['전화문의']    ||p.전화문의    ||'');
  const url     = escHtml(p['상세조회url'] ||p.상세조회url  ||'');
  const scorePct = p.score!==undefined ? Math.round(p.score*100) : null;
  const iconMap  = {'현금':'💰','이용권':'🎫','서비스':'🛎️','주거':'🏠','고용':'💼','교육':'🎓','의료':'🏥','노인':'👴','장애인':'♿','가족':'👨‍👩‍👧','기초생활':'🛡️','금융':'🏦','창업':'🚀','보건':'💊'};
  const icon = iconMap[stype]||iconMap[field]||'📋';
  return `<div class="policy-card mid" style="margin-bottom:12px">
    <div class="policy-top-row">
      <div class="policy-left">
        <div class="policy-icon blue">${icon}</div>
        <div class="policy-meta">
          <h4>${name}</h4>
          <p>${field}${field&&stype?' · ':''}${stype}</p>
          <div class="policy-badges">
            <span class="badge badge-blue">${org}</span>
            ${ddline?`<span class="badge badge-gray">기한: ${ddline}</span>`:''}
            ${scorePct!==null?`<span class="badge badge-green">유사도 ${scorePct}%</span>`:''}
          </div>
        </div>
      </div>
    </div>
    ${target?`<p style="font-size:12px;color:var(--gray-500);margin-top:10px;padding-top:10px;border-top:1px solid var(--gray-100);line-height:1.6">${escHtml(target.substring(0,140))}${target.length>140?'…':''}</p>`:''}
    ${content?`<p style="font-size:12px;color:var(--blue);margin-top:6px;font-weight:600">💰 ${escHtml(content.substring(0,100))}${content.length>100?'…':''}</p>`:''}
    <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      ${tel?`<span style="font-size:11px;color:var(--gray-500)">📞 ${tel}</span>`:''}
      ${url?`<a href="${url}" target="_blank" style="font-size:11px;color:var(--blue);text-decoration:none;font-weight:600;margin-left:auto">🔗 상세 보기 →</a>`:''}
    </div>
  </div>`;
}

function renderSearchResults(results) {
  const el = document.getElementById('search-results');
  if (!results||!results.length) { el.innerHTML=_emptyHTML('검색 결과가 없습니다'); return; }
  el.innerHTML = results.map(_renderPolicyCard).join('');
}

function _loadingHTML(msg){return`<div style="text-align:center;padding:40px 20px;color:var(--gray-500)"><div style="font-size:28px;margin-bottom:10px">⏳</div><p style="font-size:14px;font-weight:600">${msg}</p></div>`;}
function _emptyHTML(msg){return`<div style="text-align:center;padding:60px 20px;color:var(--gray-500)"><div style="font-size:40px;margin-bottom:12px">🔎</div><p style="font-size:15px;font-weight:600;margin-bottom:6px">${msg}</p><p style="font-size:13px">다른 키워드나 표현을 사용해보세요.</p></div>`;}
function _errorHTML(msg){return`<div style="text-align:center;padding:40px 20px;color:var(--red)"><div style="font-size:28px;margin-bottom:10px">⚠️</div><p style="font-size:13px">${escHtml(msg)}</p></div>`;}
function _paginationHTML(page,totalPages,fnName){
  if(totalPages<=1)return'';
  const s=a=>a?'background:var(--blue);color:#fff;border:none;border-radius:8px;padding:7px 14px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit':'background:var(--gray-100);color:var(--gray-700);border:none;border-radius:8px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit';
  const st=Math.max(1,page-2),en=Math.min(totalPages,page+2);
  let h='<div style="display:flex;gap:6px;justify-content:center;flex-wrap:wrap">';
  if(page>1)h+=`<button onclick="${fnName}(${page-1})" style="${s(false)}">‹ 이전</button>`;
  for(let i=st;i<=en;i++)h+=`<button onclick="${fnName}(${i})" style="${s(i===page)}">${i}</button>`;
  if(page<totalPages)h+=`<button onclick="${fnName}(${page+1})" style="${s(false)}">다음 ›</button>`;
  return h+'</div>';
}



function closeDashSearch() {
  document.getElementById('dash-search-results-wrap').classList.remove('visible');
  document.getElementById('dash-search-input').value = '';
  document.getElementById('dash-search-status').textContent = '';
  document.getElementById('dash-search-results').innerHTML = '';
}

// ── COMMUNITY MODULE ──
const CAT_LABELS = {
  popular: { label: '⭐ 인기글', cls: 'cat-popular' },
  qna:     { label: '❓ 질문',   cls: 'cat-qna' },
  review:  { label: '🎉 후기',   cls: 'cat-review' },
  regional:{ label: '📍 지역',   cls: 'cat-regional' },
  anonymous:{ label:'🤫 익명',   cls: 'cat-anonymous' },
  notice:  { label: '📢 공지',   cls: 'cat-notice' },
};

const SAMPLE_POSTS = [
  { id: 1, category: 'notice', title: '베네픽 커뮤니티 오픈 안내 🎉', content: '안녕하세요, 베네픽 팀입니다.\n드디어 복지 커뮤니티가 오픈되었습니다!\n\n수급 후기, 질문, 지역 정보 등 다양한 이야기를 나눠주세요.\n서로의 경험을 공유하면 더 많은 분들이 도움을 받을 수 있어요. 🙌', author: '베네픽팀', date: '2025-01-10', likes: 34, region: '' },
  { id: 2, category: 'review', title: '청년 월세 지원 드디어 받았어요!! 월 20만원 ㅠㅠ', content: '안녕하세요 서울 은평구에 사는 25살 취준생이에요.\n베네픽으로 수급 확률 92%라고 나와서 반신반의 하면서 신청했는데\n진짜로 승인됐습니다!!!\n\n전입신고 꼭 미리 해두셔야 해요. 저는 그거 때문에 한번 탈락했다가 다시 신청했거든요.\n다들 파이팅!', author: '은평구청년', date: '2025-01-12', likes: 87, region: '서울 은평구' },
  { id: 3, category: 'qna', title: '국민내일배움카드 소득 기준이 어떻게 되나요?', content: '안녕하세요! 취업준비 중인 28살입니다.\n베네픽에서 배움카드 수급 확률이 85%로 나왔는데\n혹시 소득 기준이 정확히 어떻게 되는지 아시는 분 계신가요?\n알바 수입이 있는데 괜찮을지 걱정돼서요.', author: '취준생_희망', date: '2025-01-13', likes: 12, region: '' },
  { id: 4, category: 'regional', title: '부산 해운대구 청년지원센터 정보 공유해요', content: '부산 해운대구 거주 청년분들!\n해운대구 청년지원센터에서 별도 복지 상담을 무료로 해줍니다.\n주소: 해운대구청 3층\n운영시간: 평일 09:00-18:00\n\n베네픽이랑 같이 활용하면 진짜 많은 혜택 받을 수 있어요!', author: '해운대청년', date: '2025-01-14', likes: 31, region: '부산 해운대구' },
  { id: 5, category: 'anonymous', title: '복지 신청이 창피한 것 같아서 망설이고 있어요...', content: '주변에서 "너 그런 거 받아도 돼?"라는 시선이 신경 쓰여서\n받을 자격이 있는데도 신청을 못 하고 있어요.\n\n혹시 비슷한 경험 있으신 분 계신가요?\n어떻게 마음을 정리하셨는지 궁금해요.', author: '익명', date: '2025-01-15', likes: 55, region: '' },
];

let commPosts = [];
let currentFilter = 'all';
let currentDetailId = null;

const AI_TIPS = [
  '💡 청년 월세 지원은 전입신고가 필수! 신청 전 반드시 확인하세요.',
  '💡 국민내일배움카드는 취업자·재직자 모두 신청 가능합니다.',
  '💡 복지 혜택은 중복 수령이 가능한 경우가 많아요. 꼭 꼼꼼히 확인하세요!',
  '💡 청년도약계좌는 매월 70만원 납입 시 정부기여금 최대 6%를 받을 수 있어요.',
  '💡 마음건강 바우처는 소득과 무관하게 신청 가능합니다.',
];

function initComm() {
  const stored = localStorage.getItem('benefic_posts');
  if (stored) {
    commPosts = JSON.parse(stored);
  } else {
    commPosts = JSON.parse(JSON.stringify(SAMPLE_POSTS));
    savePosts();
  }
  // AI tip rotation
  const tip = AI_TIPS[Math.floor(Math.random() * AI_TIPS.length)];
  const tipEl = document.getElementById('aiTip');
  if (tipEl) tipEl.textContent = tip;
}

function savePosts() {
  localStorage.setItem('benefic_posts', JSON.stringify(commPosts));
}

function getCatInfo(cat) {
  return CAT_LABELS[cat] || { label: cat, cls: 'cat-qna' };
}

function timeAgo(dateStr) {
  const d = new Date(dateStr);
  const now = new Date();
  const diff = Math.floor((now - d) / 86400000);
  if (diff === 0) return '오늘';
  if (diff === 1) return '어제';
  if (diff < 7) return diff + '일 전';
  return dateStr;
}

function filterComm(cat, btn) {
  currentFilter = cat;
  document.querySelectorAll('.comm-filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderCommPosts();
}

function renderCommPosts() {
  const listEl = document.getElementById('commPostList');
  const emptyEl = document.getElementById('commEmpty');
  if (!listEl) return;

  let filtered = currentFilter === 'all' ? commPosts
    : currentFilter === 'popular' ? commPosts.filter(p => p.likes >= 20).sort((a,b) => b.likes - a.likes)
    : commPosts.filter(p => p.category === currentFilter);

  filtered = [...filtered].reverse(); // newest first (for user posts)

  if (filtered.length === 0) {
    listEl.innerHTML = '';
    emptyEl.style.display = 'block';
  } else {
    emptyEl.style.display = 'none';
    listEl.innerHTML = filtered.map(post => {
      const cat = getCatInfo(post.category);
      return `
        <div class="comm-post-card" onclick="showCommDetail(${post.id})">
          <span class="comm-post-cat-badge ${cat.cls}">${cat.label}</span>
          <div class="comm-post-body">
            <h4>${escHtml(post.title)}</h4>
            <p>${escHtml(post.content.substring(0, 80))}${post.content.length > 80 ? '...' : ''}</p>
            <div class="comm-post-meta">
              <span class="comm-meta-item author">👤 ${escHtml(post.author)}</span>
              ${post.region ? `<span class="comm-meta-item">📍 ${escHtml(post.region)}</span>` : ''}
              <span class="comm-meta-item">🕐 ${timeAgo(post.date)}</span>
            </div>
          </div>
          <div class="comm-post-right">
            <div class="comm-stats">
              <span class="comm-stat">❤️ ${post.likes}</span>
            </div>
          </div>
        </div>`;
    }).join('');
  }

  renderHotList('hotPostList');
  updateStats();
}

function renderHotList(elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  const hot = [...commPosts].sort((a,b) => b.likes - a.likes).slice(0, 5);
  el.innerHTML = hot.map((p, i) => `
    <div class="hot-item" onclick="showCommDetail(${p.id})">
      <span class="hot-num">${i+1}</span>
      <span class="hot-title">${escHtml(p.title)}</span>
      <span class="hot-likes">❤️${p.likes}</span>
    </div>`).join('');
}

function updateStats() {
  if (!document.getElementById("statTotal")) return;
  const today = new Date().toISOString().slice(0,10);
  document.getElementById('statTotal').textContent = commPosts.length;
  document.getElementById('statToday').textContent = commPosts.filter(p => p.date === today).length;
  document.getElementById('statLikes').textContent = commPosts.reduce((s,p) => s + p.likes, 0);
}

function showCommDetail(id) {
  currentDetailId = id;
  const post = commPosts.find(p => p.id === id);
  if (!post) return;
  const cat = getCatInfo(post.category);
  const likedKey = 'liked_' + id;
  const isLiked = localStorage.getItem(likedKey);

  document.getElementById('commDetailCard').innerHTML = `
    <div class="comm-detail-meta">
      <span class="comm-post-cat-badge ${cat.cls}">${cat.label}</span>
      ${post.region ? `<span class="comm-meta-item">📍 ${escHtml(post.region)}</span>` : ''}
      <span class="comm-meta-item author">👤 ${escHtml(post.author)}</span>
      <span class="comm-meta-item">🕐 ${timeAgo(post.date)}</span>
    </div>
    <h2>${escHtml(post.title)}</h2>
    <div class="comm-detail-content">${escHtml(post.content)}</div>
    <button class="comm-like-btn ${isLiked ? 'liked' : ''}" id="likeBtn" onclick="toggleLike(${id})">
      ${isLiked ? '❤️' : '🤍'} 좋아요 <span id="likeCount">${post.likes}</span>
    </button>
  `;

  renderHotList('hotPostList2');
  document.getElementById('comm-list-view').style.display = 'none';
  document.getElementById('comm-detail-view').style.display = 'block';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showCommList() {
  document.getElementById('comm-list-view').style.display = 'block';
  document.getElementById('comm-detail-view').style.display = 'none';
  renderCommPosts();
}

function toggleLike(id) {
  const post = commPosts.find(p => p.id === id);
  if (!post) return;
  const likedKey = 'liked_' + id;
  const isLiked = localStorage.getItem(likedKey);
  if (isLiked) {
    post.likes = Math.max(0, post.likes - 1);
    localStorage.removeItem(likedKey);
  } else {
    post.likes += 1;
    localStorage.setItem(likedKey, '1');
  }
  savePosts();
  showCommDetail(id);
}

function openWriteModal() {
  document.getElementById('writeModalBg').classList.add('open');
  document.getElementById('modalTitle').focus();
}

function closeWriteModal(e) {
  if (e.target === document.getElementById('writeModalBg')) closeWriteModalDirect();
}

function closeWriteModalDirect() {
  document.getElementById('writeModalBg').classList.remove('open');
  document.getElementById('modalTitle').value = '';
  document.getElementById('modalContent').value = '';
  document.getElementById('modalRegion').value = '';
}

function submitPost() {
  const title = document.getElementById('modalTitle').value.trim();
  const content = document.getElementById('modalContent').value.trim();
  const cat = document.getElementById('modalCat').value;
  const region = document.getElementById('modalRegion').value.trim();

  if (!title) { alert('제목을 입력해주세요.'); return; }
  if (!content) { alert('내용을 입력해주세요.'); return; }

  const newPost = {
    id: Date.now(),
    category: cat,
    title,
    content,
    author: '남정현님',
    date: new Date().toISOString().slice(0,10),
    likes: 0,
    region,
  };
  commPosts.push(newPost);
  savePosts();
  closeWriteModalDirect();

  // show list view if in detail
  if (document.getElementById('comm-detail-view').style.display !== 'none') {
    showCommList();
  } else {
    currentFilter = 'all';
    document.querySelectorAll('.comm-filter-btn').forEach((b,i) => {
      b.classList.toggle('active', i === 0);
    });
    renderCommPosts();
  }
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Init community on page load
initComm();

// community.html 직접 접근 시 자동 렌더링
(function() {
  const currentPage = location.pathname.split('/').pop() || 'index.html';
  if (currentPage === 'community.html') {
    renderCommPosts();
    // insight widget 초기화
    const p = document.getElementById('iStatPosts');
    const l = document.getElementById('iStatLikes');
    if (p) p.textContent = commPosts.length;
    if (l) l.textContent = commPosts.reduce((s, post) => s + post.likes, 0);
    insightAnimateBars();
    // FAB 표시
    const fab = document.getElementById('fabWrite');
    if (fab) fab.classList.add('visible');
  }
})();

// ── INSIGHT WIDGET ──
const INSIGHT_REVIEWS = [
  { text: '신청이 생각보다 정말 간편해요!', tag: '#청년월세지원 · 은평구청년' },
  { text: '서류 준비 팁: 주민등록등본이 핵심!', tag: '#내일배움카드 · 취준생_희망' },
  { text: '베네픽 덕분에 몰랐던 혜택 발견했어요.', tag: '#소득세감면 · 익명' },
  { text: '월 20만원 지원 실제로 받았습니다 ㅠㅠ', tag: '#청년월세지원 · 서울청년' },
  { text: '복지 신청, 당연한 권리예요. 망설이지 마세요!', tag: '#익명고민 · 익명' },
];
let insightIdx = 0;

function insightRenderReviews() {
  const list = document.getElementById('iReviewList');
  const dots = document.getElementById('iNavDots');
  if (!list || !dots) return;
  const r1 = INSIGHT_REVIEWS[insightIdx];
  const r2 = INSIGHT_REVIEWS[(insightIdx + 1) % INSIGHT_REVIEWS.length];
  list.innerHTML = [r1, r2].map(r => `
    <div class="insight-review-item">
      <div class="insight-review-text">${r.text}</div>
      <span class="insight-review-tag">${r.tag}</span>
    </div>`).join('');
  dots.innerHTML = INSIGHT_REVIEWS.map((_, i) =>
    `<div class="insight-dot${i === insightIdx ? ' active' : ''}" onclick="insightIdx=${i};insightRenderReviews()"></div>`
  ).join('');
}

function insightAnimateBars() {
  setTimeout(() => { const b = document.getElementById('iBar1'); if(b) b.style.width='85%'; }, 100);
  setTimeout(() => { const b = document.getElementById('iBar2'); if(b) b.style.width='62%'; }, 250);
  setTimeout(() => { const b = document.getElementById('iBar3'); if(b) b.style.width='45%'; }, 400);
}

function insightRefresh() {
  ['iBar1','iBar2','iBar3'].forEach(id => { const b = document.getElementById(id); if(b) b.style.width='0%'; });
  setTimeout(insightAnimateBars, 150);
  insightIdx = (insightIdx + 1) % INSIGHT_REVIEWS.length;
  insightRenderReviews();
  const p = document.getElementById('iStatPosts');
  const l = document.getElementById('iStatLikes');
  if(p) p.textContent = commPosts.length;
  if(l) l.textContent = commPosts.reduce((s,p) => s + p.likes, 0);
}

function insightInit() {
  insightRenderReviews();
  insightAnimateBars();
  setInterval(() => { insightIdx = (insightIdx + 1) % INSIGHT_REVIEWS.length; insightRenderReviews(); }, 4000);
}
insightInit();

// ── Language Selector ──
function toggleLangDropdown() {
  const btn = document.getElementById('langBtn');
  const dd = document.getElementById('langDropdown');
  if (!btn || !dd) return;
  const isOpen = dd.classList.contains('visible');
  if (isOpen) {
    dd.classList.remove('visible');
    btn.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
  } else {
    dd.classList.add('visible');
    btn.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
  }
}

function selectLanguage(el, lang) {
  // 모든 옵션 초기화
  document.querySelectorAll('#langDropdown .lang-option').forEach(opt => {
    opt.classList.remove('active');
    const chk = opt.querySelector('.lang-check');
    if (chk) chk.remove();
  });
  // 선택된 항목에 체크 추가
  el.classList.add('active');
  el.insertAdjacentHTML('beforeend',
    `<svg class="lang-check" viewBox="0 0 13 13" fill="none">
      <path d="M2 6.5l3.5 3.5 5.5-6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`
  );
  const label = document.getElementById('currentLangLabel');
  if (label) label.textContent = lang;
  // 드롭다운 닫기 (딜레이로 클릭 이벤트 버블링과 충돌 방지)
  setTimeout(() => {
    const dd = document.getElementById('langDropdown');
    const btn = document.getElementById('langBtn');
    if (dd) dd.classList.remove('visible');
    if (btn) { btn.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }
  }, 150);
}

document.addEventListener('click', (e) => {
  const sel = document.getElementById('langSelector');
  if (!sel) return;
  if (!sel.contains(e.target)) {
    const dd = document.getElementById('langDropdown');
    const btn = document.getElementById('langBtn');
    if (dd) dd.classList.remove('visible');
    if (btn) { btn.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); }
  }
});

// Animate bars on load
window.addEventListener('load', () => {
  document.querySelectorAll('.progress-fill').forEach((bar, i) => {
    const finalW = bar.style.width;
    bar.style.width = '0';
    setTimeout(() => {
      bar.style.width = finalW;
    }, 300 + i * 120);
  });
  initDashSearch();

  // 현재 페이지에 맞는 초기화 실행
  const currentPage = location.pathname.split('/').pop() || 'index.html';
  if (currentPage === 'search.html') {
    initSearch();
  }
  if (currentPage === 'analysis.html') {
    const pid = (() => { try { return localStorage.getItem('benefic_detail_id'); } catch(e) { return null; } })();
    if (pid) {
      // 복원 즉시 삭제 — showDetail 내 showTab('detail')이 다시 analysis.html로
      // 이동 → 재복원 → 무한 루프가 생기는 것을 차단
      try { localStorage.removeItem('benefic_detail_id'); } catch(e) {}
      showDetail(pid);
    }
  }
});
