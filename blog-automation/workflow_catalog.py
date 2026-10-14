"""워크플로 목록을 대시보드용 JSON으로 만듭니다.

왜 자동 생성인가
────────────────
대시보드의 "실행 제어"는 쓸 워크플로를 화면에 손으로 박아 두는 방식이었고,
dispatch 가능한 70개 중 30개만 올라와 있었습니다. 블로그 관련으로만 세도
19개가 빠져 있었습니다 — 백업·사이트맵·클러스터·검증·면책 링크·무단 이미지
교체·체험담 정정·글 비공개 등. 손으로 유지하면 새 워크플로가 생길 때마다
또 빠지므로, 워크플로 파일에서 직접 읽어 만듭니다.

무엇을 거르는가
───────────────
이 저장소는 npm/cli의 포크입니다. 상속받은 npm CI 워크플로(ci-*.yml,
audit.yml, node-integration.yml 등)는 블로그 운영과 무관하므로 목록에서
빼되, 왜 뺐는지 집계로 남깁니다 — "왜 74개 중 50개만 보이지"를 다시 파는
일을 막으려는 것입니다.

위험한 작업 표시
────────────────
발행된 글을 지우거나 내리는 워크플로가 섞여 있습니다. 목록에 그냥 올리면
버튼 하나로 글이 사라집니다. `danger` 로 표시해 화면이 확인을 받게 하고,
dry-run 입력이 있는 워크플로는 그 입력의 기본값을 함께 넘깁니다.

Usage:
  python workflow_catalog.py            # docs/data/workflow_catalog.json 생성
  python workflow_catalog.py --print    # 생성 없이 집계만 출력
"""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.join(_HERE, "..", ".github", "workflows")
OUT_PATH = os.path.join(_HERE, "..", "docs", "data", "workflow_catalog.json")

#: npm/cli에서 상속받은 워크플로 — 블로그 운영과 무관합니다.
#: 접두사 또는 정확한 파일명으로 거릅니다.
UPSTREAM_PREFIXES = ("ci-",)
UPSTREAM_FILES = {
    "audit.yml", "ci.yml", "create-node-pr.yml",
    "node-integration.yml", "release-integration.yml",
}

#: 발행된 글을 지우거나 내리는 워크플로 — 화면이 확인을 받아야 합니다.
DANGEROUS_FILES = {
    "delete-low-grade-posts.yml",
    "unpublish-url.yml",
    "curate-site.yml",
    "site-structure.yml",
}

#: 발행 글의 본문을 고치는 워크플로 — 되돌리기 어려우니 함께 표시합니다.
MUTATING_HINTS = ("fix-", "image-backfill", "link-disclaimer", "enrich")

#: 화면에서 묶어 보여줄 분류. 파일명 조각 → 분류명.
CATEGORIES = (
    ("발행", ("blog-run", "manual-publish", "series-schedule", "publish")),
    ("SEO·색인", ("sitemap", "index", "gsc", "optimize", "cluster", "inbound",
                  "site-structure", "trend")),
    ("콘텐츠 정비", ("fix-", "enrich", "image", "experience", "disclaimer",
                     "affiliate", "curate", "delete-low-grade", "unpublish",
                     "faq", "dead-link")),
    ("수익", ("adsense", "revenue", "coupang")),
    ("운영·점검", ("monitor", "alert", "verify", "repair", "health", "test",
                   "backup", "export-settings", "deploy", "learning", "brief",
                   "bot", "schedule")),
)


def _classify(filename: str) -> str:
    for label, needles in CATEGORIES:
        if any(n in filename for n in needles):
            return label
    return "기타"


def _is_upstream(filename: str) -> bool:
    return filename in UPSTREAM_FILES or filename.startswith(UPSTREAM_PREFIXES)


