"""
Blogger 정적 페이지 생성 모듈
- Privacy Policy (개인정보처리방침)
- About (블로그 소개)

AdSense 심사 필수 요건:
1. 개인정보처리방침 — 쿠키/광고/데이터 수집 고지
2. About 페이지 — E-E-A-T 입증 (작성자 신뢰성)
"""

import json
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"


# ──────────────────────────────────────────────────────────────────────────────
# 블로그 테마 감지
# ──────────────────────────────────────────────────────────────────────────────

def _detect_theme(blog_cfg: dict) -> str:
    """블로그 이름·id로 테마를 판별합니다."""
    name = (blog_cfg.get("name") or blog_cfg.get("id") or "").lower()
    if any(k in name for k in ["금융", "finance", "news", "뉴스", "주식", "경제", "투자"]):
        return "finance"
    if any(k in name for k in ["여행", "travel", "스포츠", "sports", "연예", "entertainment", "hogu"]):
        return "lifestyle"
    return "general"


# ──────────────────────────────────────────────────────────────────────────────
# OAuth / API
# ──────────────────────────────────────────────────────────────────────────────

def _get_access_token(blog_cfg: dict | None = None) -> str | None:
    try:
        if blog_cfg and blog_cfg.get("client_id") and blog_cfg.get("refresh_token"):
            client_id     = blog_cfg["client_id"]
            client_secret = blog_cfg.get("client_secret", "")
            refresh_token = blog_cfg["refresh_token"]
        else:
            from config import BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN
            client_id     = BLOGGER_CLIENT_ID
            client_secret = BLOGGER_CLIENT_SECRET
            refresh_token = BLOGGER_REFRESH_TOKEN

        resp = requests.post(TOKEN_URL, data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"토큰 요청 오류: {e}")
    return None


def _get_blog_id(blog_cfg: dict | None = None) -> str:
    if blog_cfg:
        bid = blog_cfg.get("blog_id") or blog_cfg.get("id")
        if bid:
            return bid
    from config import BLOGGER_BLOG_ID
    return BLOGGER_BLOG_ID


