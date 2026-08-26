"""글에 넣는 이미지를 저장소에 복제해 우리 도메인에서 서빙합니다.

왜 필요한가
──────────
지금까지 본문 이미지는 전부 남의 서버를 가리키는 핫링크였습니다
(`<img src="https://pixabay.com/get/...">`). 원본이 지워지거나 URL 규칙이
바뀌면 이미 발행한 글이 조용히 깨지고, 우리 쪽에는 무엇이 있었는지조차
남지 않습니다. 2026-08-25 기준 최근 1,000장 중 467장이 Pixabay의 해시 URL,
278장이 뉴스사 CDN이었습니다.

어떻게
──────
docs/ 가 GitHub Pages로 서빙되므로(deploy-dashboard.yml, docs/ 전체 배포)
`docs/images/` 에 파일을 커밋하면 그대로 공개 URL이 됩니다. 내용 해시를
파일 이름으로 써서 같은 사진은 한 번만 저장하고, 어느 원본에서 왔는지는
docs/data/image_mirror.json 에 남깁니다.

라이선스
────────
복제 대상은 image_fetcher의 화이트리스트를 통과한 것뿐입니다
(Pixabay·Wikimedia·Unsplash·우리가 올린 ImgBB). 모두 상업적 재사용이
허용된 소스이고, 출처 표기는 기존 figcaption 로직이 그대로 유지합니다.
화이트리스트 밖 이미지는 애초에 여기까지 오지 않습니다 — 그리고 이 모듈은
그 판정을 다시 하지 않으므로, 호출부가 관문 뒤에 있어야 합니다.

한계
────
· 배포 시차: 글 발행과 Pages 배포 사이 몇 분 동안 복제본이 아직 없습니다.
  그래서 _make_img_html이 원본 URL을 onerror 폴백으로 함께 심습니다.
· 리사이즈는 하지 않습니다(Pillow 미설치). MAX_BYTES를 넘는 원본은
  복제하지 않고 핫링크로 남겨 둡니다 — 저장소가 부푸는 것이 더 큰 손해입니다.
"""

import base64
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_BASE, ".."))

MIRROR_DIR = os.path.join(_REPO_ROOT, "docs", "images")
MANIFEST_FILE = os.path.join(_REPO_ROOT, "docs", "data", "image_mirror.json")

#: 이보다 큰 원본은 복제하지 않습니다. Pixabay 1280px 사진이 보통 150~400KB라
#: 정상 범위는 넉넉히 들어오고, 원본 해상도 파일만 걸립니다.
MAX_BYTES = 2_000_000
TIMEOUT = 20

#: 확장자는 서버가 알려 준 Content-Type으로 정합니다. URL 끝의 ".jpg"는
#: Pixabay의 해시 URL처럼 실제 형식과 무관한 경우가 있습니다.
_EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_DEFAULT_BASE = "https://kevinlee7250.github.io/cli/images"


def public_base() -> str:
    """복제본이 서빙되는 공개 URL의 앞부분.

    러너에서는 GITHUB_REPOSITORY로 계산합니다. 저장소 이름이 바뀌어도
    따라가고, 포크에서 돌려도 그 포크의 Pages를 가리킵니다.
    """
    env = os.getenv("IMAGE_HOST_BASE", "").strip().rstrip("/")
    if env:
        return env
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/images"
    return _DEFAULT_BASE


def is_mirrored_url(url: str) -> bool:
    return bool(url) and url.rstrip("/").startswith(public_base())


# ─── 매니페스트 ───────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    try:
        with open(MANIFEST_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"updatedAt": "", "items": {}}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"updatedAt": "", "items": {}}
    return data


def save_manifest(manifest: dict) -> None:
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(MANIFEST_FILE), exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, separators=(",", ":"))


def _origin_index(manifest: dict) -> dict[str, str]:
    """원본 URL → 해시. 같은 원본을 다시 내려받지 않기 위한 색인입니다."""
    index = {}
    for digest, rec in manifest.get("items", {}).items():
        for origin in rec.get("origins", []):
            index[origin] = digest
    return index


def mirrored_url_for(origin: str) -> str:
    """이미 복제해 둔 원본이면 그 공개 URL을, 아니면 빈 문자열.

    파일이 실제로 있는지도 확인합니다 — 매니페스트에만 남고 파일이 사라진
    경우에 발행 글을 그쪽으로 돌려놓으면 이미지가 죽습니다.
    """
    manifest = load_manifest()
    digest = _origin_index(manifest).get((origin or "").strip())
    if not digest:
        return ""
    rec = manifest["items"].get(digest, {})
    name = rec.get("file", "")
    if not name or not os.path.exists(os.path.join(MIRROR_DIR, name)):
        return ""
    return f"{public_base()}/{name}"


