import unittest

from automation_store import _publish_product_values


class AutoPublishContractTests(unittest.TestCase):
    def test_accepts_complete_toss_category_39_product(self) -> None:
        result = _publish_product_values(
            {
                "platform": "toss",
                "product_id": "item-123",
                "product_name": "검증 상품",
                "sale_price": "9900",
                "affiliate_url": "https://toss.im/_m/verified",
                "naver_category": "39",
            }
        )

        self.assertEqual(result["platform"], "toss")
        self.assertEqual(result["sale_price"], 9900)
        self.assertEqual(result["naver_category"], "39")

    def test_rejects_non_publication_category(self) -> None:
        with self.assertRaisesRegex(ValueError, "category must be 39"):
            _publish_product_values(
                {
                    "product_id": "item-123",
                    "product_name": "검증 상품",
                    "sale_price": 9900,
                    "affiliate_url": "https://toss.im/_m/verified",
                    "naver_category": "42",
                }
            )

    def test_rejects_missing_affiliate_link(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete"):
            _publish_product_values(
                {
                    "product_id": "item-123",
                    "product_name": "검증 상품",
                    "sale_price": 9900,
                    "affiliate_url": "",
                    "naver_category": "39",
                }
            )


if __name__ == "__main__":
    unittest.main()
