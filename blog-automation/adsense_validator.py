"""
Google AdSense 정책 자동 검증기 — 8개 항목 점검

반영된 최신 AdSense 정책 (2025):
- Valuable Inventory Policy: AI 스팸 콘텐츠 금지, 독창적 가치 필수
- Made for Ads (MFA): 광고 수익 목적만의 콘텐츠 금지
- Dangerous/Harmful Content: 유해·금지 콘텐츠 엄격 금지
- E-E-A-T: 경험·전문성·권위·신뢰도 신호 필수
- AI-Generated Content: 인간 검토·편집 후 독창적 가치 추가 필요
- Copyright: 저작권 침해 금지
- Misleading Content: 허위·과장 정보 금지

검증 항목 (8개, 각 12점 만점 = 합계 96 → 100점 환산):
  1. originality    — 원본성 및 품질
  2. seo            — SEO 최적화
  3. structure      — 구조 및 가독성
  4. ad_placement   — 광고 배치 적합성
  5. harmful_content — 유해/금지 콘텐츠 (fail 시 즉시 reject)
  6. eeat           — E-E-A-T 신뢰도
  7. image_policy   — 이미지 정책
  8. ai_suspicion   — AI 생성 의심도

권장사항:
  upload  — 점수 ≥ 80, 필수 항목 통과
  review  — 점수 ≥ 65, 필수 항목 통과 (pending 저장)
  reject  — 점수 < 65 또는 harmful_content fail
"""

import json
import logging
import re
from config import claude_text

logger = logging.getLogger(__name__)

# ─── 스코어링 ───────────────────────────────────────────────────────────────
_SCORE_MAP = {"pass": 12, "warn": 7, "fail": 0}
_CHECKS = [
    "originality",
    "seo",
    "structure",
    "ad_placement",
    "harmful_content",
    "eeat",
    "image_policy",
    "ai_suspicion",
]
_MAX_RAW = len(_CHECKS) * _SCORE_MAP["pass"]   # 96

# 이 항목이 fail이면 점수 관계없이 즉시 reject
_MANDATORY_PASS = {"harmful_content"}

_THRESHOLD_UPLOAD = 80  # 80점 이상만 즉시 업로드
_THRESHOLD_REVIEW = 65

_LABELS_KO = {
    "originality":     "원본성 및 품질",
    "seo":             "SEO 최적화",
    "structure":       "구조 및 가독성",
    "ad_placement":    "광고 배치 적합성",
    "harmful_content": "유해/금지 콘텐츠",
    "eeat":            "E-E-A-T 신뢰도",
    "image_policy":    "이미지 정책",
    "ai_suspicion":    "AI 생성 의심도",
}
_ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌"}


# ─── 헬퍼 ────────────────────────────────────────────────────────────────────

def _strip_html(html: str, max_chars: int = 2800) -> str:
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()[:max_chars]


def _count_ads(html: str) -> int:
    return len(re.findall(r'adsbygoogle', html, re.IGNORECASE))


def _count_h2(html: str) -> int:
    return len(re.findall(r'<h2[\s>]', html, re.IGNORECASE))


def _default_pass() -> dict:
    """API 오류 시 warn 수준 기본 결과를 반환합니다. score=65(review)로 업로드를 막습니다."""
    return {
        "pass": True,
        "score": 65,
        "recommendation": "review",
        "checks": {
            k: {"status": "warn", "label": _LABELS_KO[k], "note": "검증 생략 (API 오류)", "icon": "⚠️"}
            for k in _CHECKS
        },
        "issues": [],
        "warnings": ["AdSense 검증이 API 오류로 생략됐습니다. 검토 후 수동 업로드 필요합니다."],
    }


