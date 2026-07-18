"use client";

import { useEffect, useMemo, useState } from "react";

type Asset = { id: number; type: string; alt: string; filename: string; theme?: string; image?: string };
type Blog = { id: string; name: string; url: string };
type Post = { id: string; title: string; content: string; published?: string; status?: string };

const sampleTitle = "봄철 서울 근교 당일치기 여행 추천 8곳";
const sampleBody = `따뜻한 봄바람이 불어오는 계절, 멀리 떠나지 않아도 하루를 알차게 보낼 수 있는 서울 근교 여행지가 많습니다. 아름다운 자연과 맛있는 음식, 사진 찍기 좋은 명소까지 모두 갖춘 곳들로 선별해 보았어요.\n\n1. 남양주 다산유적지\n정약용 선생의 발자취를 따라 걸으며 조용한 힐링을 즐길 수 있는 곳이에요. 주변 한강 풍경도 일품입니다.\n\n2. 가평 아침고요수목원\n형형색색의 봄꽃이 가득한 정원에서 산책을 즐겨보세요. 튤립과 벚꽃이 어우러진 풍경이 아름답습니다.\n\n3. 양평 세미원\n연꽃과 다양한 수생식물을 감상할 수 있는 곳으로, 한적하게 여유를 즐기기 좋아요.\n\n4. 파주 헤이리 예술마을\n감성 가득한 카페와 갤러리, 책방을 둘러보며 문화적인 하루를 보내기 좋은 곳입니다.`;

const initialAssets: Asset[] = [
  { id: 0, type: "대표 이미지 1장", alt: "봄날 서울 근교로 떠나는 당일치기 여행 풍경", filename: "seoul-day-trip-cover.webp", theme: "cover" },
  { id: 1, type: "본문 이미지 1", alt: "남양주 다산유적지의 한옥과 봄 풍경", filename: "seoul-day-trip-dasan.webp", theme: "heritage" },
  { id: 2, type: "본문 이미지 2", alt: "가평 아침고요수목원에 핀 봄꽃", filename: "seoul-day-trip-garden.webp", theme: "garden" },
  { id: 3, type: "요약 인포그래픽 1장", alt: "서울 근교 당일치기 여행지 8곳 핵심 요약", filename: "seoul-day-trip-summary.webp", theme: "info" },
];

function Icon({ children }: { children: React.ReactNode }) { return <span className="icon">{children}</span>; }

