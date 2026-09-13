#!/usr/bin/env python3
"""사이트를 '소규모 정예'로 재편합니다 — 살릴 글을 고르고 나머지는 내립니다.

왜 이렇게 하나
─────────────
2026-09-12 전수 감사 결과 발행글 498편 중 **453편(91%)이 지어낸 경험담**이었고,
그중 236편은 날짜·금액까지 구체적으로 조작한 critical입니다. 깨끗한 글은
45편(9%)뿐입니다.

453편을 전부 리라이팅하는 선택지도 있었지만 택하지 않았습니다. 이 글들의
'가치'는 대부분 그 지어낸 구체성이었고, 그것을 걷어내면 남는 것은 평범한
일반론 453편입니다. 정직해지긴 하지만 "가치가 별로 없는 콘텐츠"라는 판정은
그대로입니다. AdSense는 500편을 요구하지 않습니다 — 쓸모 있는 20~30편을
요구합니다.

그래서 세 갈래로 나눕니다.

  keep      감사 통과 글. 손대지 않음
  rewrite   살릴 가치가 있는 글. 본문 리라이팅 대상
  unpublish 나머지. 임시저장(draft)으로 내림 — 삭제가 아니라 되돌릴 수 있음

무엇을 기준으로 살리나
────────────────────
점수는 "고쳤을 때 쓸 만한 글이 남는가"를 봅니다. 조작이 글의 뼈대인 글은
고쳐도 껍데기만 남으므로 살리지 않습니다.

핵심은 **문제 문단의 절대 개수가 아니라 밀도**입니다. 첫 판에서는 개수만
봤는데, 그러면 3,000자 드라마 회차 리뷰(문제 2개)가 4,900자 퇴직연금
가이드(문제 2개)를 이깁니다. 실제로 상위 10편이 전부 회차 리뷰로 채워졌고
5,000자짜리 반도체·채권·연금 글이 전부 내려가는 계획이 나왔습니다. AdSense
심사에서 그 조합은 정확히 반대 방향입니다. 그래서 1,000자당 문제 문단 수로
바꿨습니다.

  + 문제 문단 밀도가 낮다   (조작이 장식이지 뼈대가 아니다)
  + 분량이 넉넉하다         (걷어내도 남을 게 있다)
  + 정보형 글이다           (how_to·비교·분석·투자 — 검색 수요가 실재)
  + FAQ가 있다              (조사 기반 부분이 실재한다)
  − critical 이다           (지어낸 수치를 다시 써야 한다)
  − 회차 리뷰·근황 정리      (조작 문장을 걷어내면 줄거리 요약만 남는다)

블로그별로 상위 N편을 뽑습니다. AdSense는 사이트 단위로 심사하므로
한 블로그에 몰아주면 나머지 두 곳이 빈 사이트가 됩니다.

사용
────
  python curate_site.py --plan                    # 계획만 출력 (기본)
  python curate_site.py --plan --keep-per-blog 30 --min-score 50
  python curate_site.py --apply --limit 20        # 실제로 내리기 시작
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_HERE = os.path.dirname(os.path.abspath(__file__))
_DOCS_DATA = os.path.join(_HERE, "..", "docs", "data")
AUDIT_PATH = os.path.join(_DOCS_DATA, "experience_audit.json")
PLAN_PATH = os.path.join(_DOCS_DATA, "curation_plan.json")
PLAN_MD_PATH = os.path.join(_DOCS_DATA, "curation_plan.md")
RESULT_PATH = os.path.join(_DOCS_DATA, "curation_result.json")

DEFAULT_KEEP_PER_BLOG = 25

#: 이 점수 아래는 정원이 남아도 살리지 않습니다. 목표는 25편을 채우는 것이
#: 아니라 25편이 쓸 만한 것입니다 — 자리를 채우려고 회차 리뷰를 밀어 넣으면
#: 애초에 거절당한 그 사이트가 다시 만들어집니다.
DEFAULT_MIN_SCORE = 40


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _registry_index() -> dict:
    """URL → 레지스트리 메타(분량·FAQ·카테고리)."""
    raw = _load_json(os.path.join(_DOCS_DATA, "post_registry.json"), [])
    items = raw if isinstance(raw, list) else list(raw.values())
    out = {}
    for i in items:
        if isinstance(i, dict) and i.get("blogUrl"):
            out[i["blogUrl"].rstrip("/")] = i
    return out


#: 검색 수요가 실재하고, 조작 문장을 걷어내도 뼈대(제도·수치·절차)가 남는 유형.
#: news_analysis는 뺐습니다 — 레지스트리에서 "2026 기준금리 인상 체크리스트"와
#: "[1편] 김부장 첫인상 리뷰"에 같은 태그가 붙어 있어 신호가 되지 못합니다.
_HIGH_VALUE_TYPES = {"how_to", "comparison", "analysis", "investment"}

#: 회차 요약·연예인 근황. 분량이 있어도 남는 것은 줄거리 요약이라
#: "가치가 별로 없는 콘텐츠" 판정을 그대로 받습니다. 고쳐서 살릴 대상이 아닙니다.
_LOW_VALUE_TYPES = {"drama_review", "kpop_review", "sports_review", "review"}

#: articleType이 믿을 수 없어 제목으로도 봅니다. 이 글들은 "솔직 리뷰"라는
#: 주장 자체가 콘텐츠라서, 그 주장을 걷어내면 남는 것이 방영 정보뿐입니다.
_EPISODIC_TITLE = re.compile(
    r"(첫인상|등장인물|관계도|출연진|결말|근황|줄거리|명대사|스포일러"
    r"|\d+\s*화\b|몇\s*부작|시청률|재방송)")


def salvage_score(audit_item: dict, meta: dict, title: str = "") -> tuple[int, list[str]]:
    """고쳤을 때 쓸 만한 글이 남을지 점수화합니다. (점수, 사유)

    레지스트리에 없는 글(2026-07-20 이전 발행분)은 분량·유형을 알 수 없습니다.
    그 경우 메타 기반 가점을 주지 않고 문제 문단 개수만 봅니다 — 모르는 것을
    장점으로 세면 오래된 글이 부당하게 유리해집니다.
    """
    score, why = 0, []
    sev = audit_item.get("severity", "high")
    hits = audit_item.get("body_hit_count", 0)
    wc = meta.get("wordCount") or 0

    # ── 1. 수선 범위 — 문제 문단이 글에서 차지하는 비중 (가장 무거운 항목)
    if wc:
        density = hits / (wc / 1000.0)          # 1,000자당 문제 문단 수
        if density <= 0.4:
            score += 40; why.append(f"{wc}자에 문제 문단 {hits}개 — 국소적")
        elif density <= 0.8:
            score += 20; why.append(f"{wc}자에 문제 문단 {hits}개")
        elif density <= 1.5:
            why.append(f"{wc}자에 문제 문단 {hits}개 — 넓게 퍼짐")
        else:
            score -= 30; why.append(f"{wc}자에 문제 문단 {hits}개 — 조작이 글의 뼈대")
    else:
        # 분량·유형을 모르는 옛 글. 같은 조건이라도 확인된 글보다 낮게 둡니다 —
        # 검증할 수 없는 글을 검증된 4,900자 투자 가이드 위에 올리면 안 됩니다.
        if hits <= 2:
            score += 15; why.append(f"문제 문단 {hits}개 (분량 미상)")
        elif hits <= 5:
            why.append(f"문제 문단 {hits}개 (분량 미상)")
        else:
            score -= 25; why.append(f"문제 문단 {hits}개 — 글 전반에 퍼짐")

    # ── 2. 조작의 성격
    if sev == "medium":
        score += 25; why.append("제목 표현만 문제")
    elif sev == "high":
        score += 10
    else:
        score -= 20; why.append("지어낸 수치 포함")

    # ── 3. 걷어내고 남는 글의 가치
    if wc >= 4500:
        score += 25; why.append(f"{wc}자")
    elif wc >= 3500:
        score += 15; why.append(f"{wc}자")
    elif wc and wc < 3000:
        score -= 20; why.append(f"{wc}자 — 걷어내면 남는 게 적음")

    if (meta.get("faqCount") or 0) >= 3:
        score += 10; why.append("FAQ 보유")

    atype = meta.get("articleType") or ""
    if atype in _HIGH_VALUE_TYPES:
        score += 20; why.append(f"정보형({atype})")
    elif atype == "travel_guide":
        # 여행 가이드는 정보형이지만 조작이 '내가 가봤다'에 몰려 있어 절반만 인정합니다.
        score += 10; why.append("여행 가이드")
    elif atype in _LOW_VALUE_TYPES:
        score -= 25; why.append("회차·근황 리뷰 — 고쳐도 줄거리 요약만 남음")

    # 유형 태그와 무관하게 제목이 회차 리뷰면 감점합니다 (중복 감점하지 않음).
    if atype not in _LOW_VALUE_TYPES and _EPISODIC_TITLE.search(title or ""):
        score -= 25; why.append("회차·근황 리뷰 — 고쳐도 방영 정보만 남음")

    return score, why


def build_plan(keep_per_blog: int = DEFAULT_KEEP_PER_BLOG,
               min_score: int = DEFAULT_MIN_SCORE) -> dict:
    audit = _load_json(AUDIT_PATH, {})
    items = audit.get("items") or []
    if not items:
        logger.error("experience_audit.json이 없거나 비어 있습니다 — 먼저 감사를 돌리세요")
        return {}

    reg = _registry_index()
    flagged_urls = set()
    by_blog = defaultdict(list)

    for it in items:
        url = (it.get("url") or "").rstrip("/")
        flagged_urls.add(url)
        meta = reg.get(url, {})
        score, why = salvage_score(it, meta, it.get("title", ""))
        by_blog[it.get("blog", "?")].append({
            "url": it.get("url", ""), "title": it.get("title", ""),
            "blog": it.get("blog", ""), "blogId": it.get("blogId", ""),
            "severity": it.get("severity"), "hits": it.get("body_hit_count", 0),
            "wordCount": meta.get("wordCount"), "faqCount": meta.get("faqCount"),
            "articleType": meta.get("articleType"),
            "score": score, "why": why,
        })

    # 감사를 통과한 글은 손대지 않습니다. 감사 리포트에는 문제 글만 실려 있으므로
    # 레지스트리에서 역으로 찾습니다. 레지스트리에 없는 옛 글은 셀 수 없어
    # keep 수에 반영되지 않습니다 — 계획이 보수적으로 나오는 방향이라 괜찮습니다.
    clean_by_blog = Counter()
    for url, meta in reg.items():
        if meta.get("status") == "published" and url not in flagged_urls:
            clean_by_blog[meta.get("blogName", "?")] += 1

    plan = {"keep": [], "rewrite": [], "unpublish": []}
    shortfall = {}
    for blog, cands in by_blog.items():
        cands.sort(key=lambda c: -c["score"])
        already_clean = clean_by_blog.get(blog, 0)
        want = max(0, keep_per_blog - already_clean)
        picked = [c for c in cands[:want] if c["score"] >= min_score]
        chosen = {c["url"] for c in picked}
        plan["rewrite"].extend(picked)
        plan["unpublish"].extend(c for c in cands if c["url"] not in chosen)
        if len(picked) < want:
            shortfall[blog] = want - len(picked)

    plan["rewrite"].sort(key=lambda c: (c["blog"], -c["score"]))
    plan["unpublish"].sort(key=lambda c: (c["blog"], c["score"]))

    # 감사는 498편을 봤는데 레지스트리에는 300편만 있습니다. 감사를 통과한
    # 45편 중 레지스트리로 확인되는 것은 일부뿐이고, 나머지 옛 글은 손대지
    # 않으므로 그대로 살아남습니다. 두 숫자를 모두 보여 줘야 최종 공개 편수를
    # 실제보다 적게 오해하지 않습니다.
    clean_total = max(0, (audit.get("scanned") or 0) - (audit.get("flagged") or 0))
    clean_known = sum(clean_by_blog.values())

    report = {
        "plannedAt": datetime.now(timezone.utc).isoformat(),
        "keepPerBlog": keep_per_blog,
        "minScore": min_score,
        "shortfall": shortfall,
        "auditedAt": audit.get("auditedAt", ""),
        "cleanByBlog": dict(clean_by_blog),
        "counts": {
            "clean": clean_known,
            "cleanTotal": clean_total,
            "cleanUntracked": max(0, clean_total - clean_known),
            "rewrite": len(plan["rewrite"]),
            "unpublish": len(plan["unpublish"]),
        },
        "rewrite": plan["rewrite"],
        "unpublish": plan["unpublish"],
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(PLAN_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"계획 저장: {PLAN_PATH}")
    except OSError as e:
        logger.warning(f"계획 저장 실패: {e}")
    return report


def _post_id_index(cfg: dict, token: str) -> dict:
    """URL → Blogger post id. 내릴 글을 찾으려면 id가 필요합니다."""
    out, page_token = {}, ""
    while True:
        params = {"maxResults": 100, "status": "live", "fetchBodies": "false",
                  "fields": "nextPageToken,items(id,url)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{cfg['blog_id']}/posts",
                         headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=30)
        if r.status_code != 200:
            logger.error(f"글 목록 조회 실패 [{r.status_code}]: {r.text[:160]}")
            return out
        data = r.json()
        for p in data.get("items", []):
            out[(p.get("url") or "").rstrip("/")] = p["id"]
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return out


def apply_unpublish(plan: dict, limit: int = 0, dry_run: bool = True) -> dict:
    """계획의 unpublish 목록을 임시저장으로 내립니다 (삭제 아님)."""
    from blogger_uploader import _get_access_token
    from config import get_blog_configs

    targets = defaultdict(list)
    for it in plan.get("unpublish", []):
        targets[it["blogId"]].append(it)

    done = failed = 0
    log = []
    for cfg in get_blog_configs():
        bid = cfg.get("id", "")
        if bid not in targets:
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{cfg.get('name')}] 토큰 발급 실패 — 건너뜀")
            failed += 1
            continue
        ids = _post_id_index(cfg, token)
        logger.info(f"── [{cfg.get('name')}] 내릴 글 {len(targets[bid])}편 ──")

        for it in targets[bid]:
            if limit and done >= limit:
                logger.info(f"--limit {limit} 도달 — 중단")
                break
            pid = ids.get((it["url"] or "").rstrip("/"))
            if not pid:
                logger.warning(f"  ⏭️  이미 내려갔거나 못 찾음: {it['title'][:44]}")
                continue
            logger.info(f"  ↓ [{it['severity']}/{it['score']}점] {it['title'][:46]}")
            if dry_run:
                done += 1
                log.append({**it, "action": "dry-run"})
                continue
            r = requests.post(
                f"{BLOGGER_API_BASE}/blogs/{cfg['blog_id']}/posts/{pid}/revert",
                headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if r.status_code == 200:
                done += 1
                log.append({**it, "action": "unpublished"})
            else:
                failed += 1
                logger.error(f"    ❌ 실패 [{r.status_code}]: {r.text[:140]}")
            time.sleep(1)
        if limit and done >= limit:
            break

    return {"unpublished": done, "failed": failed, "dryRun": dry_run, "items": log}


def write_markdown(rep: dict, path: str = "") -> str:
    """사람이 읽고 승인할 검토 문서.

    JSON은 400편을 눈으로 훑기에 적합하지 않습니다. 내릴 글 목록 전체를
    점수·사유와 함께 적어, 승인 전에 "이건 남겨야 하는데"를 잡을 수 있게 합니다.
    """
    path = path or PLAN_MD_PATH
    c = rep["counts"]
    L = [
        "# 사이트 재편 계획 (소규모 정예)", "",
        f"- 감사 기준: `{rep.get('auditedAt', '?')}`",
        f"- 계획 생성: `{rep['plannedAt']}`",
        f"- 블로그당 목표 {rep['keepPerBlog']}편 · 최소 점수 {rep['minScore']}점", "",
        "| 구분 | 편수 |", "|---|---:|",
        f"| ✅ 그대로 유지 (감사 통과) | {c['cleanTotal']} |",
        f"| ✏️ 리라이팅 후 유지 | {c['rewrite']} |",
        f"| ↓ 비공개 전환 | {c['unpublish']} |",
        f"| **최종 공개** | **{c['cleanTotal'] + c['rewrite']}** |", "",
        "> 비공개는 **임시저장 전환**입니다. 삭제가 아니라 Blogger에서 언제든 "
        "다시 공개할 수 있습니다.", "",
    ]

    for blog in sorted({i["blog"] for i in rep["rewrite"] + rep["unpublish"]}):
        rw = [i for i in rep["rewrite"] if i["blog"] == blog]
        up = [i for i in rep["unpublish"] if i["blog"] == blog]
        short = rep.get("shortfall", {}).get(blog, 0)
        L += [f"## {blog}", "",
              f"리라이팅 {len(rw)}편 · 비공개 {len(up)}편"
              + (f" · 정원 {short}편은 기준 미달로 비움" if short else ""), "",
              "### ✏️ 살릴 글", "", "| 점수 | 심각도 | 분량 | 제목 | 판단 근거 |",
              "|---:|---|---:|---|---|"]
        for i in rw:
            L.append(f"| {i['score']} | {i['severity']} | {i['wordCount'] or '?'} | "
                     f"[{i['title']}]({i['url']}) | {' · '.join(i['why'])} |")
        L += ["", "<details><summary>↓ 내릴 글 " + str(len(up)) +
              "편 (펼치기)</summary>", "", "| 점수 | 심각도 | 문제 문단 | 제목 |",
              "|---:|---|---:|---|"]
        for i in up:
            L.append(f"| {i['score']} | {i['severity']} | {i['hits']} | "
                     f"[{i['title']}]({i['url']}) |")
        L += ["", "</details>", ""]

    text = "\n".join(L)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info(f"검토 문서 저장: {path}")
    except OSError as e:
        logger.warning(f"검토 문서 저장 실패: {e}")
    return text


def _print_plan(rep: dict) -> None:
    c = rep["counts"]
    logger.info("=" * 66)
    logger.info(f"블로그당 목표 {rep['keepPerBlog']}편 (감사 통과분 포함)")
    logger.info(f"  ✅ 그대로 유지 (감사 통과)  {c['cleanTotal']:>3}편  "
                f"— 이 중 {c['clean']}편만 레지스트리로 블로그 확인 가능")
    logger.info(f"  ✏️  리라이팅 후 유지        {c['rewrite']:>3}편")
    logger.info(f"  ↓  비공개 전환             {c['unpublish']:>3}편")
    logger.info(f"  → 최종 공개 글             {c['cleanTotal'] + c['rewrite']:>3}편")
    logger.info("")
    for blog in sorted({i["blog"] for i in rep["rewrite"]}):
        rw = [i for i in rep["rewrite"] if i["blog"] == blog]
        up = [i for i in rep["unpublish"] if i["blog"] == blog]
        clean = rep["cleanByBlog"].get(blog, 0)
        short = rep.get("shortfall", {}).get(blog, 0)
        note = f"  (정원 {short}편은 {rep['minScore']}점 미달로 비움)" if short else ""
        logger.info(f"  [{blog}] 유지 {clean} + 리라이팅 {len(rw)} = {clean + len(rw)}편 "
                    f"/ 비공개 {len(up)}편{note}")
    logger.info("")
    logger.info("리라이팅 대상 상위 10편:")
    for i in rep["rewrite"][:10]:
        logger.info(f"  {i['score']:>4}점 [{i['severity']:<8}] {i['title'][:44]}")
        logger.info(f"        {' · '.join(i['why'][:3])}")


def main() -> int:
    p = argparse.ArgumentParser(description="사이트를 소규모 정예로 재편")
    p.add_argument("--plan", action="store_true", help="계획만 출력 (기본)")
    p.add_argument("--apply", action="store_true", help="비공개 전환을 실제로 실행")
    p.add_argument("--keep-per-blog", type=int, default=DEFAULT_KEEP_PER_BLOG,
                   help=f"블로그당 남길 글 수 (기본 {DEFAULT_KEEP_PER_BLOG})")
    p.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE,
                   help=f"이 점수 미만은 정원이 남아도 살리지 않음 (기본 {DEFAULT_MIN_SCORE})")
    p.add_argument("--limit", type=int, default=0, help="이번에 내릴 최대 글 수")
    args = p.parse_args()

    rep = build_plan(args.keep_per_blog, args.min_score)
    if not rep:
        return 1
    write_markdown(rep)
    _print_plan(rep)

    if not args.apply:
        logger.info("")
        logger.info("계획만 세웠습니다. 실제로 내리려면 --apply --limit 20 부터 시작하세요.")
        logger.info("비공개는 임시저장 전환이라 Blogger에서 언제든 되돌릴 수 있습니다.")
        return 0

    res = apply_unpublish(rep, args.limit, dry_run=False)
    try:
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump({"ranAt": datetime.now(timezone.utc).isoformat(), **res},
                      f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"실행 결과 저장 실패: {e}")
    logger.info("=" * 66)
    logger.info(f"비공개 전환 {res['unpublished']}편 / 실패 {res['failed']}편")
    logger.info("다음: fix-experience-claims 워크플로의 bodies 단계로 "
                "리라이팅 대상을 처리하세요.")
    return 0 if res["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