def _log_result(title: str, result: dict) -> None:
    rec = result["recommendation"]
    icon_map = {"upload": "✅", "review": "⚠️", "reject": "❌"}
    logger.info(
        f"AdSense 검증 {icon_map[rec]} [{rec.upper()}] "
        f"점수: {result['score']}/100 — '{title[:35]}'"
    )
    for check in result["checks"].values():
        lvl = logging.DEBUG if check["status"] == "pass" else logging.INFO
        logger.log(lvl, f"  {check['icon']} {check['label']}: {check['note']}")
    for issue in result["issues"]:
        logger.warning(f"  🔴 {issue}")
    for warn in result["warnings"]:
        logger.debug(f"  🟡 {warn}")


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def validate_adsense(post_data: dict) -> dict:
    """
    Google AdSense 2025 정책 기준으로 포스트를 8개 항목 검증합니다.

    Returns:
        pass           (bool)   — reject가 아니면 True
        score          (int)    — 0~100
        recommendation (str)    — "upload" | "review" | "reject"
        checks         (dict)   — 항목별 {status, label, note, icon}
        issues         (list)   — fail 항목 설명
        warnings       (list)   — warn 항목 설명
    """
    title       = post_data.get("title", "")
    keyword     = post_data.get("keyword", "")
    labels      = post_data.get("labels", [])
    html        = post_data.get("content", "")
    faq         = post_data.get("faq", [])
    sources     = post_data.get("sources", [])
    word_count  = post_data.get("word_count", 0)

    plain_text   = _strip_html(html)
    ad_count     = _count_ads(html)
    h2_count     = _count_h2(html)
    faq_preview  = " | ".join(f.get("q", "") for f in faq[:3]) if faq else "없음"
    src_info     = f"{len(sources)}개 출처 포함" if sources else "출처 없음"

    try:
        import anthropic
        from config import claude_text, ANTHROPIC_API_KEY, CLAUDE_MODEL
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        prompt = f"""Google AdSense 2025 최신 정책 기준으로 다음 블로그 포스트를 8개 항목 검증하세요.

포스트 정보:
- 제목: {title}
- 키워드: {keyword}
- 글자 수: {word_count}자
- H2 헤딩 수: {h2_count}개
- AdSense 광고 슬롯 수: {ad_count}개
- 레이블: {', '.join(labels[:6])}
- FAQ: {faq_preview}
- 출처: {src_info}

본문 (앞 2800자):
{plain_text}

━━━ 검증 항목 ━━━ (각 항목: pass / warn / fail + 한 줄 근거)

1. originality — 원본성 및 품질 (AdSense Valuable Inventory / 가치 없는 콘텐츠 정책)
   판단 기준:
   • 독창적 관점·개인 경험이 구체적 수치·날짜·사례와 함께 실제로 포함됐는가?
   • 다른 사이트의 정보를 그대로 나열만 하지 않는가? (thin content 금지)
   • 글자 수 4000자 이상이면 pass, 2500~3999자면 warn, 2500자 미만이면 fail
   • 독자에게 실질적 가치를 주는가? (인터넷에 이미 넘치는 정보의 재조합이면 fail)
   • AI가 생성한 일반론 나열인지, 아니면 진짜 경험·인사이트가 담겼는지 판단

2. seo — SEO 최적화
   판단 기준:
   • 키워드가 자연스럽게 분산 배치됐는가? (20회 이상 반복이면 warn, 밀집 반복이면 fail)
   • 제목이 검색 의도에 맞는가?
   • 내용이 제목과 일치하는가? (낚시성 제목이면 fail)

3. structure — 구조 및 가독성
   판단 기준:
   • H2 헤딩 4개 이상이면 pass, 2~3개면 warn, 1개 이하면 fail
   • 단락이 지나치게 길지 않은가? (500자 이상 단락이 3개 이상이면 warn)
   • 전체적으로 읽기 쉬운 구조인가?

4. ad_placement — 광고 배치 적합성 (AdSense 광고 게재 정책)
   판단 기준:
   • 광고 슬롯이 4개 이하이면 pass (콘텐츠 충분 조건 하에)
   • 콘텐츠 대비 광고 비율이 적절한가? (글자 수 대비)
   • 광고가 콘텐츠 흐름을 심각하게 방해하지 않는가?

5. harmful_content — 유해/금지 콘텐츠 (가장 중요 — fail이면 즉시 거부)
   판단 기준:
   • 성인·폭력·혐오·불법·도박·약물·무기 관련 내용 없음
   • 허위 정보·과장된 의료/투자 주장 없음 (단, 면책 조항 있으면 OK)
   • 개인정보 수집 유도 없음
   • 저작권 침해 의심 내용 없음

6. eeat — E-E-A-T 신뢰도 (Google 품질 평가 기준)
   판단 기준:
   • 직접 경험 기반 내용이 포함됐는가? (1인칭 경험 서술)
   • 출처·참고자료가 인용됐는가?
   • 과도한 단정적 주장 없이 균형 잡힌 시각인가?
   • 저자 신뢰성 신호가 있는가? (전문 지식 표현)

7. image_policy — 이미지 정책 (저작권 정책)
   ★ 중요: 이미지가 없거나 적어도 저작권 위반이 없으면 반드시 "warn"으로 평가.
     이미지 부재 자체는 "fail"이 아님 — 텍스트만으로도 AdSense 정책 통과 가능.
   판단 기준:
   • alt 텍스트 없는 이미지가 많으면 warn
   • 이미지 출처가 네이버 검색 결과 기반이면 warn (저작권 주의)
   • 성인·혐오 이미지 삽입 없음
   • 이미지 없는 글이면 warn (SEO 및 가독성)

8. ai_suspicion — AI 생성 의심도 (Valuable Inventory / Spam 정책)
   판단 기준:
   • "또한, 더불어, 아울러" 과다 사용 없음
   • "이처럼, 정리하자면, 결론적으로" 자동요약 문구 없음
   • 모든 내용을 목록화하는 패턴 없음
   • 같은 길이 문장의 단조로운 반복 없음
   • 딱딱한 격식체·보고서 문체 없음
   • 인간적인 관점·감정·경험이 자연스럽게 녹아 있으면 pass

JSON만 응답 (설명 없이):
{{
  "checks": {{
    "originality":     {{"status": "pass|warn|fail", "note": "한 줄 근거"}},
    "seo":             {{"status": "pass|warn|fail", "note": "한 줄 근거"}},
    "structure":       {{"status": "pass|warn|fail", "note": "한 줄 근거"}},
    "ad_placement":    {{"status": "pass|warn|fail", "note": "한 줄 근거"}},
    "harmful_content": {{"status": "pass|warn|fail", "note": "한 줄 근거"}},
    "eeat":            {{"status": "pass|warn|fail", "note": "한 줄 근거"}},
    "image_policy":    {{"status": "pass|warn|fail", "note": "한 줄 근거"}},
    "ai_suspicion":    {{"status": "pass|warn|fail", "note": "한 줄 근거"}}
  }},
  "critical_issues": ["즉시 수정 필요한 심각한 문제 (없으면 빈 배열)"],
  "suggestions": ["개선 권장 사항 (없으면 빈 배열)"]
}}"""

        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = claude_text(msg).strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e <= s:
            logger.warning(f"AdSense 검증 JSON 파싱 실패 — 기본 처리: {raw[:200]}")
            return _default_pass()

        json_str = raw[s:e + 1]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # json_repair로 재시도 (Claude가 trailing comma 등 비표준 JSON 반환 시)
            try:
                import json_repair
                data = json_repair.repair_json(json_str, return_objects=True)
                if not isinstance(data, dict):
                    raise ValueError("json_repair 결과가 dict가 아님")
                logger.debug("AdSense 검증 JSON json_repair로 복구 성공")
            except Exception as repair_e:
                logger.warning(f"AdSense 검증 JSON 복구 실패 ({repair_e}) — 기본 처리")
                return _default_pass()
        checks_raw = data.get("checks", {})

        # 정규화
        checks: dict = {}
        for key in _CHECKS:
            raw_c = checks_raw.get(key, {})
            status = raw_c.get("status", "warn")
            if status not in _SCORE_MAP:
                status = "warn"
            checks[key] = {
                "status": status,
                "label": _LABELS_KO[key],
                "note": raw_c.get("note", ""),
                "icon": _ICON[status],
            }

        # 점수 계산 (96 → 100 환산)
        raw_score = sum(_SCORE_MAP[c["status"]] for c in checks.values())
        score = round(raw_score / _MAX_RAW * 100)

        # 필수 항목 fail 여부
        mandatory_failed = any(
            checks.get(k, {}).get("status") == "fail"
            for k in _MANDATORY_PASS
        )

        # 권장사항
        if mandatory_failed or score < _THRESHOLD_REVIEW:
            recommendation = "reject"
        elif score < _THRESHOLD_UPLOAD:
            recommendation = "review"
        else:
            recommendation = "upload"

        issues   = [f"[{checks[k]['label']}] {checks[k]['note']}"
                    for k in _CHECKS if checks[k]["status"] == "fail"]
        warnings = [f"[{checks[k]['label']}] {checks[k]['note']}"
                    for k in _CHECKS if checks[k]["status"] == "warn"]

        result = {
            "pass":           recommendation != "reject",
            "score":          score,
            "recommendation": recommendation,
            "checks":         checks,
            "issues":         issues + data.get("critical_issues", []),
            "warnings":       warnings + data.get("suggestions", []),
        }
        _log_result(title, result)
        return result

    except Exception as exc:
        logger.warning(f"AdSense 검증 오류 — 기본 통과 처리: {exc}")
        return _default_pass()


