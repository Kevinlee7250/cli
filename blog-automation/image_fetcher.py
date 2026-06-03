"""
이미지 자동 검색 & 삽입 모듈
- DuckDuckGo 이미지 검색 (API 키 불필요)
- 네이버 이미지 검색 (NAVER_CLIENT_ID 설정 시 우선 사용)
- Wikimedia Commons (폴백)
"""

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
               re.search(r"vqd='([^']+)'", r.text))
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
        for r in jr.json().get("results", []):
            url = r.get("image", "")
            if not re.search(r"\.(jpe?g|png|webp)", url, re.I):
                continue
            if r.get("width", 0) < 400:
                continue
            images.append({
                "url": url,
                "title": r.get("title", keyword),
                "width": r.get("width", 800),
                "height": r.get("height", 450),
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
        images = []
        for item in r.json().get("items", []):
            link = item.get("link", "")
            if re.search(r"\.(jpe?g|png|webp)", link, re.I):
                images.append({
                    "url": item.get("thumbnail", link),
                    "title": re.sub(r"<[^>]+>", "", item.get("title", keyword)).strip(),
                    "width": int(item.get("sizewidth", 0) or 0),
                    "height": int(item.get("sizeheight", 0) or 0),
                })
            if len(images) >= count:
                break
        return images
    except Exception as e:
        logger.debug(f"Naver 이미지 검색 실패: {e}")
        return []


def _wikimedia_images(keyword: str, count: int) -> list[dict]:
    """Wikimedia Commons 이미지 (저작권 없는 공개 이미지)."""
    try:
        base = "https://commons.wikimedia.org/w/api.php"
        # 검색
        sr = requests.get(base, params={
            "action": "query", "list": "search", "srnamespace": 6,
            "srsearch": keyword, "srlimit": count * 3, "format": "json",
        }, headers=_HEADERS, timeout=10)
        titles = [r["title"] for r in sr.json().get("query", {}).get("search", [])]

        images = []
        for title in titles:
            ir = requests.get(base, params={
                "action": "query", "titles": title,
                "prop": "imageinfo", "iiprop": "url|size|mime", "format": "json",
            }, headers=_HEADERS, timeout=8)
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

def fetch_relevant_images(
    keyword: str,
    count: int = 3,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """키워드 관련 이미지를 검색합니다. 순서: Naver → DuckDuckGo → Wikimedia."""
    # 1순위: 네이버 (설정된 경우)
    if naver_client_id and naver_client_secret:
        imgs = _naver_images(keyword, count, naver_client_id, naver_client_secret)
        if imgs:
            logger.info(f"네이버 이미지 {len(imgs)}개 수집: '{keyword}'")
            return imgs

    # 2순위: DuckDuckGo
    imgs = _ddg_images(keyword, count)
    if imgs:
        logger.info(f"DuckDuckGo 이미지 {len(imgs)}개 수집: '{keyword}'")
        return imgs

    # 3순위: Wikimedia Commons
    imgs = _wikimedia_images(keyword, count)
    if imgs:
        logger.info(f"Wikimedia 이미지 {len(imgs)}개 수집: '{keyword}'")
        return imgs

    logger.warning(f"이미지 수집 실패: '{keyword}'")
    return []


def _make_img_html(img: dict, alt: str, caption: str = "") -> str:
    """이미지 SEO 최적화 HTML 생성."""
    fig_style = "margin:2.5em auto;text-align:center;max-width:720px;"
    img_style = (
        "max-width:100%;height:auto;border-radius:10px;"
        "box-shadow:0 3px 14px rgba(0,0,0,0.13);display:block;margin:0 auto;"
    )
    cap_html = (
        f'<figcaption style="text-align:center;font-size:13px;color:#777;'
        f'margin-top:8px;font-style:italic;">{caption}</figcaption>'
        if caption else ""
    )
    return (
        f'\n<figure style="{fig_style}">'
        f'\n  <img src="{img["url"]}" alt="{alt}" title="{alt}" '
        f'style="{img_style}" loading="lazy" decoding="async" width="720"/>'
        f'\n  {cap_html}'
        f'\n</figure>\n'
    )


def inject_images_into_content(html: str, images: list[dict], keyword: str) -> str:
    """
    블로그 본문 HTML에 이미지를 전략적으로 삽입합니다.
    - 첫 이미지: 도입부 첫 <p> 바로 다음
    - 나머지 이미지: 짝수 번째 <h2> 섹션 끝에 삽입
    """
    if not images:
        return html

    img_iter = iter(enumerate(images))

    # ① 첫 번째 이미지: 첫 <p>...</p> 바로 다음
    first_p = re.search(r'(</p>)', html, re.IGNORECASE)
    if first_p:
        try:
            idx, img = next(img_iter)
            img_html = _make_img_html(img, f"{keyword} 이미지", img.get("title", ""))
            html = html[:first_p.end()] + img_html + html[first_p.end():]
        except StopIteration:
            return html

    # ② 나머지 이미지: <h2> 태그 직전에 삽입 (섹션 사이 배치)
    # h2 인덱스 1, 3, 5 번째마다 (짝수 번째 섹션 전)
    h2_positions = [m.start() for m in re.finditer(r'<h2', html, re.IGNORECASE)]
    insert_positions = h2_positions[1::2]  # 2번째, 4번째, 6번째 H2 앞

    offset = 0
    for pos in insert_positions:
        try:
            idx, img = next(img_iter)
            img_html = _make_img_html(
                img,
                f"{keyword} 관련 이미지 {idx + 1}",
                img.get("title", ""),
            )
            actual_pos = pos + offset
            html = html[:actual_pos] + img_html + html[actual_pos:]
            offset += len(img_html)
        except StopIteration:
            break

    return html