def _list_existing_pages(token: str, blog_id: str) -> list[dict]:
    try:
        resp = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages",
            headers={"Authorization": f"Bearer {token}"},
            params={"status": "live"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("items", [])
    except Exception as e:
        logger.warning(f"페이지 목록 조회 실패: {e}")
    return []


def _create_or_update_page(token: str, blog_id: str, title: str, content: str, existing_pages: list[dict]) -> dict | None:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"title": title, "content": content}

    existing = next((p for p in existing_pages if p.get("title", "").strip() == title.strip()), None)
    try:
        if existing:
            page_id = existing["id"]
            resp = requests.put(
                f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages/{page_id}",
                json=payload, headers=headers, timeout=30,
            )
            action = "업데이트"
        else:
            resp = requests.post(
                f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages",
                json=payload, headers=headers, params={"isDraft": False}, timeout=30,
            )
            action = "생성"

        if resp.status_code in (200, 201):
            result = resp.json()
            logger.info(f"페이지 {action} 완료: {title} → {result.get('url', '')}")
            return result
        logger.error(f"페이지 {action} 실패: {resp.status_code} {resp.text[:300]}")
    except Exception as e:
        logger.error(f"페이지 API 오류: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 공통 스타일
# ──────────────────────────────────────────────────────────────────────────────

def _make_page_style() -> str:
    return """<style>
body{font-family:'Noto Sans KR','Apple SD Gothic Neo',sans-serif;line-height:1.9;color:#333;max-width:860px;margin:0 auto;padding:0 16px}
h1{font-size:1.6em;border-bottom:2px solid #4a6cf7;padding-bottom:10px;margin-bottom:24px;color:#1a1a2e}
h2{font-size:1.15em;margin-top:32px;margin-bottom:10px;color:#2d3a8c;border-left:4px solid #4a6cf7;padding-left:10px}
p{margin:12px 0}
ul,ol{margin:10px 0;padding-left:24px}
li{margin:6px 0}
.notice-box{background:#f0f4ff;border:1px solid #c5d0f5;border-radius:8px;padding:14px 18px;margin:20px 0;font-size:0.95em}
.contact-box{background:#f8f9fa;border-radius:8px;padding:16px 20px;margin-top:28px}
a{color:#4a6cf7;text-decoration:none}
a:hover{text-decoration:underline}
.last-updated{font-size:0.85em;color:#888;margin-top:32px;border-top:1px solid #eee;padding-top:12px}
</style>"""


# ──────────────────────────────────────────────────────────────────────────────
# 개인정보처리방침 (공통 — 테마 무관)
# ──────────────────────────────────────────────────────────────────────────────

def build_privacy_policy_html(blog_url: str = "", blog_name: str = "이 블로그") -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    style = _make_page_style()
    blog_link = f'<a href="{blog_url}" target="_blank">{blog_url}</a>' if blog_url else blog_name
    return f"""{style}
<h1>개인정보처리방침</h1>

<div class="notice-box">
  <strong>{blog_name}</strong>은(는) 방문자의 개인정보를 소중히 여깁니다.
  본 방침은 이 블로그가 어떤 정보를 수집하고 어떻게 사용하는지 설명합니다.
</div>

<h2>1. 수집하는 정보</h2>
<p>이 블로그는 방문자로부터 직접 개인정보를 수집하지 않습니다. 다만, 아래 서드파티 서비스가 자동으로 일부 정보를 수집할 수 있습니다.</p>
<ul>
  <li><strong>Google Analytics</strong>: 방문 페이지, 체류 시간, 유입 경로 등 익명 통계 데이터</li>
  <li><strong>Google AdSense</strong>: 광고 게재를 위한 쿠키 및 관심사 기반 데이터</li>
  <li><strong>Blogger (Google)</strong>: 댓글 작성 시 Google 계정 정보</li>
</ul>

<h2>2. 쿠키(Cookie) 사용</h2>
<p>이 블로그는 광고 및 통계 목적으로 쿠키를 사용합니다. 쿠키는 방문자의 브라우저에 저장되는 작은 텍스트 파일입니다.</p>
<p><strong>Google AdSense</strong>는 방문자의 관심사에 맞는 광고를 표시하기 위해 쿠키를 사용합니다.
광고 쿠키 비활성화를 원하시면 <a href="https://www.google.com/settings/ads" target="_blank" rel="noopener">Google 광고 설정</a>에서 변경하실 수 있습니다.</p>

<h2>3. 제3자 광고 (Google AdSense)</h2>
<p>이 블로그는 <strong>Google AdSense</strong>를 통해 광고를 게재합니다.
Google은 이 블로그 방문자에게 관심사 기반 광고를 표시하기 위해 쿠키를 사용할 수 있습니다.</p>
<ul>
  <li>Google 광고 사용 방식: <a href="https://policies.google.com/technologies/ads" target="_blank" rel="noopener">https://policies.google.com/technologies/ads</a></li>
  <li>개인정보 정책: <a href="https://policies.google.com/privacy" target="_blank" rel="noopener">https://policies.google.com/privacy</a></li>
</ul>

<h2>4. 외부 링크</h2>
<p>이 블로그의 글에는 외부 사이트 링크가 포함될 수 있습니다.
외부 사이트의 개인정보처리방침은 해당 사이트에서 확인하시기 바랍니다.
이 블로그는 외부 사이트의 콘텐츠나 정책에 대해 책임지지 않습니다.</p>

<h2>5. 제휴 링크 (Affiliate Links)</h2>
<p>일부 게시물에는 제휴 링크가 포함될 수 있으며, 해당 링크를 통해 구매 시 소정의 수수료가 지급될 수 있습니다.
이는 독자에게 추가 비용을 발생시키지 않습니다. 제휴 관계가 있는 경우 글 내에 명시합니다.</p>

<h2>6. 방침 변경</h2>
<p>본 개인정보처리방침은 관련 법령 또는 서비스 변경에 따라 업데이트될 수 있습니다.
변경 시 이 페이지를 통해 공지합니다.</p>

<h2>7. 문의</h2>
<div class="contact-box">
  개인정보 관련 문의사항이 있으시면 블로그 댓글로 남겨주세요.<br>
  <strong>블로그</strong>: {blog_link}
</div>

<p class="last-updated">최종 업데이트: {today}</p>"""


# ──────────────────────────────────────────────────────────────────────────────
# About 페이지 — 테마별 맞춤 콘텐츠
# ──────────────────────────────────────────────────────────────────────────────

def build_about_html(blog_url: str = "", blog_name: str = "이 블로그", theme: str = "general") -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    style = _make_page_style()
    blog_link = f'<a href="{blog_url}" target="_blank">{blog_url}</a>' if blog_url else blog_name

    if theme == "finance":
        body = f"""
<h1>블로그 소개</h1>

<div class="notice-box">
  안녕하세요! <strong>{blog_name}</strong>에 오신 것을 환영합니다 📈<br>
  국내외 금융·경제 뉴스를 빠르고 정확하게 정리해 드리는 금융 전문 블로그입니다.
</div>

<h2>이 블로그에 대해</h2>
<p>복잡한 금융 시장의 움직임을 누구나 쉽게 이해할 수 있도록 정리합니다.
매일 쏟아지는 경제 뉴스와 시장 데이터를 핵심만 추려 제공하고,
개인 투자자가 알아야 할 정보를 실용적인 관점에서 분석합니다.</p>
<p>주식·ETF·채권·코인·부동산 등 다양한 자산군의 동향을 다루며,
정책 금리·환율·물가 등 거시경제 지표도 꾸준히 팔로우합니다.</p>

<h2>주로 다루는 주제</h2>
<ul>
  <li>📰 <strong>금융 뉴스</strong>: 국내외 주요 경제 뉴스 요약 및 분석</li>
  <li>📊 <strong>주식·ETF</strong>: 국내외 주요 종목 및 ETF 동향</li>
  <li>🏦 <strong>거시경제</strong>: 금리·환율·물가·GDP 등 핵심 지표 해설</li>
  <li>💰 <strong>재테크 전략</strong>: 소액 투자자를 위한 자산 배분·절세 팁</li>
  <li>📉 <strong>시장 리스크</strong>: 글로벌 리스크 요인 모니터링</li>
  <li>🏠 <strong>부동산·대출</strong>: 금리 변동에 따른 부동산 시장 흐름</li>
</ul>

<h2>콘텐츠 작성 원칙</h2>
<p>본 블로그는 공개된 뉴스·공시·통계 자료를 바탕으로 콘텐츠를 작성합니다.
투자 판단에 참고할 수 있는 정보를 제공하되, <strong>투자 권유나 전문 재무 조언을 대체하지 않습니다.</strong>
모든 투자 결정은 독자 본인의 판단과 책임 하에 이루어져야 합니다.</p>

<h2>면책 고지</h2>
<p>이 블로그에 게재된 내용은 <strong>정보 제공 목적</strong>으로만 작성됩니다.
주식·ETF·코인 등 금융 상품 관련 내용은 공개된 정보를 바탕으로 작성한 것이며,
전문 투자 조언을 대체하지 않습니다. 이 블로그의 내용을 참고한 투자 결정으로 인한
손실이나 피해에 대해 법적 책임을 지지 않습니다.</p>

<h2>광고 및 제휴 관계 고지</h2>
<p>이 블로그는 <strong>Google AdSense</strong>를 통해 광고 수익을 얻습니다.
일부 글에는 제휴 링크가 포함될 수 있으며, 해당 경우 글 내에 명시합니다.
광고·제휴 수익은 더 좋은 금융 정보 콘텐츠 제작에 사용됩니다.</p>

<h2>문의</h2>
<div class="contact-box">
  오류 정정·제보·협업 제안은 댓글로 남겨주세요.<br>
  모든 댓글을 직접 확인하고 성실하게 답변드립니다.<br><br>
  <strong>블로그</strong>: {blog_link}
</div>

<p class="last-updated">작성: {today}</p>"""

    elif theme == "lifestyle":
        body = f"""
<h1>블로그 소개</h1>

<div class="notice-box">
  안녕하세요! <strong>{blog_name}</strong>에 오신 것을 환영합니다 ✈️⚽🎬<br>
  여행·스포츠·연예 분야의 생생한 정보와 솔직한 이야기를 담는 라이프스타일 블로그입니다.
</div>

<h2>이 블로그에 대해</h2>
<p>일상을 더 풍요롭게 만드는 이야기를 씁니다.
국내외 여행지 정보, 스포츠 경기 분석·결과, 연예·드라마·영화 리뷰까지
다양한 라이프스타일 콘텐츠를 한 곳에서 만나보실 수 있습니다.</p>
<p>직접 다녀온 여행지의 솔직한 후기, 경기를 보며 느낀 스포츠 이야기,
그리고 요즘 화제의 드라마·영화 이야기를 즐겁게 풀어냅니다.</p>

<h2>주로 다루는 주제</h2>
<ul>
  <li>✈️ <strong>국내 여행</strong>: 숨겨진 명소·맛집·숙소 솔직 후기</li>
  <li>🌏 <strong>해외 여행</strong>: 항공권·호텔·패키지 정보 및 현지 체험</li>
  <li>⚽ <strong>스포츠</strong>: 축구·야구·농구 등 주요 경기 결과 및 분석</li>
  <li>🏆 <strong>스포츠 이슈</strong>: 선수 이적·대회 소식·랭킹 업데이트</li>
  <li>🎬 <strong>드라마·영화</strong>: 국내외 인기 작품 리뷰 및 등장인물 분석</li>
  <li>🎵 <strong>연예·K-POP</strong>: 아이돌·배우 소식, 음반·공연 정보</li>
</ul>

<h2>콘텐츠 작성 원칙</h2>
<p>직접 경험하거나 공신력 있는 출처를 통해 확인한 정보를 씁니다.
여행 후기는 실제 방문 기록을 기반으로 하며, 스포츠·연예 정보는 공식 발표와
신뢰할 수 있는 매체를 참고합니다. 협찬·광고 콘텐츠는 반드시 명시합니다.</p>

<h2>면책 고지</h2>
<p>이 블로그의 여행 정보·가격·운영 시간 등은 변경될 수 있습니다.
방문 전에 공식 채널에서 최신 정보를 반드시 확인하시기 바랍니다.
본 블로그는 여행·스포츠·연예 콘텐츠를 정보 제공 목적으로 제공하며,
이를 참고한 결정으로 발생한 불이익에 대해 법적 책임을 지지 않습니다.</p>

<h2>광고 및 제휴 관계 고지</h2>
<p>이 블로그는 <strong>Google AdSense</strong>를 통해 광고 수익을 얻습니다.
일부 글에는 제휴 링크(숙소·항공권·쇼핑몰 등)가 포함될 수 있으며,
해당 경우 글 내에 명시합니다. 제휴 링크 클릭·구매 시 소정의 수수료가 지급되며
독자에게 추가 비용은 발생하지 않습니다.</p>

<h2>문의</h2>
<div class="contact-box">
  여행 정보 문의·협업 제안·오류 제보는 댓글로 남겨주세요.<br>
  모든 댓글을 직접 확인하고 성실하게 답변드립니다.<br><br>
  <strong>블로그</strong>: {blog_link}
</div>

<p class="last-updated">작성: {today}</p>"""

    else:  # general
        body = f"""
<h1>블로그 소개</h1>

<div class="notice-box">
  안녕하세요! <strong>{blog_name}</strong>에 오신 것을 환영합니다 😊<br>
  재테크, 건강, 생활 정보를 직접 경험하고 솔직하게 정리해서 올리는 공간입니다.
</div>

<h2>이 블로그에 대해</h2>
<p>저는 평범한 30대 직장인입니다. 매달 월급은 들어오는데 어디로 가는지 모르는 상황이 답답해서
재테크를 공부하기 시작했어요. 건강도 마찬가지예요. 운동도 해보고, 식단도 바꿔보고,
영양제도 직접 써봤습니다.</p>
<p>인터넷에 정보는 넘쳐나는데 막상 제 상황에 딱 맞는 글이 없어서 직접 정리하기로 했습니다.
검색으로 찾은 정보를 복붙하는 게 아니라, <strong>제가 직접 해보고 느낀 것을 솔직하게 씁니다.</strong></p>

<h2>주로 다루는 주제</h2>
<ul>
  <li>💰 <strong>재테크·투자</strong>: ETF, 배당주, 절세 방법 — 소액으로 직접 해본 것 위주</li>
  <li>🏥 <strong>건강·생활</strong>: 직접 해본 다이어트, 영양제, 건강검진 결과 해석법</li>
  <li>💻 <strong>AI·기술</strong>: 업무에 실제로 쓰는 AI 툴 비교·활용법</li>
  <li>📋 <strong>세금·법률</strong>: 직장인·프리랜서가 알아두면 좋은 절세·법률 상식</li>
  <li>🛍️ <strong>부업·수익화</strong>: 직접 시도해본 부업 솔직 후기</li>
</ul>

<h2>면책 고지</h2>
<p>이 블로그의 글은 <strong>정보 제공 목적</strong>으로만 작성됩니다.
투자, 법률, 세무, 의료 관련 내용은 개인의 경험과 공개된 정보를 바탕으로 작성한 것이며,
전문적인 조언을 대체하지 않습니다.</p>

<h2>광고 및 제휴 관계 고지</h2>
<p>이 블로그는 <strong>Google AdSense</strong>를 통해 광고 수익을 얻습니다.
일부 글에는 제휴 링크가 포함될 수 있으며, 해당 경우 글 내에 명시합니다.</p>

<h2>문의</h2>
<div class="contact-box">
  글 내용에 오류가 있거나 협업 제안이 있으시면 댓글로 남겨주세요.<br>
  모든 댓글은 직접 확인하고 성실하게 답변드립니다.<br><br>
  <strong>블로그</strong>: {blog_link}
</div>

<p class="last-updated">작성: {today}</p>"""

    return style + body


# ──────────────────────────────────────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────────────────────────────────────

def create_required_pages(blog_cfg: dict | None = None) -> dict:
    """
    AdSense 심사 필수 페이지(개인정보처리방침·소개)를 Blogger에 생성/업데이트합니다.

    Args:
        blog_cfg: BLOGS_CONFIG 항목 dict. None이면 .env 기본값 사용.
    Returns:
        {"privacy_policy": url|None, "about": url|None}
    """
    results = {"privacy_policy": None, "about": None}

    blog_id   = _get_blog_id(blog_cfg)
    blog_name = (blog_cfg or {}).get("name") or "이 블로그"
    blog_url  = (blog_cfg or {}).get("url") or ""
    theme     = _detect_theme(blog_cfg or {})

    logger.info(f"페이지 생성 대상: {blog_name} (id={blog_id}, theme={theme})")

    token = _get_access_token(blog_cfg)
    if not token:
        logger.error("액세스 토큰 발급 실패 — 페이지 생성 중단")
        return results

    existing_pages = _list_existing_pages(token, blog_id)
    logger.info(f"기존 Blogger 페이지 {len(existing_pages)}개 확인")

    pages = [
        ("개인정보처리방침", build_privacy_policy_html(blog_url, blog_name), "privacy_policy"),
        ("블로그 소개",     build_about_html(blog_url, blog_name, theme),   "about"),
    ]

    for title, html, key in pages:
        result = _create_or_update_page(token, blog_id, title, html, existing_pages)
        if result:
            results[key] = result.get("url")
        else:
            logger.error(f"'{title}' 페이지 생성 실패")

    return results


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")
    urls = create_required_pages()
    print("\n=== 생성된 페이지 ===")
    for k, v in urls.items():
        print(f"  {k}: {v or '실패'}")
