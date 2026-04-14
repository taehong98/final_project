"use client";

import { useMemo, useState } from "react";

type ScreenTab = "dashboard" | "search" | "detail" | "portfolio" | "apply" | "community";
type ApplyStatus = "APPLICABLE_NOW" | "NEEDS_CHECK" | "NOT_RECOMMENDED";
type ScoreLevel = "HIGH" | "MID" | "LOW";
type DocumentStatus = "READY" | "MISSING" | "UPLOADED" | "VERIFIED";
type PolicyLink = { link_type: string; link_name: string | null; link_url: string; sort_order: number };
type PolicyLaw = { law_name: string; law_type: string | null; source: string | null };
type PolicyTag = { tag_type: string; tag_code: string; tag_label: string };
type UnmatchedPolicy = { reference_id: string; source: string | null; reason: string };
type PolicySummary = {
  policy_id: string; title: string; description: string | null; match_score: number; score_level: ScoreLevel;
  apply_status: ApplyStatus; benefit_amount: number | null; benefit_amount_label: string | null; benefit_summary: string | null;
  badge_items: string[]; sort_order: number;
};
type AnalyzeResponse = {
  profile_summary: { display_name?: string; analysis_score: number; tags: string[] };
  policies: PolicySummary[]; rag_answer: string | null; rag_docs_used: string[]; unmatched_policies: UnmatchedPolicy[];
};
type SearchResponse = {
  items: PolicySummary[]; query: string; total_count: number; rag_answer: string | null; rag_docs_used: string[]; unmatched_policies: UnmatchedPolicy[];
};
type PolicyDetail = {
  policy_id: string; title: string; description: string | null; match_score: number; score_level: ScoreLevel; apply_status: ApplyStatus;
  eligibility_summary: string | null; blocking_reasons: string[]; recommended_actions: string[];
  required_documents: Array<{ document_type: string; document_name: string; description: string | null; is_required: boolean }>;
  related_links: PolicyLink[]; laws: PolicyLaw[]; tags: PolicyTag[]; application_url: string | null; managing_agency: string | null; last_updated_at: string | null;
};
type PortfolioData = {
  total_estimated_benefit_amount: number; total_estimated_benefit_label: string; currency: string; selected_policy_count: number;
  applicable_now_count: number; needs_check_count: number;
  portfolio_items: Array<{ policy_id: string; title: string; amount_label: string | null; benefit_summary: string | null; apply_status: ApplyStatus; source: string | null; tags: PolicyTag[] }>;
};
type ApplicationPrep = {
  policy_id: string; application_step: string;
  required_documents: Array<{ document_type: string; document_name: string; status: DocumentStatus; description: string | null; is_required: boolean }>;
  checklist_items: Array<{ code: string; label: string; is_done: boolean; sort_order: number }>;
  related_links: PolicyLink[]; laws: PolicyLaw[]; application_url: string | null;
};
type CommunityPost = { id: number; category: string; title: string; content: string; region_text: string | null; like_count: number };
type CommunityListResponse = { items: CommunityPost[] };
type CommunityStats = { total_posts: number; today_posts: number; total_likes: number };
type AnalyzeFormState = {
  age: number; region_code: string; region_name: string;
  income_band: "MID_50_60" | "MID_60_80" | "MID_80_100";
  household_type: "SINGLE" | "TWO_PERSON" | "MULTI_PERSON";
  employment_status: "UNEMPLOYED" | "EMPLOYED" | "SELF_EMPLOYED";
  housing_status: "MONTHLY_RENT" | "JEONSE" | "OWNER_FAMILY_HOME";
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const defaultForm: AnalyzeFormState = { age: 27, region_code: "KR-11-680", region_name: "서울 강남구", income_band: "MID_60_80", household_type: "SINGLE", employment_status: "UNEMPLOYED", housing_status: "MONTHLY_RENT" };
const regions = [
  { code: "KR-11-680", name: "서울 강남구" },
  { code: "KR-11-440", name: "서울 마포구" },
  { code: "KR-26-350", name: "부산 해운대구" },
  { code: "KR-41-117", name: "경기 수원시" },
];

const requestJson = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }, cache: "no-store" });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  const json = await res.json();
  return json.data as T;
};

