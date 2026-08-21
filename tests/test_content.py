import unittest

from automation.content import (
    CONDITIONAL_PRICE_NOTICE,
    COUPANG_DISCLOSURE,
    TOSS_DISCLOSURE,
    ContentValidationError,
    Product,
    build_coupang_post,
    build_threads_post,
    build_toss_post,
)


class ContentTests(unittest.TestCase):
    def test_toss_post_has_original_image_link_disclosure_and_blank_paragraphs(self) -> None:
        product = Product(
            platform="toss",
            product_id="t-1",
            name="테스트 베이글",
            composition="100g, 2개",
            image_path="C:/data/source-product.jpg",
            affiliate_url="https://toss.im/_m/test",
            price=6800,
        )
        post = build_toss_post(product)

        self.assertEqual(post["category_no"], 39)
        self.assertIn("상품 자세히 보기\n\nhttps://toss.im/_m/test", post["body"])
        self.assertIn(TOSS_DISCLOSURE, post["body"])
        self.assertGreaterEqual(len(post["tags"]), 5)
        self.assertLessEqual(len(post["tags"]), 7)

    def test_coupang_post_uses_short_affiliate_template_and_required_tags(self) -> None:
        product = Product(
            platform="coupang",
            product_id="c-1",
            name="테스트 티셔츠",
            composition="1개",
            image_path="C:/data/source-product.webp",
            affiliate_url="https://link.coupang.com/a/test",
            normal_price=13000,
            sale_price=7000,
            conditional_price=500,
            price_condition="와우회원 쿠폰",
        )
        post = build_coupang_post(product)

        self.assertEqual(post["category_no"], 42)
        self.assertEqual(post["title"], "[테스트 티셔츠] 500원")
        self.assertIn("실제 할인 조건: 와우회원 쿠폰 적용 시 최저 구매가 500원", post["body"])
        self.assertIn("구성: 1개", post["body"])
        self.assertNotIn("특징", post["body"])
        self.assertNotIn("추천 대상", post["body"])
        self.assertIn(COUPANG_DISCLOSURE, post["body"])
        self.assertIn("#골드박스", post["tags"])
        self.assertIn("#쿠팡파트너스", post["tags"])

    def test_threads_requires_published_source_and_image(self) -> None:
        product = Product(
            platform="toss",
            product_id="t-2",
            name="테스트 상품",
            composition="1개",
            image_path="C:/data/source-product.jpg",
            affiliate_url="https://toss.im/_m/test",
            price=1000,
        )
        result = build_threads_post(
            product,
            {"platform": "toss", "status": "PUBLISHED", "naver_post_url": "https://blog.naver.com/a/1"},
        )
        self.assertLessEqual(len(result["text"]), 300)
        self.assertEqual(result["image_path"], product.image_path)

        with self.assertRaises(ContentValidationError):
            build_threads_post(product, {"platform": "toss", "status": "FAILED", "naver_post_url": "https://blog.naver.com/a/1"})


if __name__ == "__main__":
    unittest.main()
