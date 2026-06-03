#!/usr/bin/env python3
"""이미지 검색 기능 테스트 스크립트 — 로컬 PC에서 실행하세요"""

import sys
import os
from dotenv import load_dotenv

load_dotenv()

def test_naver(keyword="오늘 핫이슈"):
    import requests
    cid = os.getenv("NAVER_CLIENT_ID", "")
    cs  = os.getenv("NAVER_CLIENT_SECRET", "")
    if not cid or not cs:
        print("❌ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 가 .env에 없습니다")
        return False

    print(f"🔍 네이버 이미지 검색: '{keyword}'")
    r = requests.get(
        "https://openapi.naver.com/v1/search/image",
        params={"query": keyword, "display": 3, "sort": "sim", "filter": "large"},
        headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": cs},
        timeout=10,
    )
    if r.status_code == 200:
        items = r.json().get("items", [])
        print(f"  ✅ 이미지 {len(items)}개 수집 성공!")
        for i, item in enumerate(items, 1):
            import re
            title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
            print(f"  [{i}] {title[:50]}")
            print(f"      {item.get('thumbnail','')[:80]}")
        return True
    else:
        print(f"  ❌ 실패 (HTTP {r.status_code}): {r.text[:200]}")
        print()
        print("  📌 해결 방법:")
        print("  1. https://developers.naver.com/apps/ 접속")
        print("  2. 앱 클릭 → API 설정 탭")
        print("  3. '이미지 검색' 체크 확인")
        print("  4. '웹 서비스 환경' → 이 PC의 공인 IP 또는 도메인 추가")
        print("     (공인 IP 확인: https://www.whatismyip.com)")
        return False


def test_duckduckgo(keyword="Korea news today"):
    from image_fetcher import _ddg_images
    print(f"\n🔍 DuckDuckGo 이미지 검색: '{keyword}'")
    imgs = _ddg_images(keyword, 3)
    if imgs:
        print(f"  ✅ 이미지 {len(imgs)}개 수집 성공!")
        for i, img in enumerate(imgs, 1):
            print(f"  [{i}] {img['title'][:50]}")
            print(f"      {img['url'][:80]}")
        return True
    else:
        print("  ❌ DuckDuckGo 이미지 검색 실패")
        return False


def test_full_pipeline(keyword="재테크 방법"):
    from image_fetcher import fetch_relevant_images, inject_images_into_content
    print(f"\n🚀 전체 파이프라인 테스트: '{keyword}'")
    imgs = fetch_relevant_images(
        keyword, count=3,
        naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
    )
    if imgs:
        print(f"  ✅ {len(imgs)}개 이미지 수집")
        sample_html = "<p>도입부 내용입니다.</p><h2>섹션1</h2><p>내용</p><h2>섹션2</h2><p>내용</p>"
        result = inject_images_into_content(sample_html, imgs, keyword)
        figure_count = result.count("<figure")
        print(f"  ✅ 본문 삽입 완료 — <figure> {figure_count}개")
        return True
    else:
        print("  ❌ 이미지 수집 실패 — 텍스트만으로 포스트 생성 진행됩니다 (정상)")
        return False


if __name__ == "__main__":
    keyword = sys.argv[1] if len(sys.argv) > 1 else "오늘 핫이슈"
    print("=" * 55)
    print("  블로그 자동화 — 이미지 기능 테스트")
    print("=" * 55)

    naver_ok = test_naver(keyword)
    ddg_ok   = test_duckduckgo(keyword)
    pipe_ok  = test_full_pipeline(keyword)

    print()
    print("=" * 55)
    print(f"네이버 이미지: {'✅ 정상' if naver_ok else '❌ 실패'}")
    print(f"DuckDuckGo   : {'✅ 정상' if ddg_ok   else '❌ 실패'}")
    print(f"전체 파이프라인: {'✅ 정상' if pipe_ok  else '⚠️  이미지 없이 진행'}")
    print("=" * 55)
    if naver_ok or ddg_ok:
        print("✅ 이미지 자동 삽입 기능 사용 가능합니다!")
    else:
        print("⚠️  네이버 앱 설정 후 재시도하거나, 텍스트만으로 사용 가능합니다.")
