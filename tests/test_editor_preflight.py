import os
import unittest

from playwright.sync_api import sync_playwright

from automation.editor_preflight import verify_editor_input


class EditorPreflightTests(unittest.TestCase):
    def test_keyboard_probe_succeeds_and_restores_blank_title_and_iframe_body(self) -> None:
        with sync_playwright() as playwright:
            launch_options = {"headless": True}
            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
            if executable_path:
                launch_options["executable_path"] = executable_path
            elif os.name != "nt" and os.path.exists("/usr/bin/chromium"):
                launch_options["executable_path"] = "/usr/bin/chromium"
            browser = playwright.chromium.launch(**launch_options)
            page = browser.new_page()
            try:
                page.set_content(
                    """
                    <input aria-label="제목" value="">
                    <iframe id="editor" srcdoc="<body contenteditable='true'></body>"></iframe>
                    """
                )
                page.locator("#editor").content_frame.locator("body").wait_for()

                result = verify_editor_input(page)

                self.assertTrue(result.ok)
                self.assertTrue(result.title.inserted)
                self.assertTrue(result.title.removed)
                self.assertTrue(result.body.inserted)
                self.assertTrue(result.body.removed)
                self.assertEqual(page.locator('input[aria-label="제목"]').input_value(), "")
                self.assertEqual(page.locator("#editor").content_frame.locator("body").inner_text().strip(), "")
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