def origin_of(url: str) -> str:
    """복제본 URL을 원본 URL로 되돌립니다 (모르면 빈 문자열).

    중복 이미지 판정이 복제 전 URL 기준으로 이뤄져야 같은 사진이 다른
    경로로 다시 뽑히는 것을 막을 수 있습니다.
    """
    if not is_mirrored_url(url):
        return ""
    m = re.search(r"/([0-9a-f]{16})\.[a-z]+$", url)
    if not m:
        return ""
    rec = load_manifest().get("items", {}).get(m.group(1), {})
    origins = rec.get("origins", [])
    return origins[0] if origins else ""


# ─── 복제 ─────────────────────────────────────────────────────────────────────

def _decode_data_uri(url: str) -> tuple[bytes, str] | None:
    m = re.match(r"data:([^;,]+)(;base64)?,(.*)$", url, re.S)
    if not m:
        return None
    mime, is_b64, payload = m.group(1).lower(), bool(m.group(2)), m.group(3)
    try:
        raw = base64.b64decode(payload) if is_b64 else requests.utils.unquote(payload).encode("utf-8")
    except Exception:
        return None
    return raw, mime


#: 발행 글의 Pixabay 이미지가 400을 돌려줍니다. 원인이 둘인데 대응이 정반대라
#: 구분해야 합니다.
#:   (가) 서명 URL 만료 → 그 이미지는 이미 죽었고, 복제가 아니라 교체 대상
#:   (나) 핫링크 차단   → 브라우저에서는 멀쩡하고, 서버 요청만 막힌 것
#: Referer를 붙여 한 번 더 요청해 보면 갈립니다. 성공하면 (나)이고, 그래도
#: 400이면 (가)입니다. 어느 쪽인지 로그에 남깁니다 — 추측으로 500장을
#: 처리하면 안 됩니다.
def _fetch(url: str):
    r = requests.get(url, headers=_HEADERS, timeout=TIMEOUT, stream=True)
    if r.status_code < 400:
        return r
    m = re.match(r"(https?://[^/]+)", url)
    retry = dict(_HEADERS, Referer=(m.group(1) + "/") if m else url, Accept="image/*,*/*")
    r2 = requests.get(url, headers=retry, timeout=TIMEOUT, stream=True)
    if r2.status_code < 400:
        logger.info(f"Referer 재시도로 통과(핫링크 차단이었음): {url[:70]}")
        return r2
    logger.debug(f"재시도도 {r2.status_code}: {url[:70]}")
    return r


def _download(url: str) -> tuple[bytes, str] | None:
    """(바이트, MIME). 실패하거나 이미지가 아니면 None."""
    if url.startswith("data:"):
        return _decode_data_uri(url)
    try:
        r = _fetch(url)
        r.raise_for_status()
        mime = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        # 길이를 미리 알 수 있으면 내려받기 전에 포기합니다
        declared = r.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            logger.info(f"이미지 복제 건너뜀(용량 {int(declared)//1024}KB): {url[:70]}")
            return None
        raw = b""
        for chunk in r.iter_content(64 * 1024):
            raw += chunk
            if len(raw) > MAX_BYTES:
                logger.info(f"이미지 복제 건너뜀(용량 초과): {url[:70]}")
                return None
        return raw, mime
    except Exception as e:
        logger.warning(f"이미지 내려받기 실패: {url[:70]} — {e}")
        return None


def mirror_url(url: str) -> dict | None:
    """이미지 하나를 docs/images 아래에 복제하고 공개 URL 정보를 돌려줍니다.

    이미 복제된 원본이면 내려받지 않고 기존 것을 그대로 씁니다.
    복제할 수 없으면 None — 호출부는 원본 URL을 유지해야 합니다.
    """
    url = (url or "").strip()
    if not url or is_mirrored_url(url):
        return None

    manifest = load_manifest()
    known = _origin_index(manifest).get(url)
    if known:
        rec = manifest["items"][known]
        path = os.path.join(MIRROR_DIR, rec["file"])
        if os.path.exists(path):
            return {"url": f"{public_base()}/{rec['file']}", "file": rec["file"],
                    "sha": known, "bytes": rec.get("bytes", 0), "reused": True,
                    "uses": times_used_by_record(rec)}
        # 매니페스트에는 있는데 파일이 없으면 다시 내려받습니다

    got = _download(url)
    if not got:
        return None
    raw, mime = got
    ext = _EXT_BY_TYPE.get(mime)
    if not ext:
        logger.info(f"이미지 복제 건너뜀(형식 {mime or '불명'}): {url[:70]}")
        return None

    digest = hashlib.sha256(raw).hexdigest()[:16]
    name = f"{digest}{ext}"
    os.makedirs(MIRROR_DIR, exist_ok=True)
    path = os.path.join(MIRROR_DIR, name)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(raw)

    rec = manifest["items"].setdefault(
        digest, {"file": name, "bytes": len(raw), "mime": mime,
                 "firstSeen": datetime.now(timezone.utc).isoformat(),
                 "origins": [], "uses": 0})
    rec["file"] = name
    prior = times_used_by_record(rec)
    if url not in rec["origins"]:
        rec["origins"].append(url)
    save_manifest(manifest)

    return {"url": f"{public_base()}/{name}", "file": name, "sha": digest,
            "bytes": len(raw), "reused": prior > 0, "uses": prior}


