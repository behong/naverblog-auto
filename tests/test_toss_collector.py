from unittest.mock import patch

from toss_open_api import best_selling_products, today_deal_products


LISTING_PAYLOAD = {
    "items": [
        {
            "rank": 1,
            "tacaItemId": 12345,
            "displayName": "테스트 상품",
            "thumbnailUrl": "https://resources-fe.toss.im/thumb.jpg",
            "productUrl": "https://toss.shopping/t/9876",
            "displayPrice": 9900,
            "originalPrice": 12900,
            "discountRate": 23,
            "isSoldOut": False,
            "reviewScore": 4.8,
            "reviewCount": 120,
        }
    ],
    "nextCursor": "next-page",
    "hasNext": True,
}


@patch("toss_open_api.api_request", return_value=LISTING_PAYLOAD)
def test_best_selling_products_uses_documented_path_and_normalizes_card(mock_request):
    result = best_selling_products(size=120)

    mock_request.assert_called_once_with(
        "GET", "/products/best-selling", params={"size": 100}
    )
    assert result["has_next"] is True
    assert result["next_cursor"] == "next-page"
    assert result["items"] == [
        {
            "taca_item_id": "12345",
            "title": "테스트 상품",
            "thumbnail_url": "https://resources-fe.toss.im/thumb.jpg",
            "product_url": "https://toss.shopping/t/9876",
            "display_price": 9900,
            "original_price": 12900,
            "discount_rate": 23,
            "is_sold_out": False,
            "review_score": 4.8,
            "review_count": 120,
            "rank": 1,
            "end_at": "",
        }
    ]


@patch("toss_open_api.api_request", return_value={"items": [], "nextCursor": None, "hasNext": False})
def test_today_deals_caps_requested_size_at_thirty(mock_request):
    result = today_deal_products(size=99)

    mock_request.assert_called_once_with(
        "GET", "/products/today-deals", params={"size": 30}
    )
    assert result == {"items": [], "next_cursor": "", "has_next": False}


@patch("toss_collector.store_toss_collection", return_value={"id": "run-1", "saved_count": 1})
@patch(
    "toss_collector.best_selling_products",
    return_value={"items": [{"taca_item_id": "1"}], "has_next": False, "next_cursor": ""},
)
def test_collect_toss_listing_persists_documented_best_listing(mock_best, mock_store):
    from toss_collector import collect_toss_listing

    result = collect_toss_listing("best-selling", 30)

    mock_best.assert_called_once_with(size=30)
    mock_store.assert_called_once_with("best-selling", 30, [{"taca_item_id": "1"}])
    assert result == {
        "source": "best-selling",
        "requested_size": 30,
        "saved_count": 1,
        "has_next": False,
        "next_cursor_present": False,
        "run_id": "run-1",
    }
