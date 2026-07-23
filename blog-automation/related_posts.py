"""
blog-automation/related_posts.py
관련 포스트 자동 추천 + 내부 링크 클러스터링 모듈.

기능:
  1. 관련 포스트 추천 (Jaccard + 키워드 유사도)
     - posts.json의 tags, keyword, title 기반 유사도 계산
     - 현재 포스트와 가장 유사한 상위 MAX_RELATED 개 추천
     - HTML 카드 섹션으로 반환 → _build_full_content에 삽입
  2. 링크 클러스터 빌드 (build_clusters)
     - 공통 태그 2개 이상인 포스트를 같은 클러스터로 묶음 (Union-Find)
     - docs/data/link_clusters.json 에 저장
     - get_cluster_siblings() 로 동일 클러스터 포스트 조회 가능

사용법:
    from related_posts import build_related_section, build_clusters

    # 업로드 시: 관련 포스트 HTML 섹션
    section = build_related_section(post_data, blog_config)

    # 배치: 클러스터 JSON 재빌드 (blog-cluster.yml 등에서 호출)
    build_clusters()
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
_ROOT         = Path(__file__).parent.parent
POSTS_JSON    = _ROOT / "docs" / "data" / "posts.json"
CLUSTERS_JSON = _ROOT / "docs" / "data" / "link_clusters.json"

# ── 파라미터 ──────────────────────────────────────────────────────────────────
MAX_RELATED      = 3      # 포스트당 관련 포스트 최대 수
MIN_SIMILARITY   = 0.025   # 유사도 최소 임계값 (이하 표시 안 함)
CLUSTER_MIN_TAGS = 2      # 같은 클러스터로 묶을 최소 공통 태그 수
TAG_WEIGHT       = 0.60   # 유사도: 태그 가중치
KEYWORD_WEIGHT   = 0.25   # 유사도: 키워드 가중치
TITLE_WEIGHT     = 0.15   # 유사도: 제목 unigram 가중치

_DEFAULT_BLOG_NAME = "오늘의 핫이슈"
_DEFAULT_BLOG_URL  = "https://hoguwhat1.blogspot.com"


# ── 포스트 인덱스 로드 ────────────────────────────────────────────────────────

def _load_posts() -> list[dict]:
    """posts.json 로드 (blogUrl 없는 항목 제외)"""
    if not POSTS_JSON.exists():
        logger.warning(f"posts.json 없음: {POSTS_JSON}")
        return []
    try:
        with open(POSTS_JSON, encoding="utf-8") as f:
            posts = json.load(f)
        return [p for p in posts if p.get("blogUrl") and p.get("title")]
    except Exception as e:
        logger.warning(f"posts.json 로드 실패: {e}")
        return []


# ── 유사도 계산 ───────────────────────────────────────────────────────────────

def _tag_set(post: dict) -> set[str]:
    """태그 + labels + keyword → 정규화된 집합"""
    combined = (
        list(post.get("tags") or [])
        + list(post.get("labels") or [])
        + ([post.get("keyword", "").strip()] if post.get("keyword") else [])
    )
    return {t.strip().lower().replace(" ", "") for t in combined if t.strip()}


def _keyword_tokens(post: dict) -> set[str]:
    """keyword + title → 2자 이상 토큰 집합"""
    text = " ".join([post.get("keyword") or "", post.get("title") or ""])
    return {
        t.strip().lower()
        for t in re.split(r'[\s\-—·,·()\[\]\/]+', text)
        if len(t.strip()) >= 2
    }


def _title_unigrams(post: dict) -> set[str]:
    """제목 단어 집합 (2자 이상)"""
    title = (post.get("title") or "").lower()
    return {w for w in re.split(r'\s+', title) if len(w) >= 2}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _similarity(src: dict, cand: dict) -> float:
    """종합 유사도 점수 (0.0 ~ 1.0)"""
    return (
        TAG_WEIGHT     * _jaccard(_tag_set(src),        _tag_set(cand))
        + KEYWORD_WEIGHT * _jaccard(_keyword_tokens(src),  _keyword_tokens(cand))
        + TITLE_WEIGHT   * _jaccard(_title_unigrams(src),  _title_unigrams(cand))
    )


# ── 관련 포스트 추천 ──────────────────────────────────────────────────────────

def get_related_posts(post_data: dict, top_n: int = MAX_RELATED) -> list[dict]:
    """
    현재 포스트와 가장 유사한 포스트 top_n 개 반환.
    반환: [{"title", "url", "description", "score", "tags"}, ...]
    """
    all_posts   = _load_posts()
    current_url = post_data.get("blogUrl") or ""
    current_id  = post_data.get("id") or ""

    scored: list[tuple[float, dict]] = []
    for p in all_posts:
        if p.get("blogUrl") == current_url or p.get("id") == current_id:
            continue
        score = _similarity(post_data, p)
        if score >= MIN_SIMILARITY:
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = []
    for score, p in scored[:top_n]:
        desc = p.get("metaDescription") or p.get("contentPreview") or ""
        if len(desc) > 80:
            desc = desc[:77] + "..."
        result.append({
            "title":       p.get("title", ""),
            "url":         p.get("blogUrl", ""),
            "description": desc,
            "score":       round(score, 4),
            "tags":        (p.get("tags") or [])[:3],
        })
    return result


# ── HTML 카드 섹션 ────────────────────────────────────────────────────────────

_SECTION_STYLE = (
    '<style>'
    '.rp-wrap{margin:40px 0 24px;padding:24px 20px;background:#f8fafc;'
    'border-radius:12px;border:1px solid #e2e8f0;}'
    '.rp-wrap h3{margin:0 0 16px;font-size:17px;font-weight:700;color:#1e293b;}'
    '.rp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;}'
    '.rp-card{display:flex;flex-direction:column;gap:6px;padding:14px 16px;'
    'background:#fff;border-radius:8px;border:1px solid #e2e8f0;'
    'text-decoration:none;color:inherit;transition:box-shadow .2s,transform .2s;}'
    '.rp-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.08);transform:translateY(-2px);}'
    '.rp-ctit{font-size:14px;font-weight:600;color:#0f172a;line-height:1.5;'
    'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}'
    '.rp-cdesc{font-size:12px;color:#64748b;line-height:1.6;'
    'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}'
    '.rp-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;}'
    '.rp-tag{font-size:11px;padding:2px 7px;background:#eff6ff;color:#3b82f6;'
    'border-radius:999px;font-weight:500;}'
    '@media(max-width:600px){.rp-grid{grid-template-columns:1fr;}}'
    '</style>'
)


def build_related_section(post_data: dict, blog_config: dict | None = None) -> str:
    """
    관련 포스트 HTML 카드 섹션 반환.
    관련 포스트가 없으면 빈 문자열 반환.
    """
    related = get_related_posts(post_data)
    if not related:
        logger.debug("관련 포스트 없음 — 섹션 생략")
        return ""

    cards = ""
    for r in related:
        tags_html = "".join(
            f'<span class="rp-tag">#{t}</span>' for t in r["tags"]
        )
        desc_html = (
            f'<span class="rp-cdesc">{r["description"]}</span>'
            if r["description"] else ""
        )
        cards += (
            f'<a href="{r["url"]}" class="rp-card" rel="noopener">'
            f'<span class="rp-ctit">{r["title"]}</span>'
            f'{desc_html}'
            f'<span class="rp-tags">{tags_html}</span>'
            f'</a>'
        )

    section = (
        f'{_SECTION_STYLE}'
        f'<div class="rp-wrap">'
        f'<h3>📖 관련 포스트</h3>'
        f'<div class="rp-grid">{cards}</div>'
        f'</div>\n'
    )
    logger.info(f"관련 포스트 {len(related)}개 섹션 생성")
    return section


# ── 링크 클러스터 빌드 ────────────────────────────────────────────────────────

class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank   = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def build_clusters(save: bool = True) -> dict:
    """
    모든 포스트를 태그 유사도 기준으로 클러스터링.

    공통 태그 수 >= CLUSTER_MIN_TAGS 이면 같은 클러스터로 Union.
    결과를 docs/data/link_clusters.json 에 저장.

    반환 형식:
    {
      "clusters": [{"id", "size", "representative_tags", "posts":[...]}, ...],
      "post_to_cluster": {"post_id": "cluster_000", ...},
      "total_posts": N,
      "total_clusters": M,
      "built_at": "ISO8601"
    }
    """
    posts = _load_posts()
    n = len(posts)
    if n == 0:
        logger.warning("posts.json 비어 있음 — 클러스터 생성 불가")
        return {}

    uf       = _UnionFind(n)
    tag_sets = [_tag_set(p) for p in posts]

    # Union-Find: 공통 태그 >= CLUSTER_MIN_TAGS 이면 연결
    for i in range(n):
        for j in range(i + 1, n):
            if len(tag_sets[i] & tag_sets[j]) >= CLUSTER_MIN_TAGS:
                uf.union(i, j)

    # 클러스터 그루핑
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)

    clusters         = []
    post_to_cluster: dict[str, str] = {}

    for cluster_idx, (_, members) in enumerate(
        sorted(groups.items(), key=lambda x: -len(x[1]))
    ):
        cluster_id = f"cluster_{cluster_idx:03d}"

        # 대표 태그: 멤버 태그 빈도 상위 5개
        tag_freq: dict[str, int] = defaultdict(int)
        for i in members:
            for t in tag_sets[i]:
                tag_freq[t] += 1
        rep_tags = sorted(tag_freq, key=lambda t: -tag_freq[t])[:5]

        post_list = [
            {
                "id":    posts[i].get("id", ""),
                "title": posts[i].get("title", ""),
                "url":   posts[i].get("blogUrl", ""),
                "tags":  (posts[i].get("tags") or [])[:5],
            }
            for i in sorted(members)
        ]
        for item in post_list:
            post_to_cluster[item["id"]] = cluster_id

        clusters.append({
            "id":                  cluster_id,
            "size":                len(members),
            "representative_tags": rep_tags,
            "posts":               post_list,
        })

    result = {
        "clusters":        clusters,
        "post_to_cluster": post_to_cluster,
        "total_posts":     n,
        "total_clusters":  len(clusters),
        "built_at":        datetime.now(timezone.utc).isoformat(),
    }

    if save:
        CLUSTERS_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(CLUSTERS_JSON, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(
            f"link_clusters.json 저장: "
            f"{len(clusters)}개 클러스터, {n}개 포스트"
        )

    return result


def get_cluster_siblings(post_data: dict) -> list[dict]:
    """
    현재 포스트와 같은 클러스터에 속한 포스트 목록 반환.
    link_clusters.json이 없으면 빈 리스트.
    """
    if not CLUSTERS_JSON.exists():
        return []
    try:
        with open(CLUSTERS_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"link_clusters.json 로드 실패: {e}")
        return []

    post_id    = post_data.get("id") or ""
    cluster_id = data.get("post_to_cluster", {}).get(post_id)
    if not cluster_id:
        return []

    current_url = post_data.get("blogUrl") or ""
    for cluster in data.get("clusters", []):
        if cluster["id"] == cluster_id:
            return [p for p in cluster["posts"] if p.get("url") != current_url]
    return []


# ── CLI 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if "--test-related" in sys.argv or len(sys.argv) == 1:
        posts = _load_posts()
        if posts:
            test_post = posts[0]
            print(f"\n📌 테스트: {test_post['title']}")
            related = get_related_posts(test_post)
            print(f"관련 포스트 {len(related)}개:")
            for r in related:
                print(f"  [{r['score']:.3f}] {r['title']}")
            html = build_related_section(test_post)
            print(f"\nHTML 섹션 길이: {len(html)}자")
            print(html[:400] + "..." if len(html) > 400 else html)

    if "--build-clusters" in sys.argv or len(sys.argv) == 1:
        result = build_clusters()
        print(f"\n✅ 클러스터 빌드 완료")
        print(f"   총 포스트: {result.get('total_posts', 0)}개")
        print(f"   총 클러스터: {result.get('total_clusters', 0)}개")
        for c in result.get("clusters", [])[:8]:
            size = c['size']
            tags = ', '.join(c['representative_tags'][:3])
            print(f"  [{c['id']}] {size}개 | 태그: {tags}")
            for p in c['posts'][:2]:
                print(f"    - {p['title'][:55]}")
