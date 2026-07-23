#!/usr/bin/env python3
"""
Google AdSense 정책 자동 업데이터
- 매주 AdSense 공식 정책 페이지 크롤링
- Claude AI로 핵심 내용 + 변경사항 추출
- logs/adsense_policies.json 저장
- adsense_validator.py가 최신 정책으로 프롬프트 강화

정책 출처 (공개 HTML, 인증 불필요):
  https://support.google.com/adsense/answer/48182   — 프로그램 정책 전문
  https://support.google.com/adsense/answer/9785582 — 가치 있는 인벤토리
  https://support.google.com/adsense/answer/1279141 — 광고 게재 정책
  https://support.google.com/adsense/answer/1282110 — 제한 콘텐츠

사용법:
  python adsense_policy_updater.py           # 정책 업데이트 실행
  python adsense_policy_updater.py --dry     # 크롤링만, 저장 안 함
  python adsense_policy_updater.py --force   # 최신 버전이어도 강제 재분석
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_BASE_DIR    = os.path.dirname(__file__)
_POLICY_FILE = os.path.join(_BASE_DIR, "logs", "adsense_policies.json")
_EXPORT_FILE = os.path.join(_BASE_DIR, os.pardir, "docs", "data", "adsense_policies.json")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
}

# 크롤링 대상 정책 페이지 (공개 Google Support 페이지)
_POLICY_SOURCES = [
    {
        "id":    "program_policies",
        "label": "AdSense 프로그램 정책",
        "url":   "https://support.google.com/adsense/answer/48182",
    },
    {
        "id":    "valuable_inventory",
        "label": "가치 있는 인벤토리 정책",
        "url":   "https://support.google.com/adsense/answer/9785582",
    },
    {
        "id":    "ad_placement",
        "label": "광고 게재 정책",
        "url":   "https://support.google.com/adsense/answer/1279141",
    },
    {
        "id":    "restricted_content",
        "label": "제한 콘텐츠 정책",
        "url":   "https://support.google.com/adsense/answer/1282110",
    },
]


# ─── 크롤링 ──────────────────────────────────────────────────────────────────

def _fetch_policy_page(url: str, retries: int = 3) -> str:
    """정책 페이지 HTML을 가져옵니다."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"HTTP {resp.status_code}: {url}")
        except requests.RequestException as e:
            logger.warning(f"요청 실패 ({attempt+1}/{retries}): {e}")
        if attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    return ""


def _extract_text_from_html(html: str, max_chars: int = 6000) -> str:
    """HTML에서 본문 텍스트를 추출합니다."""
    # script/style 제거
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    # 헤딩 보존 (h2/h3에 줄바꿈 삽입)
    text = re.sub(r'<h[23][^>]*>', '\n\n### ', text, flags=re.IGNORECASE)
    text = re.sub(r'</h[23]>', '\n', text, flags=re.IGNORECASE)
    # li → 줄 글머리 기호
    text = re.sub(r'<li[^>]*>', '\n• ', text, flags=re.IGNORECASE)
    # 나머지 태그 제거
    text = re.sub(r'<[^>]+>', ' ', text)
    # 인코딩 엔티티
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
               .replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


def fetch_all_policies() -> list[dict]:
    """모든 정책 페이지를 크롤링합니다."""
    results = []
    for src in _POLICY_SOURCES:
        logger.info(f"크롤링: {src['label']} ({src['url']})")
        html = _fetch_policy_page(src["url"])
        if not html:
            logger.warning(f"  ⚠️ 페이지 로드 실패 — 건너뜀: {src['id']}")
            results.append({**src, "text": "", "error": "fetch_failed"})
            continue
        text = _extract_text_from_html(html)
        results.append({**src, "text": text, "char_count": len(text)})
        logger.info(f"  ✅ {len(text)}자 추출")
        time.sleep(1)
    return results


# ─── Claude AI 분석 ──────────────────────────────────────────────────────────

