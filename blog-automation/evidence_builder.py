"""수집 자료 → 자료팩(evidence pack) 생성.

자료팩 스키마:
{
  "keyword": "...",
  "collectedAt": "ISO8601",
  "facts": [
    {"claim": "...", "source_title": "...", "source_url": "https://...",
     "published_at": "YYYY-MM-DD", "verified": bool}
  ]
}

글 작성 AI는 자료팩에 없는 숫자·날짜·정책 변경 내용을 임의로 작성하면 안 됩니다.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_EVIDENCE_DIR = os.path.join(os.path.dirname(__file__), "logs", "evidence")


def _safe_filename(keyword: str) -> str:
    return re.sub(r"[^\w가-힣]", "_", keyword)[:40] or "evidence"


def build_evidence_pack(research: dict) -> dict:
    """조사 자료에서 Claude로 핵심 사실을 추출해 자료팩을 만듭니다."""
    keyword = research.get("keyword", "")
    materials = research.get("materials") or []
    empty = {"keyword": keyword,
             "collectedAt": datetime.now(timezone.utc).isoformat(),
             "facts": []}
    if not materials:
        return empty
    try:
        import anthropic
        from config import claude_text, ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return empty
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        mat_text = "\n\n".join(
            f"[{i+1}] 제목: {m['title']}\nURL: {m['url']}\n"
            f"발행: {m.get('published_at', '')}\n"
            f"내용: {(m.get('body') or m.get('snippet', ''))[:1200]}"
            for i, m in enumerate(materials)
        )
        required = "\n".join(f"- {f}" for f in research.get("required_facts", []))
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": (
                    f"키워드: \"{keyword}\"\n"
                    f"확인이 필요한 사실:\n{required or '- (자유 추출)'}\n\n"
                    f"아래 수집 자료에서 글에 인용할 수 있는 핵심 사실을 추출하세요.\n\n"
                    f"{mat_text}\n\n"
                    "규칙:\n"
                    "1. 반드시 위 자료에 명시된 내용만 추출 — 자료에 없는 내용 추론 금지\n"
                    "2. 숫자·날짜·정책 내용은 자료 원문 그대로\n"
                    "3. source_url은 해당 사실이 나온 자료의 URL 그대로 복사\n"
                    "4. 자료들이 서로 모순되면 더 신뢰할 수 있는 출처(정부·공식) 기준\n\n"
                    "JSON만 응답:\n"
                    '{"facts": [{"claim": "구체적 사실 (숫자·날짜 포함)", '
                    '"source_title": "자료 제목", "source_url": "https://...", '
                    '"published_at": "YYYY-MM-DD 또는 빈 문자열"}]}\n'
                    "사실은 3~8개. 자료가 부실하면 확실한 것만."
                ),
            }],
        )
        raw = claude_text(msg).strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e <= s:
            return empty
        parsed = json.loads(raw[s:e + 1])
        facts = []
        valid_urls = {m["url"] for m in materials}
        for f in parsed.get("facts", []):
            if not isinstance(f, dict) or not f.get("claim"):
                continue
            url = str(f.get("source_url", "")).strip()
            # 환각 URL 방지: 수집 자료에 실제로 있던 URL만 인정
            if url not in valid_urls:
                continue
            facts.append({
                "claim": str(f["claim"]).strip(),
                "source_title": str(f.get("source_title", "")).strip(),
                "source_url": url,
                "published_at": str(f.get("published_at", "")).strip(),
                "verified": False,  # source_validator가 검증 후 True로
            })
        pack = {"keyword": keyword,
                "collectedAt": datetime.now(timezone.utc).isoformat(),
                "facts": facts}
        logger.info(f"자료팩 생성: 사실 {len(facts)}개 — '{keyword}'")
        return pack
    except Exception as exc:
        logger.warning(f"자료팩 생성 실패: {exc}")
        return empty


def save_evidence_pack(pack: dict) -> str:
    """자료팩을 logs/evidence/에 저장하고 경로를 반환합니다."""
    try:
        os.makedirs(_EVIDENCE_DIR, exist_ok=True)
        path = os.path.join(_EVIDENCE_DIR, f"{_safe_filename(pack.get('keyword', ''))}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pack, f, ensure_ascii=False, indent=2)
        return path
    except Exception as exc:
        logger.debug(f"자료팩 저장 실패: {exc}")
        return ""


_CRITICAL_WORDS = ("한도", "정책", "변경", "시행", "세율", "금리", "지원금",
                   "보조금", "요금", "가격", "수수료", "%", "원", "개정", "법")


def _is_critical(claim: str) -> bool:
    """중요 사실(수치·정책) 여부 — A/B 등급 출처가 필요합니다."""
    return bool(re.search(r"\d", claim)) or any(w in claim for w in _CRITICAL_WORDS)


def format_evidence_for_prompt(pack: dict | None) -> str:
    """자료팩을 글 작성 프롬프트 블록으로 변환합니다.

    완료 기준: 중요한 수치·정책 사실은 A/B 등급 출처가 있는 것만 사용.
    C/D 등급 출처뿐인 중요 사실은 제외되고, 자료팩이 없으면
    '검증 불가 수치 작성 금지' 폴백 규칙을 반환합니다.
    """
    facts = (pack or {}).get("facts") or []
    verified = [f for f in facts if f.get("verified")]
    pool = verified if verified else facts
    # 중요 수치·정책 사실은 A/B 등급 출처만 인정 (등급 정보 없으면 통과 — 구버전 팩 호환)
    usable, dropped_critical = [], 0
    for f in pool:
        grade = f.get("grade", "")
        if grade and grade not in ("A", "B") and _is_critical(f.get("claim", "")):
            dropped_critical += 1
            continue
        usable.append(f)
    if dropped_critical:
        logger.info(f"자료팩: 중요 사실 {dropped_critical}개 제외 (A/B 등급 출처 없음)")
    if not usable:
        return """
━━━ 사실 작성 규칙 (자료팩 없음) ━━━
이 글에는 검증된 자료팩이 없습니다. 다음을 반드시 지키세요:
✗ 구체적인 숫자·통계·날짜·정책 변경 내용을 임의로 만들어 쓰지 마세요
✓ 수치가 필요한 자리에는 "공식 발표를 확인하세요", "기관 홈페이지 기준" 등으로 안내
✓ 일반적으로 알려진 원리·개념·방법 설명은 가능"""

    lines = []
    for i, f in enumerate(usable, 1):
        pub = f" ({f['published_at']})" if f.get("published_at") else ""
        grade = f" [등급 {f['grade']}]" if f.get("grade") else ""
        stale = " ⚠️오래된 자료 — 최신 여부 언급 필요" if f.get("stale") else ""
        lines.append(
            f"{i}. {f['claim']}{stale}\n"
            f"   출처{grade}: {f.get('source_title', '')}{pub} — {f.get('source_url', '')}"
        )
    facts_text = "\n".join(lines)
    return f"""
━━━ 검증된 자료팩 (사실 작성의 유일한 근거) ━━━
아래는 이 키워드에 대해 실제 자료에서 추출·검증한 사실입니다.

{facts_text}

⚠️ 필수 규칙:
1. 숫자·날짜·정책 변경 내용은 위 자료팩에 있는 것만 사용하세요
2. 자료팩에 없는 수치·통계·한도·일정을 임의로 만들어 쓰지 마세요
3. 자료팩에 없는 내용이 필요하면 "공식 발표를 확인하세요" 등으로 안내
4. sources 필드에는 위 자료팩의 출처(URL 그대로)를 우선 사용하세요"""
