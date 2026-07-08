"""
코드 자동 수리 — Claude API를 사용하여 Python 예외를 분석하고 수정합니다.

auto-repair.yml에서 auto_repair.py 실행 후 호출됩니다.

사용법:
  python code_repair.py        # 분석 + 자동 수정
  python code_repair.py --dry  # 분석만 (파일 수정 없음)
"""

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_BASE = Path(__file__).parent
_LOGS = _BASE / "logs"
_DOCS = _BASE.parent / "docs" / "data"

LOG_FILE       = _LOGS / "automation.log"
CODE_REPAIR_LOG = _LOGS / "code_repair.json"
CODE_REPAIR_BACKUP = _LOGS / "code_repair_backups"

logger = logging.getLogger(__name__)

# 자동 수정이 허용된 파일 목록 (보안 — 임의 파일 수정 방지)
_ALLOWED_FILES = {
    "content_generator.py",
    "blogger_uploader.py",
    "keyword_collector.py",
    "post_manager.py",
    "adsense_validator.py",
    "main.py",
    "auto_repair.py",
    "trend_collector.py",
    "image_handler.py",
    "social_publisher.py",
    "fix_existing_posts.py",
    "coupang_affiliate.py",
}


# ── 트레이스백 추출 ────────────────────────────────────────────────────────────

def _extract_tracebacks(log_path: Path, max_lines: int = 500) -> list[dict]:
    """로그 파일에서 Python 트레이스백을 추출합니다."""
    if not log_path.exists():
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    tail = lines[-max_lines:]
    tracebacks = []
    i = 0
    while i < len(tail):
        if "Traceback (most recent call last):" in tail[i]:
            tb_lines = [tail[i]]
            j = i + 1
            while j < len(tail):
                line = tail[j]
                # 타임스탬프로 시작하는 새 로그 라인이면 트레이스백 끝
                if re.match(r'^\d{4}-\d{2}-\d{2}', line) and not line.startswith("  "):
                    break
                tb_lines.append(line)
                j += 1
            tb_text = "\n".join(tb_lines)
            file_matches = re.findall(r'File "([^"]+)", line (\d+)', tb_text)
            error_line = ""
            for l in reversed(tb_lines):
                stripped = l.strip()
                if stripped and not stripped.startswith("File ") and not stripped.startswith("Traceback"):
                    error_line = stripped
                    break
            tracebacks.append({
                "traceback": tb_text,
                "files": file_matches,
                "error": error_line,
            })
            i = j
        else:
            i += 1
    return tracebacks[-5:]  # 최근 5개


def _extract_critical_lines(log_path: Path, max_lines: int = 300) -> list[str]:
    """로그에서 CRITICAL/ERROR 패턴 줄을 추출합니다."""
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    tail = lines[-max_lines:]
    result = []
    for line in tail:
        if any(kw in line for kw in ["[CRITICAL]", "CRITICAL —", " ERROR ", "[ERROR]"]):
            result.append(line.strip())
    return result[-10:]


# ── 소스 파일 처리 ────────────────────────────────────────────────────────────

def _resolve_source_file(filepath: str) -> Path | None:
    """트레이스백 파일 경로를 blog-automation 내 실제 경로로 매핑합니다."""
    fname = Path(filepath).name
    if fname not in _ALLOWED_FILES:
        return None
    candidate = _BASE / fname
    if candidate.exists():
        # 경로 순회 방지
        try:
            candidate.resolve().relative_to(_BASE.resolve())
            return candidate
        except ValueError:
            return None
    return None


def _backup_file(path: Path) -> None:
    """수정 전 원본 백업."""
    CODE_REPAIR_BACKUP.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = CODE_REPAIR_BACKUP / f"{path.name}.{ts}.bak"
    backup.write_bytes(path.read_bytes())


# ── Claude API 호출 ───────────────────────────────────────────────────────────

