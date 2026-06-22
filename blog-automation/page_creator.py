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


def _get_access_token() -> str | None:
    from config import BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN
    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": BLOGGER_CLIENT_ID,
            "client_secret": BLOGGER_CLIENT_SECRET,
            "refresh_token": BLOGGER_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"토큰 요청 오류: {e}")
    return None


def _list_existing_pages(token: str, blog_id: str) -> list[dict]:
    """기존 Blogger 페이지 목록을 가져옵니다."""
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
    """Blogger 페이지를 생성하거나 기존 페이지를 업데이트합니다."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"title": title, "content": content}

    # 같은 제목의 페이지가 있으면 업데이트
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
# 페이지 HTML 생성
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


def build_privacy_policy_html(blog_url: str = "https://hoguwhat1.blogspot.com") -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    style = _make_page_style()
    return f"""{style}
<h1>개인정보처리방침</h1>

<div class="notice-box">
  이 블로그는 방문자의 개인정보를 소중히 여깁니다.
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
<p><strong>Google AdSense</strong>는 방문자의 관심사에 맞는 광고를 표시하기 위해 쿠키를 사용합니다. 광고 쿠키 비활성화를 원하시면 <a href="https://www.google.com/settings/ads" target="_blank" rel="noopener">Google 광고 설정</a>에서 변경하실 수 있습니다.</p>

<h2>3. 제3자 광고 (Google AdSense)</h2>
<p>이 블로그는 <strong>Google AdSense</strong>를 통해 광고를 게재합니다. Google은 이 블로그 방문자에게 관심사 기반 광고를 표시하기 위해 쿠키를 사용할 수 있습니다.</p>
<ul>
  <li>Google의 광고 사용 방식: <a href="https://policies.google.com/technologies/ads" target="_blank" rel="noopener">https://policies.google.com/technologies/ads</a></li>
  <li>개인정보 정책: <a href="https://policies.google.com/privacy" target="_blank" rel="noopener">https://policies.google.com/privacy</a></li>
</ul>

<h2>4. 외부 링크</h2>
<p>이 블로그의 글에는 외부 사이트 링크가 포함될 수 있습니다. 외부 사이트의 개인정보처리방침은 해당 사이트에서 확인하시기 바랍니다. 이 블로그는 외부 사이트의 콘텐츠나 정책에 대해 책임지지 않습니다.</p>

<h2>5. 제휴 링크 (Affiliate Links)</h2>
<p>일부 게시물에는 제휴 링크가 포함될 수 있으며, 해당 링크를 통해 구매 시 소정의 수수료가 지급될 수 있습니다. 이는 독자에게 추가 비용을 발생시키지 않습니다. 제휴 관계가 있는 경우 글 내에 명시합니다.</p>

<h2>6. 방침 변경</h2>
<p>본 개인정보처리방침은 관련 법령 또는 서비스 변경에 따라 업데이트될 수 있습니다. 변경 시 이 페이지를 통해 공지합니다.</p>

<h2>7. 문의</h2>
<div class="contact-box">
  개인정보 관련 문의사항이 있으시면 블로그 댓글 또는 아래 연락처로 문의해 주세요.<br>
  <strong>블로그</strong>: <a href="{blog_url}" target="_blank">{blog_url}</a>
</div>

<p class="last-updated">최종 업데이트: {today}</p>"""


def build_about_html(blog_url: str = "https://hoguwhat1.blogspot.com") -> str:
    today = datetime.now().strftime("%Y년 %m월 %d일")
    style = _make_page_style()
    return f"""{style}
<h1>블로그 소개</h1>

<div class="notice-box">
  안녕하세요! 이 블로그에 오신 것을 환영합니다 😊<br>
  재테크, 건강, 생활 정보를 직접 경험하고 솔직하게 정리해서 올리는 공간입니다.
</div>

