"""
이미지 자동 검색 & 삽입 모듈
- DuckDuckGo 이미지 검색 (API 키 불필요)
- 네이버 이미지 검색 (NAVER_CLIENT_ID 설정 시 우선 사용)
- Wikimedia Commons (폴백)
"""

import html
import re
import logging
import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


# ──────────────────────────────────────────────────────────────────────────────
# 이미지 검색 소스들
# ──────────────────────────────────────────────────────────────────────────────

def _ddg_images(keyword: str, count: int) -> list[dict]:
    """DuckDuckGo 이미지 검색 (API 키 불필요)."""
    try:
        # 1단계: vqd 토큰 획득
        r = requests.get(
            "https://duckduckgo.com/",
            params={"q": keyword, "iax": "images", "ia": "images"},
            headers=_HEADERS,
            timeout=12,
        )
        vqd = (re.search(r'vqd="([^"]+)"', r.text) or
               re.search(r"vqd='([^']+)'", r.text) or
               re.search(r'vqd-5="([^"]+)"', r.text) or
               re.search(r"vqd-5='([^']+)'", r.text))
        if not vqd:
            return []

        # 2단계: 이미지 목록 요청
        jr = requests.get(
            "https://duckduckgo.com/i.js",
            params={"q": keyword, "o": "json", "vqd": vqd.group(1), "f": ",,,,,", "p": "1"},
            headers={**_HEADERS, "Referer": "https://duckduckgo.com/"},
            timeout=12,
        )
        images = []
        for item in jr.json().get("results", []):
            url = item.get("image", "")
            if not re.search(r"\.(jpe?g|png|webp)", url, re.I):
                continue
            if item.get("width", 0) < 400:
                continue
            images.append({
                "url": url,
                "title": item.get("title", keyword),
                "width": item.get("width", 800),
                "height": item.get("height", 450),
            })
            if len(images) >= count:
                break
        return images
    except Exception as e:
        logger.debug(f"DDG 이미지 검색 실패: {e}")
        return []


def _naver_images(keyword: str, count: int, client_id: str, client_secret: str) -> list[dict]:
    """네이버 이미지 검색 API."""
    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/image",
            params={"query": keyword, "display": count * 2, "sort": "sim", "filter": "large"},
            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
            timeout=10,
        )
        if r.status_code != 200:
            logger.debug(f"Naver 이미지 API 오류: HTTP {r.status_code}")
            return []
        images = []
        for item in r.json().get("items", []):
            link = item.get("link", "")
            if re.search(r"\.(jpe?g|png|webp)", link, re.I):
                try:
                    width = int(item.get("sizewidth") or 0)
                except (ValueError, TypeError):
                    width = 0
                try:
                    height = int(item.get("sizeheight") or 0)
                except (ValueError, TypeError):
                    height = 0
                images.append({
                    "url": link,
                    "title": re.sub(r"<[^>]+>", "", item.get("title", keyword)).strip(),
                    "width": width,
                    "height": height,
                })
            if len(images) >= count:
                break
        return images
    except Exception as e:
        logger.debug(f"Naver 이미지 검색 실패: {e}")
        return []


def _wikimedia_search_titles(keyword: str, count: int) -> list[str]:
    """Wikimedia Commons에서 파일 제목 목록을 반환합니다."""
    try:
        base = "https://commons.wikimedia.org/w/api.php"
        sr = requests.get(base, params={
            "action": "query", "list": "search", "srnamespace": 6,
            "srsearch": keyword, "srlimit": count * 3, "format": "json",
        }, headers=_HEADERS, timeout=10)
        if sr.status_code != 200:
            return []
        return [r["title"] for r in sr.json().get("query", {}).get("search", [])]
    except Exception as e:
        logger.debug(f"Wikimedia 검색 오류: {e}")
        return []


