import unittest

from automation.coupang_pipeline import (
    CoupangCandidate,
    CoupangCandidateValidationError,
    build_coupang_approval_draft,
)


class CoupangPipelineTests(unittest.TestCase):
    def _candidate(self, **overrides):
        values = {
            "product_id": "1234567890",
            "product_name": "테스트 생활용품",
            "composition": "2개입",
            "product_url": "https://www.coupang.com/vp/products/1234567890",
            "affiliate_url": "https://link.coupang.com/a/example",
            "original_image_url": "https://image10.coupangcdn.com/image/test/product.jpg",
            "normal_price": 20000,
            "sale_price": 15000,
            "conditional_price": 12000,
            "price_condition": "와우회원 쿠폰 적용 시",
            "description": "실사용에 필요한 구성을 확인한 상품입니다.",
            "features": ("구성 확인", "보관 편의", "실속 가격"),
            "audiences": ("생활용품 구매자", "가성비를 찾는 분", "정기 구매 고객"),
            "source_image_verified": True,
        }
        values.update(overrides)
        return CoupangCandidate(**values)

    def test_builds_approval_only_category_42_draft(self):
        result = build_coupang_approval_draft(self._candidate())

        self.assertTrue(result["approval_only"])
        self.assertEqual(result["platform"], "coupang")
        self.assertEqual(result["category_no"], 42)
        self.assertIn("카테고리", "카테고리 42")
        self.assertIn("쿠팡 파트너스", result["draft"]["body"])
        self.assertIn("최저 구매가 12,000원", result["draft"]["body"])
        self.assertIn("#골드박스", result["draft"]["tags"])

    def test_rejects_unverified_source_image(self):
        with self.assertRaisesRegex(CoupangCandidateValidationError, "원본 대표 이미지 검증"):
            build_coupang_approval_draft(self._candidate(source_image_verified=False))

    def test_rejects_non_affiliate_link(self):
        with self.assertRaisesRegex(CoupangCandidateValidationError, "파트너스 단축 링크"):
            build_coupang_approval_draft(self._candidate(affiliate_url="https://www.coupang.com/vp/products/1234567890"))

    def test_accepts_current_price_without_price_order_requirement(self):
        result = build_coupang_approval_draft(self._candidate(normal_price=10000, sale_price=15000, conditional_price=12000))
        self.assertEqual(result["category_no"], 42)
        self.assertIn("최저 구매가 12,000원", result["draft"]["body"])


if __name__ == "__main__":
    unittest.main()