const statusLabel = (s: ApplyStatus) => s === "APPLICABLE_NOW" ? "즉시 신청" : s === "NEEDS_CHECK" ? "조건 확인" : "보완 필요";
const scoreClass = (s: ScoreLevel) => s === "HIGH" ? "high" : s === "MID" ? "mid" : "low";
const statusClass = (s: ApplyStatus) => s === "APPLICABLE_NOW" ? "badge-green" : s === "NEEDS_CHECK" ? "badge-blue" : "badge-orange";
const iconForPolicy = (title: string) => title.includes("주거") || title.includes("월세") ? "🏠" : title.includes("교육") || title.includes("학비") ? "📘" : title.includes("의료") ? "🩺" : title.includes("취업") ? "💼" : "✨";
const formatDate = (value: string | null) => value ? new Date(value).toLocaleDateString("ko-KR") : "업데이트 정보 없음";

function Section({ title, subtitle }: { title: string; subtitle?: string }) {
  return <div className="section-header"><div><h3>{title}</h3>{subtitle ? <p>{subtitle}</p> : null}</div></div>;
}
function EmptyState({ message }: { message: string }) { return <div className="empty-state">{message}</div>; }

function PolicyCard({ policy, onClick }: { policy: PolicySummary; onClick: (id: string) => void }) {
  return (
    <div className={`policy-card ${policy.apply_status === "APPLICABLE_NOW" ? "top" : policy.apply_status === "NEEDS_CHECK" ? "mid" : "low"}`} onClick={() => onClick(policy.policy_id)}>
      <div className="policy-top-row">
        <div className="policy-left">
          <div className={`policy-icon ${scoreClass(policy.score_level)}`}>{iconForPolicy(policy.title)}</div>
          <div className="policy-meta">
            <h4>{policy.title}</h4>
            <p>{policy.description ?? "설명 정보가 아직 없습니다."}</p>
            <div className="policy-badges">{policy.badge_items.map((badge) => <span key={badge} className="badge badge-gray">{badge}</span>)}</div>
          </div>
        </div>
        <div className="policy-percent">
          <div className={`percent-num ${scoreClass(policy.score_level)}`}>{policy.match_score}</div>
          <div className={`badge ${statusClass(policy.apply_status)}`}>{statusLabel(policy.apply_status)}</div>
        </div>
      </div>
      <div className="progress-row"><div className="progress-track"><div className={`progress-fill ${scoreClass(policy.score_level)}`} style={{ width: `${policy.match_score}%` }} /></div></div>
      <div className="policy-action">{policy.benefit_amount_label ?? "혜택 정보 없음"} · {policy.benefit_summary ?? "상세 보기"}</div>
    </div>
  );
}