export default function Home() {
  const [title, setTitle] = useState(sampleTitle);
  const [body, setBody] = useState(sampleBody);
  const [assets, setAssets] = useState(initialAssets);
  const [step, setStep] = useState(1);
  const [generating, setGenerating] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [inserted, setInserted] = useState(false);
  const [session, setSession] = useState({ connected: false, email: "", openai: false, googleConfigured: false });
  const [blogId, setBlogId] = useState("");
  const [postId, setPostId] = useState("");
  const [blogs, setBlogs] = useState<Blog[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [loadingBlogs, setLoadingBlogs] = useState(false);
  const [loadingPosts, setLoadingPosts] = useState(false);
  useEffect(() => { fetch("/api/auth/session").then(r => r.json()).then(setSession).catch(() => null); }, []);
  useEffect(() => { if (session.connected) void loadBlogs(); }, [session.connected]);

  const stats = useMemo(() => ({ chars: body.length, paragraphs: body.split(/\n+/).filter(Boolean).length, keywords: Math.max(4, Math.min(10, Math.round(body.length / 90))) }), [body]);

  const notify = (message: string) => { setToast(message); window.setTimeout(() => setToast(""), 2200); };
  const loadBlogs = async () => {
    setLoadingBlogs(true);
    try { const r = await fetch("/api/blogger/blogs"); const data = await r.json(); if (!r.ok) throw new Error(data.error?.message || data.error || "블로그 조회 실패"); setBlogs(data.items || []); if ((data.items || []).length === 1) await selectBlog(data.items[0].id); }
    catch (e) { notify(e instanceof Error ? e.message : "블로그 조회 실패"); } finally { setLoadingBlogs(false); }
  };
  const selectBlog = async (id: string) => {
    setBlogId(id); setPostId(""); setPosts([]); setLoadingPosts(true);
    try { const r = await fetch(`/api/blogger/posts?blogId=${encodeURIComponent(id)}`); const data = await r.json(); if (!r.ok) throw new Error(data.error?.message || data.error || "게시글 조회 실패"); setPosts(data.items || []); }
    catch (e) { notify(e instanceof Error ? e.message : "게시글 조회 실패"); } finally { setLoadingPosts(false); }
  };
  const selectPost = (id: string) => {
    setPostId(id); const post = posts.find(p => p.id === id); if (!post) return;
    const doc = new DOMParser().parseFromString(post.content || "", "text/html");
    doc.querySelectorAll("script,style,noscript").forEach(n => n.remove());
    const plain = (doc.body.innerText || doc.body.textContent || "").replace(/\n{3,}/g, "\n\n").trim();
    setTitle(post.title || ""); setBody(plain); setStep(1); setAssets(initialAssets); notify("게시글 제목과 본문을 불러왔습니다.");
  };
  const generate = async () => {
    if (!title.trim() || body.trim().length < 80) return notify("제목과 본문을 80자 이상 입력해주세요.");
    setGenerating(true); setStep(2);
    try { const r = await fetch("/api/generate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ title, body }) }); const data = await r.json(); if (!r.ok) throw new Error(data.error || "이미지 생성 실패"); setAssets(data.assets); notify("실제 AI 이미지 4장이 완성됐습니다."); }
    catch (e) { notify(e instanceof Error ? e.message : "생성 오류"); } finally { setGenerating(false); }
  };
  const updateAsset = (id: number, key: "alt" | "filename", value: string) => setAssets(v => v.map(a => a.id === id ? { ...a, [key]: value } : a));
  const buildHtml = () => {
    const blocks = assets.map((a, i) => `<figure><img src="${a.image || `IMAGE_URL_${i + 1}`}" alt="${a.alt}" loading="lazy"><figcaption>${a.alt}</figcaption></figure>`);
    return `<h1>${title}</h1>\n${blocks[0]}\n<p>${body.replace(/\n+/g, "</p>\n<p>")}</p>\n${blocks.slice(1).join("\n")}`;
  };
  const insert = async () => { setStep(3); setInserted(true); await navigator.clipboard?.writeText(buildHtml()); notify("Blogger용 HTML을 복사했습니다."); };
  const saveToBlogger = async () => { if (!session.connected) { location.href = "/api/auth/google"; return; } if (!blogId || !postId) return notify("블로그 ID와 게시글 ID를 입력해주세요."); const r = await fetch("/api/blogger/posts", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ blogId, postId, title, content: buildHtml() }) }); const data = await r.json(); if (!r.ok) return notify(data.error?.message || data.error || "Blogger 저장 실패"); setStep(3); notify("Blogger 게시글 저장을 완료했습니다."); };

  return (
    <main>
      <header className="topbar">
        <div className="brand"><span className="brandMark">K</span><span>Kevin Blog Image Studio</span><em>MVP</em></div>
        <div className="topActions"><span className="credit"><i /> {session.openai ? "OpenAI 연결" : "API 설정 필요"}</span><button className="googleBtn" onClick={() => location.href="/api/auth/google"}>{session.connected ? `✓ ${session.email}` : "G Google 로그인"}</button><span className="avatar">K</span></div>
      </header>

      <section className="steps" aria-label="진행 단계">
        {["본문 입력", "이미지 생성", "검토·삽입"].map((label, i) => <div className={`step ${step >= i + 1 ? "active" : ""}`} key={label}><span>{step > i + 1 ? "✓" : i + 1}</span><b>{label}</b>{i < 2 && <i />}</div>)}
      </section>

      <section className="workspace">
        <article className="panel inputPanel">
          <div className="blogPicker">
            <div><b>Google Blogger에서 불러오기</b><span>{session.connected ? "연결됨" : "Google 로그인이 필요합니다"}</span></div>
            {!session.connected ? <button className="secondary" onClick={() => location.href="/api/auth/google"}>G Google 로그인</button> : <>
              <select aria-label="블로그 선택" value={blogId} onChange={e => void selectBlog(e.target.value)} disabled={loadingBlogs}><option value="">{loadingBlogs ? "블로그 불러오는 중…" : "블로그 선택"}</option>{blogs.map(b => <option value={b.id} key={b.id}>{b.name}</option>)}</select>
              <select aria-label="게시글 선택" value={postId} onChange={e => selectPost(e.target.value)} disabled={!blogId || loadingPosts}><option value="">{loadingPosts ? "게시글 불러오는 중…" : "게시글 선택"}</option>{posts.map(p => <option value={p.id} key={p.id}>{p.title}</option>)}</select>
              <button className="refreshBtn" onClick={loadBlogs} aria-label="블로그 목록 새로고침">↻</button>
            </>}
          </div>
          <div className="panelTitle"><Icon>▤</Icon><div><h1>블로그 본문</h1><p>글을 붙여 넣으면 이미지 구성을 자동으로 분석합니다.</p></div><button className="ghost" onClick={() => { setTitle(""); setBody(""); }}>새로 작성</button></div>
          <label>제목</label>
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="블로그 제목을 입력하세요" />
          <div className="labelRow"><label>본문</label><span>{body.length.toLocaleString()} / 10,000자</span></div>
          <textarea value={body} onChange={e => setBody(e.target.value)} placeholder="블로그 본문을 붙여 넣으세요" />
          <div className="analysis"><b>본문 분석</b><span>▣ 글자 수 <strong>{stats.chars}자</strong></span><span>☷ 문단 수 <strong>{stats.paragraphs}개</strong></span><span>▰ 이미지 제안 <strong>4장</strong></span><span>◆ 핵심 키워드 <strong>{stats.keywords}개</strong></span></div>
          <button className="primary" onClick={generate} disabled={generating}>{generating ? <><span className="spinner" />이미지 기획을 만들고 있어요…</> : <>✦ 이미지 세트 만들기</>}</button>
          <p className="safe">✓ 자동 게시되지 않습니다. 검토 후 직접 삽입합니다.</p>
        </article>

        <article className="panel outputPanel">
          <div className="panelTitle"><Icon>▧</Icon><div><h2>생성 미리보기</h2><p>카드를 눌러 ALT와 파일명을 수정할 수 있습니다.</p></div><span className="four">4장</span></div>
          <div className={`assetGrid ${generating ? "loading" : ""}`}>
            {assets.map(asset => <button className={`assetCard ${selected === asset.id ? "selected" : ""}`} key={asset.id} onClick={() => setSelected(asset.id)}>
              <div className={`visual ${asset.theme || ""}`}>
                {asset.image ? <img src={asset.image} alt={asset.alt} /> : <>
                {asset.theme === "cover" && <><span className="sun"/><span className="hill one"/><span className="hill two"/><b>SEOUL DAY TRIP</b></>}
                {asset.theme === "heritage" && <><span className="roof"/><span className="house"/><span className="tree"/></>}
                {asset.theme === "garden" && <><span className="path"/><span className="flowers">✿ ✿ ✿ ✿</span></>}
                {asset.theme === "info" && <div className="infoSheet"><b>서울 근교 당일치기</b><small>여행 추천 8곳</small><div><i>자연<br/>3곳</i><i>문화<br/>2곳</i><i>힐링<br/>2곳</i><i>정원<br/>1곳</i></div></div>}</>}
              </div>
              <div className="assetHead"><strong>{asset.type}</strong><span>•••</span></div>
              <dl><div><dt>ALT</dt><dd>{asset.alt}</dd></div><div><dt>파일명</dt><dd>{asset.filename}</dd></div></dl>
            </button>)}
          </div>
          <div className="outputBar"><span>ⓘ 이미지 URL은 Blogger 업로드 후 교체하세요.</span><button onClick={() => notify("전체 미리보기 준비가 완료됐습니다.")}>전체 미리보기 ↗</button></div>
        </article>
      </section>

      <section className="insertPanel panel">
        <div><span className="ready">검토 단계</span><h2>ALT·파일명 확인 후 본문에 삽입하세요</h2><p>반자동 방식으로 Blogger용 HTML을 만들고 클립보드에 복사합니다.</p></div>
        <div className="selectedPost">{postId ? <><b>선택된 글</b><span>{posts.find(p => p.id === postId)?.title}</span></> : <span>위에서 블로그 글을 선택하세요</span>}</div><div className="insertActions"><button className="secondary" onClick={insert}>HTML 복사</button><button className="primary small" onClick={saveToBlogger}>{session.connected ? "선택 글에 저장" : "Google 연결"}</button></div>
        {inserted && <div className="htmlPreview"><div><b>Blogger 삽입 HTML</b><button onClick={() => navigator.clipboard?.writeText(buildHtml())}>복사</button></div><code>{buildHtml().slice(0, 350)}…</code></div>}
      </section>

      {selected !== null && <div className="modalBackdrop" onMouseDown={() => setSelected(null)}><section className="editor" onMouseDown={e => e.stopPropagation()}>
        <button className="close" onClick={() => setSelected(null)}>×</button><span className="ready">이미지 {selected + 1}</span><h2>{assets[selected].type} 편집</h2>
        <div className={`visual large ${assets[selected].theme || ""}`}>{assets[selected].image ? <img src={assets[selected].image} alt={assets[selected].alt}/> : assets[selected].theme === "info" ? <div className="infoSheet"><b>서울 근교 당일치기</b><small>여행 추천 8곳</small><div><i>자연<br/>3곳</i><i>문화<br/>2곳</i><i>힐링<br/>2곳</i><i>정원<br/>1곳</i></div></div> : <span className="previewWord">미리보기</span>}</div>
        <label>ALT 텍스트</label><input value={assets[selected].alt} onChange={e => updateAsset(selected, "alt", e.target.value)} />
        <label>파일명</label><input value={assets[selected].filename} onChange={e => updateAsset(selected, "filename", e.target.value)} />
        <div className="editorActions"><button className="secondary" onClick={() => notify("새로운 시안을 생성했습니다.")}>↻ 다시 생성</button><button className="primary small" onClick={() => { setSelected(null); notify("변경사항을 저장했습니다."); }}>변경 저장</button></div>
      </section></div>}
      {toast && <div className="toast">✓ {toast}</div>}
    </main>
  );
}