#: 한 사진을 이 편수까지만 씁니다. 넘으면 다른 후보를 찾습니다.
#: 2026-08-25 실측에서 사진 한 장이 61편에 들어가 있었습니다.
MAX_REUSE = 3


def note_use(mirrored_url: str) -> int:
    """이 사진을 실제로 글에 넣었다고 기록합니다.

    복제(내려받기)와 사용(글에 넣기)은 다른 일입니다. 복제할 때 세면,
    후보로 훑어보다 **버린 사진까지** 사용 횟수가 올라갑니다. 그러면 임계값이
    금세 차올라 가드가 무력해지고, 오히려 남은 후보가 없어져 가장 많이 쓴
    사진으로 되돌아갑니다.

    2026-08-26 파일럿에서 실제로 그랬습니다. 로그에는 "다른 후보 확인"이
    찍히는데 결과는 반대로, 최다 사용 사진이 61회 → 76회로 늘었습니다.
    그래서 채택이 확정된 순간에만 이 함수를 부릅니다.
    """
    m = re.search(r"/([0-9a-f]{16})\.[a-z]+$", mirrored_url or "")
    if not m:
        return 0
    manifest = load_manifest()
    rec = manifest.get("items", {}).get(m.group(1))
    if rec is None:
        return 0
    rec["uses"] = times_used_by_record(rec) + 1
    save_manifest(manifest)
    return rec["uses"]


def times_used_by_record(rec: dict) -> int:
    """이 사진이 몇 편에 쓰였는지.

    uses가 없는 옛 기록은 origins 개수로 셉니다 — 같은 사진에 서명 URL이
    여러 개 붙은 만큼은 실제로 쓰인 것이므로 최소값으로는 맞습니다.

    `or`가 아니라 None 검사를 씁니다. uses가 0인 기록(복제만 하고 아직 쓰지
    않은 사진)에 `or`를 쓰면 0을 "값 없음"으로 보고 origins 개수로 되돌아가,
    쓰지도 않은 사진이 이미 쓴 것으로 잡힙니다.
    """
    uses = rec.get("uses")
    if uses is None:
        return len(rec.get("origins", []))
    return int(uses)


def times_used(mirrored_url: str) -> int:
    """복제본 URL이 몇 편에 쓰였는지 (모르면 0)."""
    m = re.search(r"/([0-9a-f]{16})\.[a-z]+$", mirrored_url or "")
    if not m:
        return 0
    return times_used_by_record(load_manifest().get("items", {}).get(m.group(1), {}))


def is_overused(mirrored_url: str, limit: int = MAX_REUSE) -> bool:
    return times_used(mirrored_url) > limit


def mirror_images(images: list[dict]) -> int:
    """이미지 목록의 url을 복제본으로 바꾸고, 원본은 origin_url에 남깁니다.

    복제에 실패한 항목은 손대지 않습니다 — 자체 호스팅이 안 된다고 해서
    이미지 없는 글을 내보내는 것보다 핫링크가 낫습니다.
    """
    changed = 0
    for img in images or []:
        src = (img.get("url") or "").strip()
        if not src or img.get("origin_url"):
            continue
        got = mirror_url(src)
        if not got:
            continue
        img["origin_url"] = src
        img["url"] = got["url"]
        changed += 1
    if changed:
        logger.info(f"🖼️ 이미지 자체 호스팅 {changed}장 (docs/images)")
    return changed


def stats() -> dict:
    """저장소가 얼마나 늘고 있는지 — 워크플로 로그와 점검에 씁니다."""
    manifest = load_manifest()
    items = manifest.get("items", {})
    total = sum(int(r.get("bytes", 0)) for r in items.values())
    present = 0
    if os.path.isdir(MIRROR_DIR):
        present = len([n for n in os.listdir(MIRROR_DIR) if not n.startswith(".")])
    return {"mirrored": len(items), "filesOnDisk": present,
            "totalBytes": total, "updatedAt": manifest.get("updatedAt", "")}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = stats()
    print(f"복제 이미지 {s['mirrored']}장 / 디스크 {s['filesOnDisk']}개 / "
          f"{s['totalBytes'] / 1024 / 1024:.1f}MB")
    print(f"공개 경로: {public_base()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
