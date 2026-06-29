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

def _score_title_relevance(img: dict, query: str) -> float:
    """이미지 제목·URL과 쿼리 단어의 겹침 비율 (0~1). 관련성 순위 정렬에 사용."""
    query_words = set(re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', query.lower()))
    if not query_words:
        return 0.0
    haystack = (img.get("title", "") + " " + img.get("url", "")).lower()
    title_words = set(re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', haystack))
    return len(query_words & title_words) / len(query_words)


def _fetch_best_image(
    query: str,
    naver_client_id: str = "",
    naver_client_secret: str = "",
    n_candidates: int = 4,
) -> dict | None:
    """단일 쿼리로 후보 이미지 여러 개를 가져와 제목 관련성이 가장 높은 것을 반환합니다."""
    candidates: list[dict] = []
    if naver_client_id and naver_client_secret:
        candidates = _naver_images(query, n_candidates, naver_client_id, naver_client_secret)
    if not candidates:
        candidates = _ddg_images(query, n_candidates)
    if not candidates:
        candidates = _wikimedia_images(query, n_candidates)
    if not candidates:
        return None
    # 제목 관련성 점수가 가장 높은 후보 선택 (동점 시 API 기본 순위 존중)
    return max(candidates, key=lambda img: _score_title_relevance(img, query))


def _filter_relevant_images(
    images: list[dict],
    keyword: str,
    article_plain_text: str,
) -> list[dict]:
    """
    Claude를 사용해 글 내용과 관련 없는 이미지를 제거합니다.
    API 오류 시 모두 허용(기본 통과)하여 자동화를 중단시키지 않습니다.
    """
    if not images:
        return images
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        img_list = "\n".join(
            f"{i + 1}. 검색어={img.get('search_query', '')} / 제목={img.get('title', '')}"
            for i, img in enumerate(images)
        )
        # 본문 앞뒤 각 400자 → 글 전체 주제와 마지막 섹션 주제를 모두 커버
        summary = article_plain_text[:400]
        if len(article_plain_text) > 800:
            summary += " ... " + article_plain_text[-200:]

        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"블로그 주제: {keyword}\n"
                    f"글 내용 요약: {summary}\n\n"
                    f"아래 각 이미지의 검색어와 제목을 보고, 이 블로그 글의 시각적 자료로 "
                    f"적합한 이미지 번호만 쉼표로 나열하세요.\n"
                    f"기준: 글 주제·섹션 내용과 직접 관련된 이미지만 포함. "
                    f"키워드와 무관하거나 전혀 다른 주제의 이미지는 제외.\n"
                    f"모두 관련 없으면 '없음'.\n\n"
                    f"{img_list}\n\n"
                    "번호만 답 (예: 1,3 또는 없음):"
                ),
            }],
        )
        answer = msg.content[0].text.strip()
        logger.debug(f"이미지 관련성 평가 결과: {answer}")

        # '없음' 변형 처리
        if re.search(r'^없음[\.!,]?$', answer, re.IGNORECASE) or answer.lower() in ("none", "없음"):
            logger.info("이미지 관련성 검증: 관련 이미지 없음 — 전체 제거")
            return []

        keep = set()
        for part in re.split(r'[,\s]+', answer.replace(".", "")):
            if part.isdigit():
                keep.add(int(part) - 1)

        filtered = [img for i, img in enumerate(images) if i in keep]
        removed = len(images) - len(filtered)
        if removed:
            logger.info(f"이미지 관련성 검증: {removed}개 제거, {len(filtered)}개 유지")
        # 파싱 결과가 비어있으면 (인덱스 오류 포함) 원본 반환
        if not filtered:
            logger.debug("이미지 관련성 검증 파싱 실패 또는 범위 초과 — 원본 유지")
            return images
        return filtered

    except Exception as e:
        logger.debug(f"이미지 관련성 검증 오류 (기본 허용): {e}")
        return images


def fetch_images_for_queries(
    queries: list[str],
    naver_client_id: str = "",
    naver_client_secret: str = "",
    article_plain_text: str = "",
    keyword: str = "",
) -> list[dict]:
    """섹션별 쿼리 목록에 맞춰 이미지를 검색(후보 4개 중 관련성 최고 선택)하고 Claude로 최종 검증합니다."""
    images = []
    for query in queries:
        img = _fetch_best_image(query, naver_client_id, naver_client_secret, n_candidates=4)
        if img:
            img["search_query"] = query
            img["alt_text"] = query if len(query) <= 50 else query[:50].rsplit(" ", 1)[0]
            score = _score_title_relevance(img, query)
            logger.info(f"이미지 수집 성공: '{query}' → 제목='{img.get('title','')[:40]}' (관련성={score:.2f})")
        else:
            logger.warning(f"이미지 없음: '{query}'")
        if img:
            images.append(img)

    # Claude로 최종 관련성 검증 (article_plain_text 제공 시)
    if images and article_plain_text:
        images = _filter_relevant_images(images, keyword or queries[0], article_plain_text)

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

    def _alt(img: dict, fallback: str) -> str:
        return img.get("alt_text") or img.get("search_query", fallback)

    # ① 첫 번째 이미지: 첫 <p>...</p> 바로 다음
    first_p = re.search(r'(</p>)', content, re.IGNORECASE)
    if first_p:
        try:
            idx, img = next(img_iter)
            img_html = _make_img_html(img, _alt(img, keyword), img.get("title", ""))
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
            img_html = _make_img_html(
                img,
                _alt(img, f"{keyword} 관련 이미지 {idx + 1}"),
                img.get("title", ""),
            )
            actual_pos = pos + offset
            content = content[:actual_pos] + img_html + content[actual_pos:]
            offset += len(img_html)
        except StopIteration:
            break

    return content
