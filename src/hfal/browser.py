"""Headless Chromium (Playwright) for pages plain HTTP cannot read. Decided Nov 14, 2026 (owner).

Used only as a fallback, by `hfal fetch` and `hfal discover`, when the plain download is blocked, fails, or
returns a page with no links (pages built by JavaScript), and by discovery when the plain crawl finds no PDF or
Word document. Everything it collects is marked (`fetched_with_browser` in the manifest, `browser` in the
discovery record) and `hfal report` and the attrition table say so, as for robots.txt.

What it does not do: it never solves or clicks a CAPTCHA, never hides that it is a bot (the user agent is the
headless browser's own, which says "HeadlessChrome", followed by ours), and never logs in. A page that shows a
CAPTCHA is returned with status "captcha" and the hospital stays excluded as a bot check.
"""

import re

from .fetch import user_agent

CAPTCHA_MARKERS = re.compile(
    r"hcaptcha\.com|google\.com/recaptcha|recaptcha/api|challenges\.cloudflare\.com/turnstile|cf-turnstile"
    r"|verify (that )?you are (a )?human|are you a robot|captcha-delivery\.com|px-captcha|Radware Block Page",
    re.I)


def is_captcha(html: str) -> bool:
    return bool(CAPTCHA_MARKERS.search(html))


class Browser:
    """One headless Chromium for a whole run, started on first use. Use as a context manager.

    fetch(url) -> {"status": int | "captcha" | "error: ...", "final_url", "content_type", "body"}.
    Pages are rendered (JavaScript run, then up to settle_ms for the network to go quiet) and the rendered
    HTML is returned. Documents (PDF, Word) are returned as the server sent them.
    """

    def __init__(self, timeout_seconds: float = 30, settle_ms: int = 5000):
        self.timeout_ms = int(timeout_seconds * 1000)
        self.settle_ms = settle_ms
        self._pw = self._browser = self._context = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _start(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        probe = self._browser.new_page()
        ua = probe.evaluate("navigator.userAgent")
        probe.close()
        # Honest: the browser's own user agent (it says HeadlessChrome) plus ours.
        self._context = self._browser.new_context(user_agent=f"{ua} {user_agent()}", accept_downloads=False)

    def close(self):
        for thing in (self._context, self._browser):
            try:
                if thing:
                    thing.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()
        self._pw = self._browser = self._context = None

    def fetch(self, url: str) -> dict:
        from playwright.sync_api import Error as PlaywrightError

        if self._context is None:
            self._start()
        page = self._context.new_page()
        last_doc = {}       # status of the last main-frame document response (a passed JS check navigates)

        def on_response(r):
            if r.request.is_navigation_request() and r.frame == page.main_frame:
                last_doc.update(status=r.status, url=r.url, ctype=r.headers.get("content-type", ""))

        page.on("response", on_response)
        try:
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            except PlaywrightError as e:
                if "Download is starting" in str(e) or "net::ERR_ABORTED" in str(e):
                    return self._download(url)          # a PDF or Word file: Chromium hands it to downloads
                return {"status": f"error: {str(e).splitlines()[0][:120]}", "final_url": url,
                        "content_type": "", "body": b""}
            if resp is None:
                return {"status": "error: no response", "final_url": url, "content_type": "", "body": b""}
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype.lower():
                return {"status": resp.status, "final_url": resp.url, "content_type": ctype, "body": resp.body()}
            try:
                page.wait_for_load_state("networkidle", timeout=self.settle_ms)
            except PlaywrightError:
                pass                                    # busy pages never go quiet; take what has rendered
            html = page.content()
            status = last_doc.get("status", resp.status)
            if is_captcha(html):
                status = "captcha"
            return {"status": status, "final_url": page.url, "content_type": last_doc.get("ctype", ctype),
                    "body": html.encode("utf-8")}
        finally:
            page.close()

    def _download(self, url: str) -> dict:
        """A document link: request it with the browser's cookies and user agent."""
        r = self._context.request.get(url, timeout=self.timeout_ms)
        return {"status": r.status, "final_url": r.url, "content_type": r.headers.get("content-type", ""),
                "body": r.body()}

    def get(self, url: str):
        """(status, content_type, body), the shape discover.crawl expects."""
        r = self.fetch(url)
        return r["status"], r["content_type"], r["body"]
