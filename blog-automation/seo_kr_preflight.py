"""선택형 한국어 SEO 발행 전 점검. 공식 순위 점수 또는 AdSense 승인 판정기가 아님."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse


class _ContentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.headings = []
        self.links = []
        self.images = []
        self._heading = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"h1", "h2", "h3"}:
            self._heading = [tag, []]
        elif tag == "a":
            self.links.append(attrs.get("href", ""))
        elif tag == "img":
            self.images.append(attrs.get("alt"))

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading is not None:
            self._heading[1].append(data)

    def handle_endtag(self, tag):
        if self._heading is not None and self._heading[0] == tag:
            self.headings.append((tag, " ".join(self._heading[1]).strip()))
            self._heading = None


def inspect_post(post_data: dict) -> dict:
    """순수 읽기 전용 점검; 외부 API 요청·게시·원문 변경 없음.

    blockers는 확인된 구조적 오류만 포함하며, 의학·금융 등 사실 검증은
    기존 프로젝트의 별도 품질 게이트에서 계속 수행해야 한다.
    """
    source = post_data.get("content") or ""
    title = str(post_data.get("title") or "").strip()
    keyword = str(post_data.get("keyword") or "").strip()
    meta = str(post_data.get("meta_description") or "").strip()
    parser = _ContentParser()
    parser.feed(source)
    text = re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip()
    blockers = []
    warnings = []

    if not title:
        blockers.append("제목이 없습니다.")
    if not text:
        blockers.append("본문이 없습니다.")
    if not keyword:
        warnings.append("핵심 키워드가 비어 검색 의도 일치 검토가 필요합니다.")
    elif keyword.casefold() not in (title + " " + text).casefold():
        warnings.append("제목·본문에서 핵심 검색어 직접 표현을 확인하지 못했습니다. 동의어도 검토하세요.")
    if not meta:
        warnings.append("메타 설명이 비어 있습니다.")
    if not any(tag == "h2" for tag, _ in parser.headings):
        warnings.append("H2 소제목이 없습니다. 글의 길이와 구조를 확인하세요.")
    if parser.headings:
        levels = [int(tag[1]) for tag, _ in parser.headings]
        if any(b > a + 1 for a, b in zip(levels, levels[1:])):
            warnings.append("제목 계층을 건너뛴 구간이 있습니다.")
    if any(not link or link.strip() == "#" or link.lower().startswith("javascript:") for link in parser.links):
        blockers.append("빈 링크 또는 안전하지 않은 링크가 있습니다.")
    if any(alt is None for alt in parser.images):
        warnings.append("ALT가 없는 이미지가 있습니다. 장식 이미지인지 확인하세요.")

    for url in re.findall(r'href\s*=\s*["\'](https?://[^"\']+)["\']', source, re.IGNORECASE):
        if not urlparse(url).netloc:
            blockers.append("형식이 잘못된 외부 링크가 있습니다.")
            break

    return {
        "status": "hold" if blockers else ("review" if warnings else "pass"),
        "blockers": blockers,
        "warnings": warnings,
        "metrics": {
            "character_count": len(text.replace(" ", "")),
            "heading_count": len(parser.headings),
            "link_count": len(parser.links),
            "image_count": len(parser.images),
        },
        "note": "한국어 SEO 점검용 참고 결과. 검색 노출·AdSense 승인 보장이 아닙니다.",
    }
