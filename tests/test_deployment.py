from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def test_cookie_mount_and_fallback_are_removed(self) -> None:
        sources = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("app.py", "Dockerfile", "docker-compose.yml")
        )
        for forbidden in (
            "TOSS_COOKIE_FILE",
            "TOSS_SHARELINK_COOKIE_STORE_FILE",
            "toss_sharelink_cookie.json",
            "fetch_authenticated_product",
            '"Cookie":',
        ):
            self.assertNotIn(forbidden, sources)

    def test_deploy_imports_only_open_api_variables(self) -> None:
        deploy = (ROOT / "deploy.ps1").read_text(encoding="utf-8")
        self.assertIn("(TOSS_OPEN_API_[A-Za-z0-9_]*)", deploy)
        self.assertIn(".env.docker.cutover", deploy)
        self.assertNotIn("--env-file ..\\total-10shop-260514", deploy)


if __name__ == "__main__":
    unittest.main()