def _wikimedia_images(keyword: str, count: int) -> list[dict]:
    """Wikimedia Commons 이미지 (저작권 없는 공개 이미지). 한국어 키워드 실패 시 영어 단어로 재시도."""
    try:
        base = "https://commons.wikimedia.org/w/api.php"
        titles = _wikimedia_search_titles(keyword, count)

        # 한국어 키워드로 결과 없으면 영어 단순 변환 시도 (공백→ 언더스코어 제거 후 영단어 추출)
        if not titles:
            # 숫자/영어 단어만 추출해 영어 쿼리로 재시도
            en_keyword = " ".join(re.findall(r'[A-Za-z0-9]+', keyword))
            if en_keyword and en_keyword != keyword:
                titles = _wikimedia_search_titles(en_keyword, count)

        images = []
        for title in titles:
            ir = requests.get(base, params={
                "action": "query", "titles": title,
                "prop": "imageinfo", "iiprop": "url|size|mime", "format": "json",
            }, headers=_HEADERS, timeout=8)
            if ir.status_code != 200:
                continue
            for page in ir.json().get("query", {}).get("pages", {}).values():
                for info in page.get("imageinfo", []):
                    if info.get("mime", "").startswith("image/") and info.get("width", 0) >= 400:
                        images.append({
                            "url": info["url"],
                            "title": title.replace("File:", ""),
                            "width": info.get("width", 800),
                            "height": info.get("height", 450),
                        })
                        break
            if len(images) >= count:
                break
        return images
    except Exception as e:
        logger.debug(f"Wikimedia 이미지 검색 실패: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 통합 검색 & HTML 삽입
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_one_image(
    query: str,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> dict | None:
    """단일 쿼리로 이미지 1개를 검색합니다. Naver → DDG → Wikimedia 순."""
    if naver_client_id and naver_client_secret:
        imgs = _naver_images(query, 1, naver_client_id, naver_client_secret)
        if imgs:
            return imgs[0]
    imgs = _ddg_images(query, 1)
    if imgs:
        return imgs[0]
    imgs = _wikimedia_images(query, 1)
    if imgs:
        return imgs[0]
    return None


def fetch_images_for_queries(
    queries: list[str],
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """섹션별 쿼리 목록에 맞춰 이미지를 1개씩 검색합니다."""
    images = []
    for query in queries:
        img = _fetch_one_image(query, naver_client_id, naver_client_secret)
        if img:
            img["search_query"] = query
            images.append(img)
            logger.info(f"이미지 수집 성공: '{query}'")
        else:
            logger.warning(f"이미지 없음: '{query}'")
    return images




def _make_img_html(img: dict, alt: str, caption: str = "") -> str:
    """이미지 SEO 최적화 HTML 생성."""
    alt_safe = html.escape(alt, quote=True)
    caption_safe = html.escape(caption, quote=True)
    fig_style = "margin:2.5em auto;text-align:center;max-width:720px;"
    img_style = (
        "max-width:100%;height:auto;border-radius:10px;"
        "box-shadow:0 3px 14px rgba(0,0,0,0.13);display:block;margin:0 auto;"
    )
    cap_html = (
        f'<figcaption style="text-align:center;font-size:13px;color:#777;'
        f'margin-top:8px;font-style:italic;">{caption_safe}</figcaption>'
        if caption else ""
    )
    return (
        f'\n<figure style="{fig_style}">'
        f'\n  <img src="{img["url"]}" alt="{alt_safe}" title="{alt_safe}" '
        f'style="{img_style}" loading="lazy" decoding="async" width="720"/>'
        f'\n  {cap_html}'
        f'\n</figure>\n'
    )


def inject_images_into_content(content: str, images: list[dict], keyword: str) -> str:
    """
    블로그 본문 HTML에 이미지를 전략적으로 삽입합니다.
    - 첫 이미지: 도입부 첫 <p> 바로 다음
    - 나머지 이미지: 짝수 번째 <h2> 섹션 끝에 삽입
    """
    if not images:
        return content

    img_iter = iter(enumerate(images))

    # ① 첫 번째 이미지: 첫 <p>...</p> 바로 다음
    first_p = re.search(r'(</p>)', content, re.IGNORECASE)
    if first_p:
        try:
            idx, img = next(img_iter)
            alt = img.get("search_query", keyword)
            img_html = _make_img_html(img, alt, img.get("title", ""))
            content = content[:first_p.end()] + img_html + content[first_p.end():]
        except StopIteration:
            return content

    # ② 나머지 이미지: <h2> 태그 직전에 삽입 (섹션 사이 배치)
    h2_positions = [m.start() for m in re.finditer(r'<h2', content, re.IGNORECASE)]
    insert_positions = h2_positions[1::2]  # 2번째, 4번째, 6번째 H2 앞

    offset = 0
    for pos in insert_positions:
        try:
            idx, img = next(img_iter)
            alt = img.get("search_query", f"{keyword} 관련 이미지 {idx + 1}")
            img_html = _make_img_html(
                img,
                alt,
                img.get("title", ""),
            )
            actual_pos = pos + offset
            content = content[:actual_pos] + img_html + content[actual_pos:]
            offset += len(img_html)
        except StopIteration:
            break

    return content
