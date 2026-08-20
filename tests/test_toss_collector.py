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


@patch(
    "toss_collector.auto_issue_toss_share_links",
    return_value={
        "enabled": True,
        "candidates": 1,
        "issued": 1,
        "reused": 0,
        "skipped_sold_out": 0,
        "skipped_invalid": 0,
        "failed": 0,
        "quota_exceeded": False,
    },
)
@patch("toss_collector.store_toss_collection", return_value={"id": "run-1", "saved_count": 1})
@patch(
    "toss_collector.best_selling_products",
    return_value={"items": [{"taca_item_id": "1"}], "has_next": False, "next_cursor": ""},
)
def test_collect_toss_listing_persists_documented_best_listing(mock_best, mock_store, mock_auto_issue):
    from toss_collector import collect_toss_listing

    result = collect_toss_listing("best-selling", 30)

    mock_best.assert_called_once_with(size=30)
    mock_store.assert_called_once_with("best-selling", 30, [{"taca_item_id": "1"}])
    mock_auto_issue.assert_called_once_with([{"taca_item_id": "1"}])
    assert result == {
        "source": "best-selling",
        "requested_size": 30,
        "saved_count": 1,
        "has_next": False,
        "next_cursor_present": False,
        "run_id": "run-1",
        "auto_issuance": {
            "enabled": True,
            "candidates": 1,
            "issued": 1,
            "reused": 0,
            "skipped_sold_out": 0,
            "skipped_invalid": 0,
            "failed": 0,
            "quota_exceeded": False,
        },
    }


@patch(
    "toss_open_api.api_request",
    return_value={
        "tacaItemId": 12345,
        "publisherId": "550e8400-e29b-41d4-a716-446655440000",
        "shortUrl": "https://toss.im/_m/abcDE",
        "originUrl": "https://toss.shopping/t/9876?k=tracked",
    },
)
def test_issue_share_link_uses_documented_selected_item_request(mock_request):
    from toss_open_api import issue_share_link

    result = issue_share_link("12345", "550e8400-e29b-41d4-a716-446655440000")

    mock_request.assert_called_once_with(
        "POST",
        "/links",
        json_body={"tacaItemId": 12345, "publisherId": "550e8400-e29b-41d4-a716-446655440000"},
    )
    assert result["short_url"] == "https://toss.im/_m/abcDE"
    assert result["taca_item_id"] == "12345"


@patch("toss_collector.ensure_toss_share_link", return_value={"short_url": "https://toss.im/_m/existing", "reused": True})
@patch("toss_collector.admin_toss_publisher_id", return_value="550e8400-e29b-41d4-a716-446655440000")
def test_selected_share_link_uses_local_deduplication_before_issuing(mock_publisher, mock_ensure):
    from toss_collector import issue_toss_share_link

    result = issue_toss_share_link("12345")

    assert result["reused"] is True
    mock_publisher.assert_called_once()
    mock_ensure.assert_called_once()