def _analyze_policies_with_claude(pages: list[dict], prev_summary: str = "") -> dict:
    """Claude AI로 정책 내용을 분석하고 핵심 규칙 + 변경사항을 추출합니다."""
    from dotenv import load_dotenv
    load_dotenv()

    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, claude_generate
    except ImportError as e:
        logger.error(f"Anthropic SDK 임포트 실패: {e}")
        return {}

    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY 미설정")
        return {}

    # 유효한 페이지만
    valid_pages = [p for p in pages if p.get("text")]
    if not valid_pages:
        logger.error("크롤링된 정책 텍스트 없음")
        return {}

    pages_text = "\n\n".join(
        f"=== {p['label']} ===\n{p['text'][:3000]}"
        for p in valid_pages
    )

    change_context = (
        f"\n\n이전 정책 요약:\n{prev_summary[:1000]}" if prev_summary
        else "\n\n(이전 정책 요약 없음 — 최초 분석)"
    )

    prompt = f"""당신은 Google AdSense 정책 전문가입니다.
아래 Google AdSense 공식 정책 페이지 내용을 분석하여 블로그 자동화 시스템이 참고할 수 있는 구조화된 정책 가이드를 만드세요.

크롤링 날짜: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
{change_context}

━━━ 정책 페이지 내용 ━━━
{pages_text}

━━━ 분석 지시 ━━━

다음 JSON 형식으로만 응답하세요 (설명 없이):

{{
  "version": "{datetime.now(timezone.utc).strftime('%Y.%m')}",
  "fetched_at": "{datetime.now(timezone.utc).isoformat()}",
  "summary": "현재 AdSense 정책 핵심을 3~5문장으로 요약 (한국어 블로그 운영자 관점)",
  "key_rules": [
    {{
      "category": "콘텐츠 품질",
      "rules": [
        "구체적인 규칙 1 (위반 시 어떻게 되는지 포함)",
        "구체적인 규칙 2"
      ]
    }},
    {{
      "category": "금지 콘텐츠",
      "rules": ["규칙 목록"]
    }},
    {{
      "category": "광고 배치",
      "rules": ["규칙 목록"]
    }},
    {{
      "category": "AI 생성 콘텐츠",
      "rules": ["규칙 목록"]
    }},
    {{
      "category": "E-E-A-T 요건",
      "rules": ["규칙 목록"]
    }}
  ],
  "changes_from_previous": [
    "이전 대비 변경/강화된 정책 (없으면 빈 배열)"
  ],
  "validator_hints": {{
    "originality": "원본성 검증 시 최신 기준 요약 (1~2문장)",
    "ai_content":  "AI 콘텐츠 관련 최신 입장 (1~2문장)",
    "eeat":        "E-E-A-T 최신 요구사항 (1~2문장)",
    "prohibited":  "2025년 기준 금지 콘텐츠 유형 나열",
    "ad_density":  "광고 밀도 최신 기준 (1문장)"
  }},
  "critical_violations": [
    "즉시 계정 정지로 이어질 수 있는 위반 유형 목록"
  ],
  "writer_checklist": [
    "블로그 글 작성 전 체크해야 할 항목 (글쓴이용 실용 체크리스트, 10개 이내)"
  ]
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    logger.info("Claude AI 정책 분석 시작...")
    raw = claude_generate(
        client,
        model=CLAUDE_MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    if not raw:
        logger.error("Claude AI 응답 없음")
        return {}

    # JSON 추출
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e <= s:
        logger.error(f"JSON 파싱 실패: {raw[:200]}")
        return {}
    try:
        return json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        try:
            import json_repair
            result = json_repair.repair_json(raw[s:e + 1], return_objects=True)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        logger.error("JSON 파싱 최종 실패")
        return {}


# ─── 저장/로드 ────────────────────────────────────────────────────────────────

def load_current_policies() -> dict:
    """저장된 정책 JSON을 로드합니다. 없으면 빈 dict."""
    if not os.path.exists(_POLICY_FILE):
        return {}
    try:
        with open(_POLICY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_policies(data: dict) -> None:
    os.makedirs(os.path.dirname(_POLICY_FILE), exist_ok=True)
    with open(_POLICY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"정책 저장: {_POLICY_FILE}")

    # docs/data/ 에도 복사 (대시보드용)
    try:
        export_dir = os.path.normpath(_EXPORT_FILE)
        os.makedirs(os.path.dirname(export_dir), exist_ok=True)
        with open(export_dir, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"정책 내보내기: {export_dir}")
    except Exception as e:
        logger.warning(f"docs/data 내보내기 실패: {e}")


def _is_update_needed(current: dict, force: bool = False) -> bool:
    """마지막 업데이트로부터 7일 이상 경과했는지 확인합니다."""
    if force or not current:
        return True
    fetched = current.get("fetched_at", "")
    if not fetched:
        return True
    try:
        from datetime import timedelta
        last = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last).days >= 7
    except Exception:
        return True


# ─── 메인 ────────────────────────────────────────────────────────────────────

def run_policy_update(dry_run: bool = False, force: bool = False) -> dict:
    """정책 업데이트를 실행합니다."""
    current = load_current_policies()

    if not _is_update_needed(current, force=force):
        last = current.get("fetched_at", "")[:10]
        logger.info(f"정책이 최신 상태입니다 (마지막 업데이트: {last}) — 건너뜀")
        return current

    logger.info("=" * 55)
    logger.info("AdSense 정책 업데이트 시작")
    logger.info("=" * 55)

    # 크롤링
    pages = fetch_all_policies()
    success_count = sum(1 for p in pages if p.get("text"))
    logger.info(f"크롤링 완료: {success_count}/{len(pages)} 페이지 성공")

    if success_count == 0:
        logger.error("모든 정책 페이지 크롤링 실패 — 업데이트 중단")
        return current

    if dry_run:
        logger.info("[DRY RUN] 저장 건너뜀")
        for p in pages:
            if p.get("text"):
                logger.info(f"  {p['label']}: {p['char_count']}자")
        return current

    # Claude 분석
    prev_summary = current.get("summary", "")
    analysis = _analyze_policies_with_claude(pages, prev_summary=prev_summary)

    if not analysis:
        logger.error("Claude 분석 실패 — 크롤링 결과만 저장")
        # 분석 없이 기본 구조로 저장 (전 버전 유지)
        return current

    # 크롤링 메타데이터 추가
    analysis["source_pages"] = [
        {"id": p["id"], "label": p["label"], "url": p["url"],
         "char_count": p.get("char_count", 0), "error": p.get("error")}
        for p in pages
    ]
    analysis["updated_at"] = datetime.now(timezone.utc).isoformat()
    analysis["prev_version"] = current.get("version", "")

    # 변경사항 로그
    changes = analysis.get("changes_from_previous", [])
    if changes:
        logger.info(f"📢 정책 변경사항 {len(changes)}건 감지:")
        for c in changes[:5]:
            logger.info(f"  • {c}")
    else:
        logger.info("이전 대비 주요 변경사항 없음")

    _save_policies(analysis)

    logger.info("=" * 55)
    logger.info(f"AdSense 정책 업데이트 완료 (버전: {analysis.get('version')})")
    logger.info("=" * 55)

    return analysis


def get_validator_hints() -> dict:
    """adsense_validator.py에서 사용할 최신 정책 힌트를 반환합니다."""
    policies = load_current_policies()
    if not policies:
        return {}
    return policies.get("validator_hints", {})


def get_policy_summary_for_prompt() -> str:
    """검증 프롬프트에 주입할 최신 정책 요약 문자열을 반환합니다."""
    policies = load_current_policies()
    if not policies:
        return ""

    lines = []
    version = policies.get("version", "")
    if version:
        lines.append(f"[AdSense 정책 {version} 기준 최신 가이드라인]")

    summary = policies.get("summary", "")
    if summary:
        lines.append(summary)

    hints = policies.get("validator_hints", {})
    if hints.get("ai_content"):
        lines.append(f"• AI 콘텐츠: {hints['ai_content']}")
    if hints.get("originality"):
        lines.append(f"• 원본성: {hints['originality']}")
    if hints.get("eeat"):
        lines.append(f"• E-E-A-T: {hints['eeat']}")
    if hints.get("ad_density"):
        lines.append(f"• 광고 밀도: {hints['ad_density']}")

    changes = policies.get("changes_from_previous", [])
    if changes:
        lines.append(f"• 최근 변경: {'; '.join(changes[:3])}")

    violations = policies.get("critical_violations", [])
    if violations:
        lines.append(f"• 즉시 정지 위반: {'; '.join(violations[:3])}")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AdSense 정책 자동 업데이터")
    parser.add_argument("--dry",   action="store_true", help="크롤링만 (저장 안 함)")
    parser.add_argument("--force", action="store_true", help="7일 미경과 시에도 강제 업데이트")
    args = parser.parse_args()

    result = run_policy_update(dry_run=args.dry, force=args.force)
    if result.get("version"):
        print(f"\n✅ 정책 버전: {result['version']}")
        print(f"   요약: {result.get('summary', '')[:120]}...")
    else:
        print("\n⚠️  정책 업데이트 실패 또는 불필요")
        sys.exit(1)
