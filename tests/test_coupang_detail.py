import unittest
from unittest.mock import patch

from automation.coupang_detail import fetch_coupang_detail, merge_partner_link_with_detail


DETAIL_HTML = """
<html><head>
<meta property="og:title" content="검증 상품, 1kg, 1개" />
<meta property="og:image" content="https://image1.coupangcdn.com/image/retail/images/original-product.jpg" />
</head><body>
35% 9,990원 7,990원 쿠팡판매가 6,480원 와우할인
</body></html>
"""


class _Response:
    status_code = 200
    text = DETAIL_HTML

    def raise_for_status(self):
        return None


class CoupangDetailTests(unittest.TestCase):
    @patch("automation.coupang_detail.requests.get", return_value=_Response())
    def test_fetches_general_and_wow_conditional_prices_with_original_image(self, _mock_get):
        detail = fetch_coupang_detail("https://www.coupang.com/vp/products/1?itemId=2&vendorItemId=3")

        self.assertEqual(detail["general_price"], 7990)
        self.assertEqual(detail["lowest_conditional_price"], 6480)
        self.assertEqual(detail["conditional_price_condition"], "와우할인")
        self.assertTrue(detail["source_image_verified"])

    def test_merge_keeps_result_review_only_and_requires_no_extra_detail_check(self):
        link_record = {
            "affiliate_url": "https://coupa.ng/example",
            "product_url": "https://www.coupang.com/vp/products/1?itemId=2&vendorItemId=3",
            "product_name": "old name",
        }
        detail = {
            "detail_page_fetched": True,
            "product_name": "검증 상품, 1kg, 1개",
            "general_price": 7990,
            "lowest_conditional_price": 6480,
            "conditional_price_condition": "와우할인",
            "source_image_url": "https://image1.coupangcdn.com/image/original.jpg",
            "source_image_verified": True,
        }

        merged = merge_partner_link_with_detail(link_record, detail)
        self.assertEqual(merged["product_name"], "검증 상품, 1kg, 1개")
        self.assertEqual(merged["general_price"], 7990)
        self.assertFalse(merged["requires_product_detail_verification"])
        self.assertTrue(merged["approval_only"])


if __name__ == "__main__":
    unittest.main()
