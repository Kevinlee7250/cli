"""Google Drive 백업 스크립트

백업 대상:
  - docs/data/*.json          — 대시보드 데이터 (포스트·레지스트리·실행이력 등)
  - blog-automation/logs/*.json  — 런타임 레지스트리·키워드 이력
  - blog-automation/logs/*.log   — 자동화 실행 로그 (최근 2000줄)

업로드 위치: Google Drive BACKUP_FOLDER_ID (매 실행 시 날짜·시각 폴더 생성)
오래된 백업: KEEP_BACKUPS 개 초과 시 오래된 것부터 자동 삭제

사용법:
  python backup_to_drive.py [--dry-run] [--folder-id <id>]
"""

import argparse
import io
import json
import logging
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE      = Path(__file__).resolve().parent
_REPO_ROOT = _BASE.parent
_DOCS_DATA = _REPO_ROOT / "docs" / "data"

DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1VCWoy9901A0rCnjO9ilHagwuIKgB2uda")
KEEP_BACKUPS    = int(os.getenv("BACKUP_KEEP_COUNT", "30"))


# ─── Google Drive OAuth2 ─────────────────────────────────────────────────────

def _get_drive_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    client_id     = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(
            "Google Drive 인증 정보 미설정. "
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_DRIVE_REFRESH_TOKEN 환경 변수를 확인하세요."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ─── 백업 파일 수집 ───────────────────────────────────────────────────────────

def _collect_files() -> dict[str, bytes]:
    """백업할 파일명 → bytes 매핑 반환"""
    files: dict[str, bytes] = {}

    # docs/data/*.json
    if _DOCS_DATA.exists():
        for f in sorted(_DOCS_DATA.glob("*.json")):
            try:
                files[f"docs_data/{f.name}"] = f.read_bytes()
            except OSError as e:
                logger.warning(f"읽기 실패: {f} — {e}")

    # blog-automation/logs/*.json
    logs_dir = _BASE / "logs"
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("*.json")):
            try:
                files[f"logs/{f.name}"] = f.read_bytes()
            except OSError as e:
                logger.warning(f"읽기 실패: {f} — {e}")

    # blog-automation/logs/automation.log (최근 2000줄)
    log_file = logs_dir / "automation.log"
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            files["logs/automation.log"] = "\n".join(lines[-2000:]).encode()
        except OSError as e:
            logger.warning(f"로그 읽기 실패: {e}")

    return files


# ─── ZIP 생성 ─────────────────────────────────────────────────────────────────

def _build_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ─── Drive 업로드 ────────────────────────────────────────────────────────────

def _upload_zip(service, zip_bytes: bytes, zip_name: str, folder_id: str) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        resumable=True,
    )
    metadata = {
        "name":    zip_name,
        "parents": [folder_id],
    }
    result = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,size",
    ).execute()
    file_id = result.get("id", "")
    logger.info(f"✅ 업로드 완료: {zip_name} ({len(zip_bytes)//1024} KB) — Drive ID: {file_id}")
    return file_id


# ─── 오래된 백업 정리 ─────────────────────────────────────────────────────────

def _cleanup_old_backups(service, folder_id: str, keep: int) -> None:
    query = (
        f"'{folder_id}' in parents "
        f"and name contains 'blog_backup_' "
        f"and trashed = false"
    )
    result = service.files().list(
        q=query,
        orderBy="createdTime asc",
        fields="files(id,name,createdTime)",
        pageSize=100,
    ).execute()
    items = result.get("files", [])
    excess = len(items) - keep
    if excess > 0:
        to_delete = items[:excess]
        for f in to_delete:
            service.files().delete(fileId=f["id"]).execute()
            logger.info(f"🗑 오래된 백업 삭제: {f['name']} ({f['id']})")
    else:
        logger.info(f"정리 불필요 — 현재 {len(items)}개 / 최대 {keep}개 유지")


# ─── meta.json 마지막 백업 시각 기록 ──────────────────────────────────────────

def _write_backup_meta(zip_name: str, file_id: str, folder_id: str, file_count: int, size_kb: int) -> None:
    meta_path = _DOCS_DATA / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    except Exception:
        meta = {}
    now = datetime.now(timezone.utc).isoformat()
    meta["lastBackupAt"]       = now
    meta["lastBackupFileName"] = zip_name
    meta["lastBackupFileId"]   = file_id
    meta["lastBackupFolderId"] = folder_id
    meta["lastBackupFileCount"] = file_count
    meta["lastBackupSizeKB"]   = size_kb
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"meta.json 백업 시각 기록 완료: {now}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Google Drive 백업")
    parser.add_argument("--dry-run",   action="store_true", help="업로드 없이 파일 목록만 출력")
    parser.add_argument("--folder-id", default=DRIVE_FOLDER_ID, help="Drive 폴더 ID")
    args = parser.parse_args()

    folder_id = args.folder_id
    now_kst   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_name  = f"blog_backup_{now_kst}.zip"

    logger.info(f"=== 블로그 자동화 시스템 백업 시작 ({now_kst} UTC) ===")
    logger.info(f"대상 폴더 ID: {folder_id}")

    # 파일 수집
    files = _collect_files()
    if not files:
        logger.error("백업 대상 파일이 없습니다.")
        return 1

    logger.info(f"수집 파일 수: {len(files)}개")
    for name in sorted(files):
        logger.info(f"  {name}  ({len(files[name])//1024} KB)")

    # ZIP 생성
    zip_bytes = _build_zip(files)
    size_kb = len(zip_bytes) // 1024
    logger.info(f"ZIP 생성 완료: {zip_name} ({size_kb} KB, {len(files)}개 파일 압축)")

    if args.dry_run:
        logger.info("--dry-run 모드 — 업로드 건너뜀")
        return 0

    # Drive 업로드
    try:
        service = _get_drive_service()
        file_id = _upload_zip(service, zip_bytes, zip_name, folder_id)
        _cleanup_old_backups(service, folder_id, KEEP_BACKUPS)
        _write_backup_meta(zip_name, file_id, folder_id, len(files), size_kb)
        logger.info("=== 백업 완료 ===")
        return 0
    except Exception as e:
        logger.error(f"백업 실패: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