def _normalise_inputs(raw: dict) -> list[dict]:
    """workflow_dispatch inputs를 화면이 바로 그릴 수 있는 형태로."""
    out = []
    for name, spec in (raw or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        field = {
            "name": name,
            "description": str(spec.get("description", "")),
            "type": str(spec.get("type", "string")),
            "required": bool(spec.get("required", False)),
        }
        default = spec.get("default")
        if isinstance(default, bool):
            field["default"] = "true" if default else "false"
        elif default is not None:
            field["default"] = str(default)
        else:
            field["default"] = ""
        if spec.get("options"):
            field["options"] = [str(o) for o in spec["options"]]
        out.append(field)
    return out


def _dispatch_block(parsed: dict) -> dict | None:
    """on: 블록에서 workflow_dispatch를 꺼냅니다.

    YAML에서 `on:` 은 불리언 True로 파싱됩니다 — 이걸 놓치면 모든
    워크플로가 "수동 실행 불가"로 보입니다.
    """
    on = parsed.get("on", parsed.get(True))
    if isinstance(on, dict):
        wd = on.get("workflow_dispatch")
        return wd if isinstance(wd, dict) else ({} if "workflow_dispatch" in on else None)
    if isinstance(on, list):
        return {} if "workflow_dispatch" in on else None
    if on == "workflow_dispatch":
        return {}
    return None


def _schedules(parsed: dict) -> list[str]:
    on = parsed.get("on", parsed.get(True))
    if not isinstance(on, dict):
        return []
    sched = on.get("schedule") or []
    return [str(s.get("cron", "")) for s in sched
            if isinstance(s, dict) and s.get("cron")]


def build(workflow_dir: str = "") -> dict:
    import yaml

    directory = workflow_dir or WORKFLOW_DIR
    entries, skipped_upstream, no_dispatch, unreadable = [], [], [], []

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith((".yml", ".yaml")):
            continue
        if _is_upstream(filename):
            skipped_upstream.append(filename)
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, encoding="utf-8") as f:
                parsed = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as exc:
            # 읽지 못한 파일을 조용히 빼면 목록이 줄어든 것도 모릅니다
            logger.warning(f"{filename} 읽기 실패: {exc}")
            unreadable.append(filename)
            continue
        if not isinstance(parsed, dict):
            unreadable.append(filename)
            continue

        dispatch = _dispatch_block(parsed)
        if dispatch is None:
            # 수동 실행이 없는 워크플로는 버튼을 만들 수 없습니다
            no_dispatch.append(filename)
            continue

        inputs = _normalise_inputs(dispatch.get("inputs"))
        danger = filename in DANGEROUS_FILES or any(
            h in filename for h in MUTATING_HINTS)
        entries.append({
            "file": filename,
            "name": str(parsed.get("name", filename)).strip('"'),
            "category": _classify(filename),
            "inputs": inputs,
            "schedules": _schedules(parsed),
            "danger": danger,
            # dry-run 성격의 입력이 있으면 화면이 기본값을 안전한 쪽으로
            # 둘 수 있게 이름을 넘깁니다
            "dryRunInput": next(
                (i["name"] for i in inputs
                 if i["name"] in ("dry_run", "apply", "dryrun")), ""),
        })

    order = [label for label, _ in CATEGORIES] + ["기타"]
    entries.sort(key=lambda e: (order.index(e["category"]), e["name"]))

    return {
        "generatedAt": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "workflows": entries,
        "categories": order,
        "counts": {
            "listed": len(entries),
            "upstreamSkipped": len(skipped_upstream),
            "noDispatch": len(no_dispatch),
            "unreadable": len(unreadable),
        },
        "skipped": {
            "upstream": skipped_upstream,
            "noDispatch": no_dispatch,
            "unreadable": unreadable,
        },
        "note": ("npm/cli에서 상속받은 CI 워크플로는 블로그 운영과 무관해 "
                 "목록에서 제외했습니다. 수동 실행(workflow_dispatch)이 없는 "
                 "워크플로는 버튼을 만들 수 없어 제외했습니다."),
    }


def export(out_path: str = "") -> dict:
    catalog = build()
    path = out_path or OUT_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, separators=(",", ":"))
    c = catalog["counts"]
    logger.info(
        f"워크플로 목록 저장: {path} — 노출 {c['listed']} / "
        f"npm 상속 제외 {c['upstreamSkipped']} / 수동실행 없음 {c['noDispatch']}"
    )
    if c["unreadable"]:
        logger.warning(f"⚠️ 읽지 못한 워크플로 {c['unreadable']}개: "
                       f"{catalog['skipped']['unreadable']}")
    return catalog


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if "--print" in sys.argv:
        catalog = build()
        print(json.dumps(catalog["counts"], ensure_ascii=False, indent=2))
        for e in catalog["workflows"]:
            flag = " ⚠️위험" if e["danger"] else ""
            print(f"  [{e['category']}] {e['name']} ({e['file']}) "
                  f"입력 {len(e['inputs'])}개{flag}")
        return 0
    export()
    return 0


if __name__ == "__main__":
    sys.exit(main())
