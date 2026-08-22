"""검토 대기 글 저장소 — 목록·본문·보관을 나눠 둡니다.

왜 나눴나
─────────
pending_posts.json 하나에 본문 HTML까지 넣어 두니 파일이 1.3MB가 됐고,
대시보드가 화면을 그리기도 전에 그걸 통째로 내려받았습니다. 그런데 목록
화면에 필요한 건 제목·키워드·점수뿐이고, 본문은 미리보기를 눌러야 씁니다.
게다가 161건 중 112건은 이미 발행됐거나 만료된 기록이었습니다.

  pending_posts.json    목록 — 본문 대신 excerpt/contentLength만 (작음)
  pending_bodies.json   {id: 본문 HTML} — 미리보기·발행 때만 읽음
  pending_archive.json  발행·만료로 끝난 기록 (본문 없음, 이력 보존용)

파이썬 쪽에서는 load()가 본문을 도로 합쳐 주므로, 기존처럼 record["content"]를
쓰면 됩니다. 저장은 save()로만 하세요 — 세 파일이 함께 갱신돼야 합니다.
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data")

INDEX_FILE = os.path.join(_DATA_DIR, "pending_posts.json")
BODIES_FILE = os.path.join(_DATA_DIR, "pending_bodies.json")
ARCHIVE_FILE = os.path.join(_DATA_DIR, "pending_archive.json")

#: 목록 카드가 220자를 쓰므로 여유를 조금 둡니다
EXCERPT_LEN = 240
#: 목록에서 빼고 보관으로 넘길 상태
TERMINAL = ("published", "expired", "deleted", "archived")

_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")


def _read(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def _write(path, data, compact: bool = False) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            # 본문 묶음은 사람이 읽을 일이 없습니다. 들여쓰기가 파일의 절반을
            # 차지해서 받는 쪽만 손해입니다.
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)


def excerpt(html: str) -> str:
    """본문에서 태그를 걷어낸 앞부분. 목록 카드가 쓰는 미리보기 텍스트."""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html or "")).strip()
    return text[:EXCERPT_LEN]


def load_bodies() -> dict:
    return _read(BODIES_FILE, {})


def load() -> list[dict]:
    """검토 대기 기록 전체 (목록 + 보관), 본문을 도로 합쳐 돌려줍니다.

    보관본까지 함께 주는 이유: save()가 세 파일을 통째로 다시 쓰기 때문에,
    일부만 읽고 저장하면 나머지가 지워집니다. 읽은 것과 쓰는 것의 범위를
    같게 두는 편이 안전합니다. 대기 건만 필요하면 status로 거르세요.
    """
    records = _read(INDEX_FILE, []) + _read(ARCHIVE_FILE, [])
    bodies = load_bodies()
    for r in records:
        if not isinstance(r, dict):
            continue
        # 이미 본문을 들고 있으면(옛 형식 파일) 그대로 둡니다
        if not r.get("content"):
            body = bodies.get(r.get("id"))
            if body:
                r["content"] = body
    return records


def save(records: list[dict]) -> None:
    """목록·본문·보관 세 파일로 나눠 저장합니다.

    본문을 언제 버릴지는 여기서 정하지 않습니다. 그 판단(끝난 지 N일)은
    pending_manager.prune이 갖고 있고, 규칙이 두 곳에 살면 반드시 어긋납니다.
    저장소는 나누기만 하고, 넘어온 본문은 보관 기록 것이라도 그대로 씁니다.
    """
    index, archive, bodies = [], [], {}
    for r in records:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        body = row.pop("content", "") or ""
        if body:
            row.setdefault("excerpt", excerpt(body))
            row["contentLength"] = len(body)
        if body and row.get("id"):
            bodies[row["id"]] = body
        if row.get("status") in TERMINAL:
            row.pop("excerpt", None)
            archive.append(row)
        else:
            index.append(row)

    _write(INDEX_FILE, index)
    _write(BODIES_FILE, bodies, compact=True)
    _write(ARCHIVE_FILE, archive)
    logger.info(
        f"검토 대기 저장: 목록 {len(index)}건 / 보관 {len(archive)}건 / 본문 {len(bodies)}건"
    )


def migrate() -> dict:
    """옛 단일 파일을 세 파일로 나눕니다. 여러 번 실행해도 안전합니다."""
    records = load()
    save(records)
    return {
        "records": len(records),
        "index": len(_read(INDEX_FILE, [])),
        "archive": len(_read(ARCHIVE_FILE, [])),
        "bodies": len(load_bodies()),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(json.dumps(migrate(), ensure_ascii=False, indent=2))