def _call_claude_fix(traceback: str, source_code: str, filename: str) -> dict | None:
    """Claude API로 오류를 분석하고 최소 수정 코드를 반환합니다."""
    try:
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, claude_generate
        import anthropic

        if not ANTHROPIC_API_KEY:
            logger.warning("ANTHROPIC_API_KEY 미설정 — Claude 코드 수리 건너뜀")
            return None

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = (
            "다음 Python 오류를 분석하고 최소한의 코드 변경으로 수정하세요.\n\n"
            f"## 오류 트레이스백\n```\n{traceback}\n```\n\n"
            f"## 파일: {filename}\n```python\n{source_code[:10000]}\n```\n\n"
            "## 응답 형식 (JSON만, 마크다운 없이)\n"
            '{\n'
            '  "root_cause": "오류 원인 한 문장",\n'
            '  "fix_summary": "수정 내용 한 문장",\n'
            '  "can_auto_fix": true 또는 false,\n'
            '  "original_code": "수정 전 정확한 코드 조각 (없으면 null)",\n'
            '  "fixed_code": "수정 후 코드 조각 (없으면 null)",\n'
            '  "confidence": 0.0~1.0\n'
            '}\n\n'
            "수정이 불확실하면 can_auto_fix: false, confidence: 0.5 미만으로 설정하세요."
        )

        raw = claude_generate(
            client,
            model=CLAUDE_MODEL,
            max_tokens=2000,
            temperature=0.1,
            system=(
                "당신은 Python 코드 디버깅 전문가입니다. "
                "반드시 순수 JSON으로만 응답하세요 — 마크다운 없이."
            ),
            messages=[{"role": "user", "content": prompt}],
        )

        # JSON 추출 (```json ... ``` 블록도 처리)
        raw = raw.strip()
        json_match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', raw)
        json_str = json_match.group(1) if json_match else raw
        return json.loads(json_str)

    except json.JSONDecodeError as e:
        logger.error(f"Claude 응답 JSON 파싱 실패: {e}")
        return None
    except Exception as e:
        logger.error(f"Claude API 오류: {e}")
        return None


# ── 코드 수정 적용 ────────────────────────────────────────────────────────────

def _apply_fix(source_code: str, original: str, fixed: str, path: Path) -> bool:
    """소스 파일에 코드 수정을 적용합니다."""
    if not original or original not in source_code:
        logger.warning(f"수정 대상 코드를 찾을 수 없음: {path.name}")
        return False
    if original == fixed:
        logger.info(f"변경 없음 (동일 코드): {path.name}")
        return False
    new_code = source_code.replace(original, fixed, 1)
    try:
        _backup_file(path)
        path.write_text(new_code, encoding="utf-8")
        logger.info(f"✅ 코드 수정 적용됨: {path.name}")
        return True
    except OSError as e:
        logger.error(f"파일 쓰기 실패 {path}: {e}")
        return False


# ── 메인 ──────────────────────────────────────────────────────────────────────

