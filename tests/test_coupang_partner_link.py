import unittest

from automation.coupang_partner_link import CoupangLinkResultError, parse_coupang_partner_link_result


class CoupangPartnerLinkTests(unittest.TestCase):
    def _payload(self, **overrides):
        result = {
            "ok": True,
            "link_detected": True,
            "generated_urls": ["https://link.coupang.com/a/example", "https://coupa.ng/example"],
            "page_url": (
                "https://partners.coupang.com/#affiliate/ws/linkgeneration/PRODUCT/8174473713/19977722612"
                "?product%5BitemId%5D=19977722612&product%5BproductId%5D=8174473713"
                "&product%5BvendorItemId%5D=88377301608&product%5Btitle%5D=%EC%BD%94%EC%B9%B4%EC%BD%9C%EB%9D%BC%20%EC%A0%9C%EB%A1%9C"
                "&product%5BoriginPrice%5D=21600&product%5BsalesPrice%5D=13090"
                "&product%5Bimage%5D=https%3A%2F%2Fthumbnail11.coupangcdn.com%2Fimage.jpg&product%5Btravel%5D=false"
            ),
        }
        result.update(overrides)
        return {"frames": [{"frame_id": 0, "result": result}]}

    def test_parses_review_only_partner_link_result(self):
        result = parse_coupang_partner_link_result(self._payload())

        self.assertEqual(result["platform"], "coupang")
        self.assertEqual(result["product_id"], "8174473713")
        self.assertEqual(result["affiliate_url"], "https://coupa.ng/example")
        self.assertTrue(result["approval_only"])
        self.assertTrue(result["requires_product_detail_verification"])

    def test_rejects_non_partner_url(self):
        with self.assertRaisesRegex(CoupangLinkResultError, "파트너스 링크"):
            parse_coupang_partner_link_result(self._payload(generated_urls=["https://example.com/x"]))

    def test_accepts_travel_products_for_detail_verification(self):
        payload = self._payload()
        payload["frames"][0]["result"]["page_url"] = payload["frames"][0]["result"]["page_url"].replace("travel%5D=false", "travel%5D=true")
        result = parse_coupang_partner_link_result(payload)
        self.assertEqual(result["product_id"], "8174473713")
        self.assertTrue(result["requires_product_detail_verification"])
        self.assertTrue(result["requires_conditional_price_verification"])


if __name__ == "__main__":
    unittest.main()


class CoupangPartnerLinkBatchTests(unittest.TestCase):
    def _success_item(self, product_id="8174473713", sale_price="13090"):
        return {
            "ok": True,
            "generated_urls": ["https://coupa.ng/example"],
            "page_url": (
                f"https://partners.coupang.com/#affiliate/ws/linkgeneration/PRODUCT/{product_id}/19977722612"
                f"?product%5BitemId%5D=19977722612&product%5BproductId%5D={product_id}"
                "&product%5BvendorItemId%5D=88377301608&product%5Btitle%5D=%EC%BD%94%EC%B9%B4%EC%BD%9C%EB%9D%BC"
                f"&product%5BoriginPrice%5D=21600&product%5BsalesPrice%5D={sale_price}"
                "&product%5Bimage%5D=https%3A%2F%2Fthumbnail11.coupangcdn.com%2Fimage.jpg&product%5Btravel%5D=false"
            ),
            "candidate": {"product_name": "코카콜라"},
        }

    def test_batch_keeps_verified_records_and_separates_failures(self):
        from automation.coupang_partner_link import parse_coupang_batch_link_results

        records, failures, summary = parse_coupang_batch_link_results({
            "results": [self._success_item(), {"ok": False, "candidate": {"product_name": "실패 상품"}, "error": "candidate_card_not_found"}],
        })

        self.assertEqual(summary, {"input": 2, "verified": 1, "failed": 1})
        self.assertEqual(records[0]["product_id"], "8174473713")
        self.assertEqual(failures[0]["product_name"], "실패 상품")

    def test_batch_rejects_duplicate_product_ids(self):
        from automation.coupang_partner_link import parse_coupang_batch_link_results

        records, failures, summary = parse_coupang_batch_link_results({"results": [self._success_item(), self._success_item()]})

        self.assertEqual(summary["verified"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(failures[0]["reason"], "duplicate_product_id")
