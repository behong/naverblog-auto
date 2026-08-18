import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

from app import (
    AppHandler,
    DISCLOSURE,
    MetadataParser,
    analyze,
    generate_post,
    parse_pasted_text,
)
from toss_open_api import normalize_product
from toss_open_api import TossOpenApiError
from toss_open_api import health as open_api_health


SAMPLE = f"""{DISCLOSURE}
광천김 고소한 아몬드를 넣은 김자반, 40g, 10봉
https://toss.im/_m/JDmVmEU5"""


class BlogHelperTests(unittest.TestCase):
    def test_sitemap_and_robots_use_public_request_origin(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), AppHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_port}"
            headers = {"Host": "blog.example.com", "X-Forwarded-Proto": "https"}

            sitemap_request = urllib.request.Request(f"{base_url}/sitemap.xml", headers=headers)
            with urllib.request.urlopen(sitemap_request, timeout=5) as response:
                sitemap = response.read().decode("utf-8")
                self.assertEqual(response.headers.get_content_type(), "application/xml")
            self.assertIn("<loc>https://blog.example.com/</loc>", sitemap)

            robots_request = urllib.request.Request(f"{base_url}/robots.txt", headers=headers)
            with urllib.request.urlopen(robots_request, timeout=5) as response:
                robots = response.read().decode("utf-8")
                self.assertEqual(response.headers.get_content_type(), "text/plain")
            self.assertIn("Allow: /", robots)
            self.assertIn("Sitemap: https://blog.example.com/sitemap.xml", robots)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_parse_sample(self) -> None:
        parsed = parse_pasted_text(SAMPLE)
        self.assertEqual(
            parsed["product_name"],
            "광천김 고소한 아몬드를 넣은 김자반, 40g, 10봉",
        )
        self.assertEqual(parsed["share_url"], "https://toss.im/_m/JDmVmEU5")
        self.assertEqual(parsed["price"], "")

    def test_generate_food_post(self) -> None:
        result = generate_post(
            "광천김 고소한 아몬드를 넣은 김자반, 40g, 10봉",
            "https://toss.im/_m/JDmVmEU5",
            "7900",
        )
        self.assertEqual(
            result["title"],
            "광천김 고소한 아몬드를 넣은 김자반, 40g, 10봉, 7900원",
        )
        self.assertTrue(result["body"].startswith("[이미지 영역]"))
        self.assertIn("상품 자세히 보기\nhttps://toss.im/_m/JDmVmEU5", result["body"])
        self.assertTrue(result["body"].endswith(DISCLOSURE))
        self.assertIn("김자반", result["tags"])
        self.assertIn("상품추천", result["tags"])
        self.assertIn("쇼핑추천", result["tags"])
        self.assertIn("실속구매", result["tags"])
        self.assertIn("토스쇼핑", result["tags"])

    def test_parse_price_from_pasted_text(self) -> None:
        parsed = parse_pasted_text(
            "스테이퍼퓸 밤쉘 향수, 80ml, 7,900원\nhttps://toss.im/_m/example"
        )
        self.assertEqual(parsed["product_name"], "스테이퍼퓸 밤쉘 향수, 80ml")
        self.assertEqual(parsed["price"], "7900")

    def test_metadata_parser_attribute_order(self) -> None:
        parser = MetadataParser()
        parser.feed(
            '<html><head><title>기본 제목</title>'
            '<meta content="대표 제목" property="og:title">'
            '<meta content="https://shopping.toss.im/a.jpg" property="og:image">'
            "</head></html>"
        )
        self.assertEqual(parser.meta["og:title"], "대표 제목")
        self.assertEqual(parser.meta["og:image"], "https://shopping.toss.im/a.jpg")

    def test_open_api_product_prefers_main_image(self) -> None:
        product = normalize_product(
            {
                "tacaItemId": 12345,
                "displayName": "공식 API 상품",
                "displayPrice": 9900,
                "thumbnailUrl": "https://static.toss.im/thumb.jpg",
                "mainImageUrls": ["https://static.toss.im/main.jpg"],
                "isSoldOut": False,
            }
        )

        self.assertEqual(product["price"], "9900")
        self.assertEqual(product["images"], ["https://static.toss.im/main.jpg"])

    @patch("app.product_detail")
    @patch("app.open_api_configured", return_value=True)
    @patch("app.fetch_product_metadata")
    def test_analyze_uses_open_api_price_and_image(
        self, fetch_metadata, _configured, detail
    ) -> None:
        fetch_metadata.return_value = {
            "final_url": "https://toss.shopping/t/55063889",
            "title": "페이지 상품",
            "description": "",
            "images": ["https://shopping.toss.im/og.jpg"],
            "taca_item_id": "87464653",
            "taca_id": "55063889",
        }
        detail.return_value = {
            "title": "공식 상품",
            "price": "9900",
            "images": ["https://static.toss.im/main.jpg"],
            "is_sold_out": False,
        }

        result = analyze("공식 상품\nhttps://toss.im/_m/test")

        self.assertEqual(result["price"], "9900")
        self.assertEqual(result["metadata"]["price_source"], "toss-open-api")
        self.assertEqual(result["metadata"]["images"], ["https://static.toss.im/main.jpg"])

    @patch("app.product_detail", side_effect=TossOpenApiError("temporary"))
    @patch("app.open_api_configured", return_value=True)
    @patch("app.fetch_product_metadata")
    def test_analyze_requires_input_when_open_api_fails(
        self, fetch_metadata, _configured, _detail
    ) -> None:
        fetch_metadata.return_value = {
            "final_url": "https://toss.shopping/t/55063889",
            "title": "페이지 상품",
            "description": "",
            "images": ["https://shopping.toss.im/og.jpg"],
            "taca_item_id": "87464653",
            "taca_id": "55063889",
        }
        with self.assertRaisesRegex(ValueError, "Open API 조회에 실패"):
            analyze("페이지 상품\nhttps://toss.im/_m/test")

    @patch("toss_open_api.get_access_token", return_value="token")
    @patch("toss_open_api.OPEN_API_SECRET_KEY", "secret")
    @patch("toss_open_api.OPEN_API_ACCESS_KEY", "access")
    @patch("toss_open_api.OPEN_API_ENV", "production")
    def test_open_api_health_verifies_production_token(self, get_token) -> None:
        result = open_api_health()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["environment"], "production")
        get_token.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
