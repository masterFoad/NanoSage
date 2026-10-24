from __future__ import annotations

import unittest

import local_fetch


class LocalFetchTests(unittest.TestCase):
    def test_challenge_text_is_detected(self):
        for text in (
            "Checking your browser before accessing pmc.ncbi.nlm.nih.gov ...",
            "Cookies must be enabled\nEnable cookies for pubmed.ncbi.nlm.nih.gov",
            "Just a moment... please verify you are a human",
            # Real walls in front of one paper (2026-10-24): Anubis, a DOI resolver, NASA ADS.
            "# Making sure you're not a bot!\n\nLoading...\n\nYou are seeing this because the administrator",
            "JavaScript is disabled\nIn order to continue, we need to verify that you're not a robot.",
            "JavaScript is disabled In order to continue, you need to verify that you're not a robot by "
            "solving a CAPTCHA puzzle.",
        ):
            self.assertTrue(local_fetch.is_challenge_text(text), text[:40])

    def test_real_content_is_not_flagged(self):
        body = (
            "# Cryptobiosis\n\nTardigrades enter anhydrobiosis when water is lost. "
            "Trehalose accumulates in some species. " * 20
        )
        self.assertFalse(local_fetch.is_challenge_text(body))
        self.assertFalse(local_fetch.is_challenge_text(""))

    def test_hard_block_classification(self):
        self.assertTrue(local_fetch._is_hard_block("http 403"))
        self.assertTrue(local_fetch._is_hard_block("challenge page"))
        self.assertTrue(local_fetch._is_hard_block("direct fetch failed: SSLError"))
        # A thin page is still evidence and must not be classed as a block.
        self.assertFalse(local_fetch._is_hard_block("empty extraction (js-rendered or blocked)"))
        self.assertFalse(local_fetch._is_hard_block(None))

    def test_browser_budget_is_shared_and_bounded(self):
        budget = local_fetch.BrowserBudget(2)
        self.assertTrue(budget.claim())
        self.assertTrue(budget.claim())
        self.assertFalse(budget.claim())
        self.assertEqual(local_fetch.BrowserBudget(0).claim(), False)

    def test_ddg_redirect_unwrapping(self):
        wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=x"
        self.assertEqual(local_fetch._unwrap_ddg(wrapped), "https://example.com/a")
        self.assertEqual(local_fetch._unwrap_ddg("https://example.com/b"), "https://example.com/b")

    def test_needs_browser_ignores_genuinely_short_pages(self):
        self.assertIsNone(local_fetch.needs_browser("<html>hi</html>", "a real short page", 200))
        self.assertEqual(local_fetch.needs_browser("<html>x</html>", "", 403), "http 403")


if __name__ == "__main__":
    unittest.main()
