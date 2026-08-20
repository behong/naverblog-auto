from __future__ import annotations

from automation_store import check_duplicate


def main() -> int:
    result = check_duplicate("toss", "2588220177")
    post = result.get("post") or {}
    print(f"DUPLICATE_BLOCK_ACTIVE={bool(result.get('exists'))}")
    print(f"DUPLICATE_BLOCK_STATUS={str(post.get('status') or '')}")
    print(f"DUPLICATE_BLOCK_PUBLIC_URL_PRESENT={bool(post.get('naver_post_url'))}")
    return 0 if result.get("exists") and post.get("status") == "PUBLISHED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