def run_code_repair(dry_run: bool = False) -> dict:
    """로그 기반 코드 오류 분석 및 자동 수정을 실행합니다."""
    _LOGS.mkdir(parents=True, exist_ok=True)

    logger.info("[CodeRepair] 로그 분석 시작...")
    tracebacks = _extract_tracebacks(LOG_FILE)
    critical_lines = _extract_critical_lines(LOG_FILE)

    if not tracebacks:
        logger.info("[CodeRepair] 트레이스백 없음 — 코드 수리 건너뜀")
        result = {
            "timestamp": datetime.now().isoformat(),
            "tracebacks_found": 0,
            "critical_errors": len(critical_lines),
            "repairs": [],
            "auto_fixed": 0,
            "manual_required": 0,
            "dry_run": dry_run,
        }
        _save_result(result)
        return result

    logger.info(f"[CodeRepair] 트레이스백 {len(tracebacks)}개, CRITICAL {len(critical_lines)}건")
    repairs = []

    for tb in tracebacks:
        # blog-automation 소스 파일 찾기
        target = None
        for fpath, lineno in tb["files"]:
            resolved = _resolve_source_file(fpath)
            if resolved:
                target = (resolved, lineno)
                break

        entry = {
            "error": tb["error"][:200],
            "file": target[0].name if target else "unknown",
            "line": target[1] if target else None,
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
        }

        if not target:
            entry.update(result="skip", detail="수정 가능한 소스 파일 없음 (라이브러리 또는 외부 오류)")
            repairs.append(entry)
            logger.info(f"  ⏭ skip: {entry['error'][:80]}")
            continue

        source_path, lineno = target
        try:
            source_code = source_path.read_text(encoding="utf-8")
        except OSError:
            entry.update(result="skip", detail="파일 읽기 실패")
            repairs.append(entry)
            continue

        logger.info(f"  → Claude 분석: {source_path.name}:{lineno}")
        analysis = _call_claude_fix(tb["traceback"], source_code, source_path.name)

        if not analysis:
            entry.update(result="error", detail="Claude API 오류")
            repairs.append(entry)
            continue

        entry["root_cause"] = analysis.get("root_cause", "")
        entry["fix_summary"] = analysis.get("fix_summary", "")
        entry["confidence"] = analysis.get("confidence", 0)

        confidence = analysis.get("confidence", 0)
        can_fix = analysis.get("can_auto_fix", False)
        orig = analysis.get("original_code") or ""
        fixed = analysis.get("fixed_code") or ""

        if not can_fix or confidence < 0.7:
            entry.update(
                result="manual_required",
                detail=f"수동 수정 필요 (확신도 {confidence:.0%}): {entry['root_cause']}"
            )
            logger.warning(f"  ⚠️  수동 필요: {entry['detail']}")
            repairs.append(entry)
            continue

        if not orig or not fixed or orig == fixed:
            entry.update(result="no_change", detail="코드 변경 불필요")
            repairs.append(entry)
            continue

        if dry_run:
            entry.update(
                result="dry_run",
                detail=f"[dry-run] 수정 예정 (확신도 {confidence:.0%}): {entry['fix_summary']}"
            )
            logger.info(f"  🔍 {entry['detail']}")
        else:
            ok = _apply_fix(source_code, orig, fixed, source_path)
            entry.update(
                result="fixed" if ok else "failed",
                detail=entry["fix_summary"] if ok else "파일 수정 실패 (원본 코드 불일치)"
            )

        repairs.append(entry)

    auto_fixed = sum(1 for r in repairs if r.get("result") == "fixed")
    manual_req = sum(1 for r in repairs if r.get("result") == "manual_required")

    result = {
        "timestamp": datetime.now().isoformat(),
        "tracebacks_found": len(tracebacks),
        "critical_errors": len(critical_lines),
        "critical_samples": critical_lines[-3:],
        "repairs": repairs,
        "auto_fixed": auto_fixed,
        "manual_required": manual_req,
        "dry_run": dry_run,
    }
    _save_result(result)

    logger.info(
        f"[CodeRepair] 완료 | 트레이스백: {len(tracebacks)}개 | "
        f"자동수정: {auto_fixed}개 | 수동필요: {manual_req}개"
    )
    return result


def _save_result(result: dict) -> None:
    """결과를 logs/code_repair.json과 docs/data/code_repairs.json에 저장합니다."""
    history = []
    if CODE_REPAIR_LOG.exists():
        try:
            history = json.loads(CODE_REPAIR_LOG.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.insert(0, result)
    history = history[:30]
    CODE_REPAIR_LOG.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    _DOCS.mkdir(parents=True, exist_ok=True)
    (_DOCS / "code_repairs.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(_LOGS / "code_repair.log"), encoding="utf-8"),
        ],
    )
    dry = "--dry" in sys.argv
    result = run_code_repair(dry_run=dry)
    print(f"\n{'[DRY-RUN] ' if dry else ''}트레이스백: {result['tracebacks_found']}개")
    print(f"자동수정: {result['auto_fixed']}개 | 수동필요: {result['manual_required']}개")
    for r in result.get("repairs", []):
        icons = {"fixed": "✅", "manual_required": "⚠️", "skip": "⏭", "dry_run": "🔍", "no_change": "✓"}
        icon = icons.get(r.get("result", ""), "❓")
        print(f"  {icon} [{r.get('file','?')}:{r.get('line','?')}] {r.get('detail','')}")
