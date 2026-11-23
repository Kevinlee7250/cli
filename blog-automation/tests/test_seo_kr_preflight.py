"""SEO KR 검사 회귀 테스트: 외부 API·Blogger 게시 없음."""
import unittest
from seo_kr_preflight import inspect_post


class SeoKrPreflightTests(unittest.TestCase):
    def test_clean_post(self):
        post = {
            "title": "벳푸 골프 준비 안내",
            "keyword": "벳푸 골프",
            "meta_description": "벳푸에서 라운딩을 준비할 때 확인할 기본 조건과 준비물.",
            "content": "<h2>벳푸 골프 준비</h2><p>교통편과 라운드 조건을 미리 확인하세요.</p>",
        }
        self.assertEqual(inspect_post(post)["status"], "pass")

    def test_placeholder_link_blocks(self):
        post = {"title": "준비", "keyword": "준비", "content": '<h2>준비</h2><p>설명</p><a href="#">보기</a>'}
        self.assertEqual(inspect_post(post)["status"], "hold")

    def test_no_fabricated_score(self):
        post = {"title": "제목", "content": "<p>내용</p>"}
        result = inspect_post(post)
        self.assertEqual(result["status"], "review")
        self.assertNotIn("rank", result)
        self.assertNotIn("adsense_score", result)

    def test_does_not_mutate(self):
        post = {"title": "정보", "content": "<h2>정보</h2><p>본문</p>", "keyword": "정보"}
        snapshot = dict(post)
        inspect_post(post)
        self.assertEqual(post, snapshot)


if __name__ == "__main__":
    unittest.main()
