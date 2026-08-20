from __future__ import annotations

from telegram_approval import send_publication_approval


def main() -> None:
    result = send_publication_approval(
        [
            {
                "product_name": "설정 확인용 테스트 상품 — 실제 발행하지 않음",
                "display_price": 0,
            }
        ],
        source="telegram-setup-test",
    )
    print(f"TELEGRAM_APPROVAL_TEST_SENT batch={result['id']}")


if __name__ == "__main__":
    main()
