from __future__ import annotations

import unittest

from automation.coupang_pipeline import build_coupang_approval_draft
from coupang_publication import candidate_from_payload


class CoupangPublicationPolicyTests(unittest.TestCase):
    def payload(self) -> dict[str, object]:
        return {
            "product_id": "4591098403",
            "product_name": "올품 닭볶음탕용 닭고기 (냉장)",
            "composition": "1kg × 1개",
            "product_url": "https://www.coupang.com/vp/products/4591098403?itemId=5645768630",
            "affiliate_url": "https://coupa.ng/coTTff",
            "original_image_url": "https://image10.coupangcdn.com/image/retail/images/sample-product.jpg",
            "normal_price": 9990,
            "sale_price": 7590,
            "conditional_price": 2480,
            "price_condition": "와우회원 혜택 및 웰컴백 쿠폰 적용 시",
            "description": "냉장 닭고기 1kg 구성으로 닭볶음탕 요리에 활용하기 좋은 상품입니다.",
            "features": ["냉장 보관 상품", "1kg 단품 구성", "닭볶음탕용 절단 형태"],
            "audiences": ["닭볶음탕을 준비하는 가정", "냉장 식재료를 찾는 분", "조건부 특가를 확인할 수 있는 분"],
            "source_image_verified": True,
        }

    def test_conditional_price_is_preserved_with_explicit_condition(self) -> None:
        candidate = candidate_from_payload(self.payload())
        draft = build_coupang_approval_draft(candidate)
        content = draft["draft"]
        self.assertEqual(draft["category_no"], 42)
        self.assertIn("올품 닭볶음탕용 닭고기", content["title"])
        self.assertIn("2,480원", content["title"])
        self.assertIn("최저 구매가 2,480원", content["body"])
        self.assertIn("와우회원 혜택 및 웰컴백 쿠폰 적용 시", content["body"])
        self.assertIn("쿠팡 파트너스 활동", content["body"])

    def test_unverified_source_image_rejects_approval(self) -> None:
        payload = self.payload()
        payload["source_image_verified"] = False
        with self.assertRaises(ValueError):
            candidate_from_payload(payload)

    def test_current_price_does_not_require_legacy_price_order(self) -> None:
        payload = self.payload()
        payload["conditional_price"] = 10990
        candidate = candidate_from_payload(payload)
        self.assertEqual(candidate.conditional_price, 10990)


if __name__ == "__main__":
    unittest.main()