function UnmatchedCard({ item }: { item: UnmatchedPolicy }) {
  return (
    <div className="policy-card low">
      <div className="policy-top-row">
        <div className="policy-left">
          <div className="policy-icon low">!</div>
          <div className="policy-meta">
            <h4>{item.reference_id}</h4>
            <p>RAG는 찾았지만 현재 서비스 DB에는 없는 정책입니다.</p>
            <div className="policy-badges">
              <span className="badge badge-orange">DB 미연동</span>
              {item.source ? <span className="badge badge-gray">{item.source.toUpperCase()}</span> : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function LinkList({ links }: { links: PolicyLink[] }) {
  return links.length ? <div className="detail-link-list">{links.map((link) => <a key={link.link_url} className="detail-link-item" href={link.link_url} target="_blank" rel="noreferrer"><strong>{link.link_name ?? link.link_type}</strong><small>{link.link_type}</small></a>)}</div> : <EmptyState message="관련 링크가 없습니다." />;
}
function LawList({ laws }: { laws: PolicyLaw[] }) {
  return laws.length ? <div className="detail-law-list">{laws.map((law) => <div key={`${law.law_name}-${law.source}`} className="detail-law-item"><strong>{law.law_name}</strong><span>{law.law_type ?? law.source ?? "정책 근거"}</span></div>)}</div> : <EmptyState message="근거 법령이 없습니다." />;
}

export function Dashboard() {
  const [activeTab, setActiveTab] = useState<ScreenTab>("dashboard");
  const [form, setForm] = useState(defaultForm);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [searchResult, setSearchResult] = useState<SearchResponse | null>(null);
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [prep, setPrep] = useState<ApplicationPrep | null>(null);
  const [communityPosts, setCommunityPosts] = useState<CommunityPost[]>([]);
  const [communityStats, setCommunityStats] = useState<CommunityStats | null>(null);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [message, setMessage] = useState("조건을 입력하고 분석을 실행하면 RAG와 DB를 함께 이용한 추천 결과를 확인할 수 있습니다.");
  const [loading, setLoading] = useState(false);
  const [selectedPolicyId, setSelectedPolicyId] = useState<string | null>(null);

  const profileTags = useMemo(() => [
    `만 ${form.age}세`, form.region_name,
    form.household_type === "SINGLE" ? "1인 가구" : form.household_type === "TWO_PERSON" ? "2인 가구" : "다인 가구",
    form.employment_status === "UNEMPLOYED" ? "미취업" : form.employment_status === "EMPLOYED" ? "재직 중" : "자영업",
    form.housing_status === "MONTHLY_RENT" ? "월세 거주" : form.housing_status === "JEONSE" ? "전세 거주" : "자가/가족 소유",
  ], [form]);

  const loadPolicyBundle = async (policyId: string, nextTab: ScreenTab) => {
    const [detailData, prepData] = await Promise.all([
      requestJson<PolicyDetail>(`/policies/${policyId}/detail`),
      requestJson<ApplicationPrep>(`/applications/${policyId}/prep`),
    ]);
    setSelectedPolicyId(policyId);
    setDetail(detailData);
    setPrep(prepData);
    setActiveTab(nextTab);
  };

  const handleAnalyze = async () => {
    setLoading(true);
    setMessage("조건 기반 RAG 분석을 실행하고 있습니다.");
    try {
      const analyzeData = await requestJson<AnalyzeResponse>("/eligibility/analyze", { method: "POST", body: JSON.stringify(form) });
      setAnalysis(analyzeData);
      setPortfolio(await requestJson<PortfolioData>("/portfolio"));
      if (analyzeData.policies[0]) await loadPolicyBundle(analyzeData.policies[0].policy_id, "dashboard");
      setMessage("RAG 검색 결과와 DB 매핑이 완료되었습니다.");
    } catch {
      setMessage("분석 요청에 실패했습니다. 백엔드와 RAG 서버 상태를 확인해주세요.");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async () => {
    const keyword = searchKeyword.trim();
    if (!keyword) return setSearchResult(null);
    setLoading(true);
    try {
      const result = await requestJson<SearchResponse>(`/policies/search?q=${encodeURIComponent(keyword)}&size=20`);
      setSearchResult(result);
      setActiveTab("search");
    } finally {
      setLoading(false);
    }
  };

  const loadCommunity = async () => {
    const [listData, statsData] = await Promise.all([
      requestJson<CommunityListResponse>("/community/posts?category=all&sort=latest&page=1&size=10"),
      requestJson<CommunityStats>("/community/stats"),
    ]);
    setCommunityPosts(listData.items);
    setCommunityStats(statsData);
  };

  return (
    <>
      <nav>
        <a href="#" className="nav-logo" onClick={(e) => { e.preventDefault(); setActiveTab("dashboard"); }}>
          <div className="logo-mark">B</div>
          <div className="logo-text"><span className="logo-name">베네픽</span><span className="logo-tag">RAG 연동 정책 추천 대시보드</span></div>
        </a>
        <div className="nav-center">
          {(["dashboard", "search", "detail", "portfolio", "apply", "community"] as ScreenTab[]).map((tab) => (
            <a key={tab} href="#" className={activeTab === tab ? "active" : ""} onClick={(e) => { e.preventDefault(); setActiveTab(tab); if (tab === "community") void loadCommunity(); }}>
              {tab === "dashboard" ? "대시보드" : tab === "search" ? "정책 검색" : tab === "detail" ? "정책 상세" : tab === "portfolio" ? "포트폴리오" : tab === "apply" ? "신청 보조" : "커뮤니티"}
            </a>
          ))}
        </div>
        <div className="nav-right"><button className="lang-btn" type="button">한국어</button></div>
      </nav>

      <div className="container">
        <div className={`screen ${activeTab === "dashboard" ? "active" : ""}`}>
          <div className="dash-search-bar">
            <span className="dash-search-label">정책 검색</span>
            <input value={searchKeyword} onChange={(e) => setSearchKeyword(e.target.value)} placeholder="청년 월세, 취업, 교육비, 의료비" />
            <button className="btn-primary" type="button" onClick={() => void handleSearch()}>검색</button>
          </div>
          <div className="grid-main">
            <div>
              <div className="profile-card">
                <div className="profile-header">
                  <div className="profile-user"><div className="profile-avatar">AI</div><div className="profile-info"><h2>조건 기반 RAG 분석</h2><p>입력 조건을 문장형 질의로 변환해 RAG를 호출하고 DB 정책과 연결합니다.</p></div></div>
                  <div className="score-badge"><div className="score-label">분석 점수</div><div className="score-num">{analysis?.profile_summary.analysis_score ?? 0}</div><div className="score-sub">/ 100</div></div>
                </div>
                <div className="profile-tags">{profileTags.map((tag) => <span key={tag} className="profile-tag">{tag}</span>)}</div>
              </div>

              <div className="input-card">
                <div className="input-card-header"><h3>조건 입력</h3><span className="ai-chip">AI 분석</span></div>
                <div className="input-grid expanded">
                  <div className="input-item"><label>나이</label><input type="number" value={form.age} onChange={(e) => setForm((prev) => ({ ...prev, age: Number(e.target.value) }))} /></div>
                  <div className="input-item"><label>지역</label><select value={form.region_code} onChange={(e) => { const selected = regions.find((item) => item.code === e.target.value); if (selected) setForm((prev) => ({ ...prev, region_code: selected.code, region_name: selected.name })); }}>{regions.map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}</select></div>
                  <div className="input-item"><label>소득 구간</label><select value={form.income_band} onChange={(e) => setForm((prev) => ({ ...prev, income_band: e.target.value as AnalyzeFormState["income_band"] }))}><option value="MID_50_60">중위소득 50~60%</option><option value="MID_60_80">중위소득 60~80%</option><option value="MID_80_100">중위소득 80~100%</option></select></div>
                  <div className="input-item"><label>가구 형태</label><select value={form.household_type} onChange={(e) => setForm((prev) => ({ ...prev, household_type: e.target.value as AnalyzeFormState["household_type"] }))}><option value="SINGLE">1인 가구</option><option value="TWO_PERSON">2인 가구</option><option value="MULTI_PERSON">다인 가구</option></select></div>
                  <div className="input-item"><label>취업 상태</label><select value={form.employment_status} onChange={(e) => setForm((prev) => ({ ...prev, employment_status: e.target.value as AnalyzeFormState["employment_status"] }))}><option value="UNEMPLOYED">미취업</option><option value="EMPLOYED">재직 중</option><option value="SELF_EMPLOYED">자영업</option></select></div>
                  <div className="input-item"><label>주거 상태</label><select value={form.housing_status} onChange={(e) => setForm((prev) => ({ ...prev, housing_status: e.target.value as AnalyzeFormState["housing_status"] }))}><option value="MONTHLY_RENT">월세</option><option value="JEONSE">전세</option><option value="OWNER_FAMILY_HOME">자가/가족 소유</option></select></div>
                </div>
                <button className="analyze-btn" type="button" onClick={() => void handleAnalyze()} disabled={loading}>{loading ? "분석 중..." : "AI 분석 실행"}</button>
                <p className="inline-message">{message}</p>
              </div>

              <Section title="추천 정책" subtitle="RAG가 찾은 정책 중 DB와 연결된 정책만 카드로 보여줍니다." />
              <div className="policy-list">{analysis?.policies?.length ? analysis.policies.map((policy) => <PolicyCard key={policy.policy_id} policy={policy} onClick={(id) => void loadPolicyBundle(id, "detail")} />) : <EmptyState message="아직 분석 결과가 없습니다." />}</div>
              <Section title="추가 참고 정책" subtitle="RAG는 찾았지만 현재 서비스 DB에는 없는 정책입니다." />
              <div className="policy-list">{analysis?.unmatched_policies?.length ? analysis.unmatched_policies.map((item) => <UnmatchedCard key={item.reference_id} item={item} />) : <EmptyState message="DB 미연동 정책이 없습니다." />}</div>
            </div>
            <div className="sidebar">
              <div className="sidebar-card"><h4>RAG 요약</h4><p>{analysis?.rag_answer ?? "분석을 실행하면 RAG 답변이 이 영역에 표시됩니다."}</p></div>
              <div className="sidebar-card"><h4>RAG 참고 문서</h4><div className="detail-chip-wrap">{(analysis?.rag_docs_used ?? []).slice(0, 12).map((docId) => <span key={docId} className="detail-chip">{docId}</span>)}</div></div>
            </div>
          </div>
        </div>

        <div className={`screen ${activeTab === "search" ? "active" : ""}`}>
          <div className="dash-search-bar">
            <span className="dash-search-label">정책 검색</span>
            <input value={searchKeyword} onChange={(e) => setSearchKeyword(e.target.value)} placeholder="청년 월세, 취업, 교육비, 의료비" />
            <button className="btn-primary" type="button" onClick={() => void handleSearch()}>검색</button>
          </div>
          <div className="grid-main">
            <div>
              <Section title="검색 결과" subtitle={searchResult ? `${searchResult.total_count}건의 DB 연동 정책이 검색되었습니다.` : "자유 텍스트 질의로 RAG 검색을 실행합니다."} />
              <div className="policy-list">{searchResult?.items?.length ? searchResult.items.map((policy) => <PolicyCard key={policy.policy_id} policy={policy} onClick={(id) => void loadPolicyBundle(id, "detail")} />) : <EmptyState message="검색 결과가 없습니다." />}</div>
              <Section title="DB 미연동 검색 결과" subtitle="RAG는 찾았지만 현재 서비스 DB에는 없는 정책입니다." />
              <div className="policy-list">{searchResult?.unmatched_policies?.length ? searchResult.unmatched_policies.map((item) => <UnmatchedCard key={item.reference_id} item={item} />) : <EmptyState message="검색된 미연동 정책이 없습니다." />}</div>
            </div>
            <div className="sidebar">
              <div className="sidebar-card"><h4>검색 RAG 요약</h4><p>{searchResult?.rag_answer ?? "검색을 실행하면 RAG 요약이 이 영역에 표시됩니다."}</p></div>
              <div className="sidebar-card"><h4>참고 문서 ID</h4><div className="detail-chip-wrap">{(searchResult?.rag_docs_used ?? []).slice(0, 12).map((docId) => <span key={docId} className="detail-chip">{docId}</span>)}</div></div>
            </div>
          </div>
        </div>

        <div className={`screen ${activeTab === "detail" ? "active" : ""}`}>
          <div className="grid-main">
            <div>
              <div className="detail-panel">
                {detail ? (
                  <>
                    <div className="profile-header">
                      <div className="profile-user"><div className="policy-icon top">{iconForPolicy(detail.title)}</div><div className="profile-info"><h2>{detail.title}</h2><p>{detail.description ?? "설명 정보가 없습니다."}</p></div></div>
                      <div className="score-badge"><div className="score-label">적합도</div><div className="score-num">{detail.match_score}</div><div className="score-sub">{statusLabel(detail.apply_status)}</div></div>
                    </div>
                    <div className="ai-summary-box"><div className="ai-summary-box-header"><span className="ai-summary-badge">AI 요약</span></div><div className="ai-summary-content">{detail.eligibility_summary}</div></div>
                    <div className="detail-chip-wrap">{detail.tags.map((tag) => <span key={`${tag.tag_type}-${tag.tag_code}`} className="detail-chip">{tag.tag_label}</span>)}</div>
                    <Section title="보완이 필요한 조건" />
                    <div className="detail-card-stack">{detail.blocking_reasons.length ? detail.blocking_reasons.map((reason) => <div key={reason} className="detail-alert danger">{reason}</div>) : <EmptyState message="현재 확인된 탈락 사유가 없습니다." />}</div>
                    <Section title="권장 액션" />
                    <div className="detail-card-stack">{detail.recommended_actions.map((action) => <div key={action} className="detail-alert success">{action}</div>)}</div>
                    <Section title="필수 서류" />
                    <div className="detail-card-stack">{detail.required_documents.length ? detail.required_documents.map((doc) => <div key={`${doc.document_type}-${doc.document_name}`} className="detail-alert neutral"><strong>{doc.document_name}</strong><span>{doc.description ?? (doc.is_required ? "필수 제출 서류" : "선택 제출 서류")}</span></div>) : <EmptyState message="등록된 서류 정보가 없습니다." />}</div>
                  </>
                ) : <EmptyState message="정책을 선택하면 상세 정보가 열립니다." />}
              </div>
            </div>
            <div className="sidebar">
              <div className="sidebar-card"><h4>관련 링크</h4><LinkList links={detail?.related_links ?? []} /></div>
              <div className="sidebar-card"><h4>근거 법령</h4><LawList laws={detail?.laws ?? []} /></div>
              <div className="sidebar-card"><h4>정책 정보</h4><p>관리 기관: {detail?.managing_agency ?? "정보 없음"}</p><p>마지막 업데이트: {formatDate(detail?.last_updated_at ?? null)}</p>{detail?.application_url ? <a className="btn-primary wide" href={detail.application_url} target="_blank" rel="noreferrer">온라인 신청 바로가기</a> : null}</div>
            </div>
          </div>
        </div>

        <div className={`screen ${activeTab === "portfolio" ? "active" : ""}`}>
          <Section title="추천 포트폴리오" subtitle="최근 분석 결과 기준 예상 혜택입니다." />
          {portfolio ? <>
            <div className="port-grid-card"><div className="profile-header"><div className="profile-info"><h2>{portfolio.total_estimated_benefit_label}</h2><p>총 예상 혜택 · {portfolio.currency}</p></div><div className="policy-badges"><span className="badge badge-green">즉시 신청 {portfolio.applicable_now_count}건</span><span className="badge badge-blue">조건 확인 {portfolio.needs_check_count}건</span></div></div></div>
            <div className="policy-list">{portfolio.portfolio_items.map((item) => <div key={item.policy_id} className="policy-card mid" onClick={() => void loadPolicyBundle(item.policy_id, "detail")}><div className="policy-top-row"><div className="policy-left"><div className="policy-icon mid">{iconForPolicy(item.title)}</div><div className="policy-meta"><h4>{item.title}</h4><p>{item.benefit_summary ?? "혜택 요약 정보 없음"}</p><div className="policy-badges"><span className="badge badge-gray">{item.source?.toUpperCase() ?? "SOURCE"}</span>{item.tags.slice(0, 3).map((tag) => <span key={`${tag.tag_type}-${tag.tag_code}`} className="badge badge-gray">{tag.tag_label}</span>)}</div></div></div><div className="policy-percent"><div className="percent-num mid">{item.amount_label ?? "-"}</div><div className={`badge ${statusClass(item.apply_status)}`}>{statusLabel(item.apply_status)}</div></div></div></div>)}</div>
          </> : <EmptyState message="먼저 AI 분석을 실행하면 포트폴리오가 생성됩니다." />}
        </div>

        <div className={`screen ${activeTab === "apply" ? "active" : ""}`}>
          <Section title="신청 보조" subtitle="선택된 정책의 서류와 체크리스트를 준비합니다." />
          {prep ? <div className="grid-main"><div><div className="detail-panel"><div className="profile-header"><div className="profile-info"><h2>{selectedPolicyId ?? prep.policy_id}</h2><p>현재 단계: {prep.application_step}</p></div>{prep.application_url ? <a className="btn-primary" href={prep.application_url} target="_blank" rel="noreferrer">신청 페이지 이동</a> : null}</div><Section title="필수 서류 상태" /><div className="detail-card-stack">{prep.required_documents.map((doc) => <div key={`${doc.document_type}-${doc.document_name}`} className="detail-alert neutral"><strong>{doc.document_name} · {doc.status}</strong><span>{doc.description ?? "상세 설명 없음"}</span></div>)}</div><Section title="체크리스트" /><div className="detail-card-stack">{prep.checklist_items.map((item) => <div key={item.code} className={`detail-alert ${item.is_done ? "success" : "neutral"}`}><strong>{item.label}</strong><span>{item.is_done ? "완료" : "진행 필요"}</span></div>)}</div></div></div><div className="sidebar"><div className="sidebar-card"><h4>관련 링크</h4><LinkList links={prep.related_links} /></div><div className="sidebar-card"><h4>근거 법령</h4><LawList laws={prep.laws} /></div></div></div> : <EmptyState message="정책을 선택하면 신청 보조 정보가 표시됩니다." />}
        </div>

        <div className={`screen ${activeTab === "community" ? "active" : ""}`}>
          <div className="grid-main">
            <div><Section title="커뮤니티" subtitle="정책 후기와 질문을 함께 확인해보세요." /><div className="policy-list">{communityPosts.length ? communityPosts.map((post) => <div key={post.id} className="policy-card mid"><div className="policy-top-row"><div className="policy-left"><div className="policy-icon mid">💬</div><div className="policy-meta"><h4>{post.title}</h4><p>{post.content}</p><div className="policy-badges"><span className="badge badge-gray">{post.category}</span>{post.region_text ? <span className="badge badge-gray">{post.region_text}</span> : null}<span className="badge badge-gray">좋아요 {post.like_count}</span></div></div></div></div></div>) : <EmptyState message="커뮤니티 게시글이 없습니다." />}</div></div>
            <div className="sidebar"><div className="sidebar-card"><h4>커뮤니티 통계</h4><p>전체 게시글: {communityStats?.total_posts ?? 0}</p><p>오늘 게시글: {communityStats?.today_posts ?? 0}</p><p>총 좋아요: {communityStats?.total_likes ?? 0}</p></div></div>
          </div>
        </div>
      </div>
    </>
  );
}
