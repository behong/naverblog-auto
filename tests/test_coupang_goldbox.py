import unittest

from automation.coupang_goldbox import normalize_goldbox_candidates, to_review_payload


class CoupangGoldboxTests(unittest.TestCase):
    def _candidate(self, **overrides):
        values = {
            "candidate_id": "goldbox-preview-1",
            "product_name": "생활용품 테스트, 2개",
            "preview_image_url": "https://thumbnail1.coupangcdn.com/thumbnails/remote/example.jpg",
            "displayed_normal_price": 12000,
            "displayed_sale_price": 8000,
        }
        values.update(overrides)
        return values

    def test_keeps_complete_non_travel_candidate_and_sorts_by_sale_price(self):
        previews, summary = normalize_goldbox_candidates([
            self._candidate(candidate_id="a", displayed_sale_price=9000),
            self._candidate(candidate_id="b", product_name="식품 테스트", displayed_sale_price=5000),
        ])

        self.assertEqual(summary["kept"], 2)
        self.assertEqual([item.candidate_id for item in previews], ["b", "a"])
        payload = to_review_payload(previews, summary)
        self.assertTrue(payload["review_only"])
        self.assertTrue(payload["candidates"][0]["requires_partner_link_generation"])

    def test_keeps_travel_and_excludes_incomplete_titles(self):
        previews, summary = normalize_goldbox_candidates([
            self._candidate(candidate_id="travel", product_name="[평창] 리조트 숙박 특가"),
            self._candidate(candidate_id="cut", product_name="물티슈 캡형,…"),
        ])

        self.assertEqual([item.candidate_id for item in previews], ["travel"])
        self.assertEqual(summary["kept"], 1)
        self.assertEqual(summary["excluded_incomplete_title"], 1)

    def test_excludes_invalid_price_order_and_non_coupang_image(self):
        previews, summary = normalize_goldbox_candidates([
            self._candidate(candidate_id="price", displayed_normal_price=5000, displayed_sale_price=7000),
            self._candidate(candidate_id="image", preview_image_url="https://example.com/image.jpg"),
        ])

        self.assertEqual(previews, [])
        self.assertEqual(summary["excluded_price"], 1)
        self.assertEqual(summary["excluded_image"], 1)


if __name__ == "__main__":
    unittest.main()