<h2>이 블로그에 대해</h2>
<p>저는 평범한 30대 직장인입니다. 매달 월급은 들어오는데 어디로 가는지 모르는 상황이 답답해서 재테크를 공부하기 시작했어요. 건강도 마찬가지예요. 운동도 해보고, 식단도 바꿔보고, 영양제도 직접 써봤습니다.</p>
<p>인터넷에 정보는 넘쳐나는데 막상 제 상황에 딱 맞는 글이 없어서 직접 정리하기로 했습니다. 검색으로 찾은 정보를 복붙하는 게 아니라, <strong>제가 직접 해보고 느낀 것을 솔직하게 씁니다.</strong></p>

<h2>주로 다루는 주제</h2>
<ul>
  <li>💰 <strong>재테크·투자</strong>: ETF, 배당주, 절세 방법 — 소액으로 직접 해본 것 위주</li>
  <li>🏥 <strong>건강·생활</strong>: 직접 해본 다이어트, 영양제, 건강검진 결과 해석법</li>
  <li>💻 <strong>AI·기술</strong>: 업무에 실제로 쓰는 AI 툴 비교·활용법</li>
  <li>📋 <strong>세금·법률</strong>: 직장인·프리랜서가 알아두면 좋은 절세·법률 상식</li>
  <li>🛍️ <strong>부업·수익화</strong>: 직접 시도해본 부업 솔직 후기</li>
</ul>

<h2>글 쓰는 방식</h2>
<p>저는 전문가가 아닙니다. 하지만 똑같은 상황에서 먼저 해본 사람으로서, 어디서 막혔는지·어떤 게 실제로 됐는지를 솔직하게 씁니다. 전문적인 투자·법률·의료 조언은 반드시 해당 분야 전문가에게 확인하세요.</p>
<p>글에 쓰인 통계나 정보는 공신력 있는 출처를 인용하려고 노력하지만, 시간이 지나면 달라질 수 있습니다. 중요한 결정을 내리기 전에 최신 정보를 다시 확인해 주세요.</p>

<h2>면책 고지</h2>
<p>이 블로그의 글은 <strong>정보 제공 목적</strong>으로만 작성됩니다. 투자, 법률, 세무, 의료 관련 내용은 개인의 경험과 공개된 정보를 바탕으로 작성한 것이며, 전문적인 조언을 대체하지 않습니다. 이 블로그의 내용을 참고한 결정으로 인한 손실이나 피해에 대해 책임지지 않습니다.</p>

<h2>광고 및 제휴 관계 고지</h2>
<p>이 블로그는 <strong>Google AdSense</strong>를 통해 광고 수익을 얻습니다. 일부 글에는 제휴 링크가 포함될 수 있으며, 해당 경우 글 내에 명시합니다. 광고·제휴 수익은 블로그 운영 비용과 더 좋은 콘텐츠 제작에 사용됩니다.</p>

<h2>문의</h2>
<div class="contact-box">
  글 내용에 오류가 있거나 협업 제안이 있으시면 댓글로 남겨주세요.<br>
  모든 댓글은 직접 확인하고 성실하게 답변드립니다.<br><br>
  <strong>블로그</strong>: <a href="{blog_url}" target="_blank">{blog_url}</a>
</div>

<p class="last-updated">작성: {today}</p>"""


# ──────────────────────────────────────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────────────────────────────────────

def create_required_pages(blog_url: str = "https://hoguwhat1.blogspot.com") -> dict:
    """
    AdSense 심사 필수 페이지(개인정보처리방침·소개)를 Blogger에 생성/업데이트합니다.
    Returns: {"privacy_policy": url|None, "about": url|None}
    """
    from config import BLOGGER_BLOG_ID
    results = {"privacy_policy": None, "about": None}

    token = _get_access_token()
    if not token:
        logger.error("액세스 토큰 발급 실패 — 페이지 생성 중단")
        return results

    existing_pages = _list_existing_pages(token, BLOGGER_BLOG_ID)
    logger.info(f"기존 Blogger 페이지 {len(existing_pages)}개 확인")

    pages = [
        ("개인정보처리방침", build_privacy_policy_html(blog_url), "privacy_policy"),
        ("블로그 소개", build_about_html(blog_url), "about"),
    ]

    for title, html, key in pages:
        result = _create_or_update_page(token, BLOGGER_BLOG_ID, title, html, existing_pages)
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
