
import logging
import re
from typing import Optional

from markdownify import markdownify as md
from bs4 import BeautifulSoup
from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from app.core.config import Settings

# header kasÄ±tlÄ± olarak dahil EDÄ°LMEDÄ° bazÄ± siteler iÃ§eriÄŸi header div'leri iÃ§inde tutuyor.
_NOISE_TAGS = [
    "script", "style", "noscript", "iframe",
    "nav", "footer", "aside",
    "form", "button", "svg", "img",
    "meta", "link", "head",
]

# Eski Chrome UA bazÄ± anti-bot sistemleri tarafÄ±ndan engellenir
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class ScraperService:
    """
    Scrapes a URL using Playwright (Chromium, headless).

    Pipeline:
      1. Playwright ile sayfayÄ± yÃ¼kle (JavaScript render)
      2. inner_html() ile ham HTML al
      3. BeautifulSoup ile gereksiz etiketleri temizle (nav, footer, script vs.)
      4. markdownify ile Markdown'a Ã§evir (tablolar | col | col | ÅŸeklinde korunur)
      5. TemizlenmiÅŸ Markdown'Ä± dÃ¶ndÃ¼r â†’ LLM'e gÃ¶nder

    Usage::
        service = ScraperService(settings=get_settings(), logger=get_logger(__name__))
        text = await service.scrape("https://example.com")
    """

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger

    async def scrape(
        self,
        url: str,
        timeout_ms: Optional[int] = None,
    ) -> str:
        """
        Navigate to *url* and return its Markdown-formatted content.

        Args:
            url:        Target URL to scrape.
            timeout_ms: Page-load timeout in milliseconds.
                        Falls back to settings if omitted.

        Returns:
            Cleaned Markdown content of the fully loaded page.
            Tables are preserved in | col | format for LLM comprehension.

        Raises:
            RuntimeError: Wraps any Playwright or unexpected error.
        """
        timeout = timeout_ms or self._settings.scraper_default_timeout_ms
        self._logger.info("Scraping started | url=%s timeout_ms=%d", url, timeout)

        try:
            async with async_playwright() as playwright:
                browser: Browser = await playwright.chromium.launch(
                    headless=self._settings.scraper_headless,
                )
                context: BrowserContext = await browser.new_context(
                    user_agent=_USER_AGENT,
                    java_script_enabled=True,
                    # Viewport bÃ¼yÃ¼k tutmak lazy-load'u tetikler
                    viewport={"width": 1920, "height": 1080},
                )
                page: Page = await context.new_page()

                try:
                    # domcontentloaded: networkidle'dan daha gÃ¼venilir
                    # bazÄ± SPA siteler networkidle'a hiÃ§ ulaÅŸmaz.
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=timeout,
                    )

                    # Post-load: JS/AJAX render iÃ§in bekleme
                    # Otel siteleri ve YÃ–K Atlas gibi siteler domcontentloaded'dan
                    # SONRA JavaScript ile kartlarÄ±/tablolarÄ± render eder.
                    _CONTENT_SELECTORS = [
                        # Tablolar
                        "table", "tbody tr",
                        # Otel siteleri (otelpuan.com, booking.com vb.)
                        "[class*='hotel']", "[class*='otel']",
                        "[class*='card']", "[class*='listing']",
                        "[class*='property']", "[class*='result']",
                        # Fiyat/puan elementleri
                        "[class*='price']", "[class*='fiyat']",
                        "[class*='rating']", "[class*='puan']",
                        # Genel iÃ§erik alanlarÄ±
                        "main", "article", "[class*='content']",
                        "[class*='grid']", "[class*='list']",
                    ]
                    for sel in _CONTENT_SELECTORS:
                        try:
                            await page.wait_for_selector(
                                sel, state="visible", timeout=5_000,
                            )
                            self._logger.debug(
                                "Content element visible | selector=%s", sel
                            )
                            break
                        except PlaywrightTimeout:
                            continue

                    # JS render tamamlanmasÄ± iÃ§in 2 saniye sabit bekle
                    await page.wait_for_timeout(2_000)

                    # Sonsuz scroll: aÅŸaÄŸÄ± kaydÄ±r, yeni iÃ§erik gelene kadar
                    await self._scroll_to_load_all(page)

                    markdown = await self._extract_markdown(page)

                    self._logger.info(
                        "Scraping succeeded | url=%s chars=%d", url, len(markdown)
                    )
                    return markdown

                finally:
                    await context.close()
                    await browser.close()

        except PlaywrightTimeout as exc:
            self._logger.error(
                "Scraping timed out | url=%s timeout_ms=%d error=%s",
                url, timeout, str(exc),
            )
            raise RuntimeError(
                f"Timeout after {timeout}ms navigating to '{url}'"
            ) from exc

        except PlaywrightError as exc:
            self._logger.error(
                "Playwright error | url=%s error=%s", url, str(exc)
            )
            raise RuntimeError(
                f"Playwright error while scraping '{url}': {exc}"
            ) from exc

        except Exception as exc:  # noqa: BLE001
            self._logger.exception(
                "Unexpected scraping error | url=%s error=%s", url, str(exc)
            )
            raise RuntimeError(
                f"Unexpected error while scraping '{url}': {exc}"
            ) from exc

    # private helpers

    async def _scroll_to_load_all(
        self,
        page: Page,
        max_scrolls: int = 10,
        scroll_pause_ms: int = 1_500,
    ) -> None:
        """
        Sonsuz scroll (infinite scroll) yÃ¼kleme stratejisi.

        Sayfa yÃ¼ksekliÄŸi (scrollHeight) bÃ¼yÃ¼meye duruncaya kadar
        veya max_scrolls sayÄ±sÄ±na ulaÅŸÄ±nca kadar sayfayÄ± aÅŸaÄŸÄ± kaydÄ±rÄ±r.

        Ã‡alÄ±ÅŸma biÃ§imi:
          1. Mevcut scrollHeight'i al
          2. SayfanÄ±n en altÄ±na kaydÄ±r
          3. Yeni iÃ§erik yÃ¼klenmesini bekle (scroll_pause_ms)
          4. scrollHeight deÄŸiÅŸtiyse devam et, deÄŸiÅŸmediyse dur
        """
        self._logger.debug("Auto-scroll started | max_scrolls=%d", max_scrolls)
        prev_height: int = 0

        for i in range(max_scrolls):
            try:
                current_height: int = await page.evaluate(
                    "document.documentElement.scrollHeight"
                )

                if current_height == prev_height:
                    self._logger.debug(
                        "Auto-scroll stopped: no new content | scroll=%d height=%d",
                        i, current_height,
                    )
                    break

                prev_height = current_height

                await page.evaluate(
                    "window.scrollTo(0, document.documentElement.scrollHeight)"
                )
                await page.wait_for_timeout(scroll_pause_ms)

                self._logger.debug(
                    "Auto-scroll | step=%d/%d height=%d", i + 1, max_scrolls, current_height
                )

            except PlaywrightError as exc:
                # Scroll baÅŸarÄ±sÄ±z olursa devam et iÃ§erik zaten yÃ¼klenmiÅŸtir
                self._logger.debug("Auto-scroll error (ignored) | %s", str(exc))
                break

    async def _extract_markdown(self, page: Page) -> str:
        """
        HTML â†’ BeautifulSoup (temizleme) â†’ Markdown pipeline.

        Her zaman body HTML'ini alÄ±r â€” semantik container aramaz.
        Ã‡Ã¼nkÃ¼ otel siteleri gibi platformlar genellikle custom div yapÄ±larÄ± kullanÄ±r,
        main/content gibi standart container'lar bulunmaz.
        """
        try:
            raw_html = await page.locator("body").first.inner_html(timeout=10_000)
        except PlaywrightError:
            return "(no readable content extracted)"

        self._logger.debug("Raw HTML extracted | chars=%d", len(raw_html))
        return self._html_to_markdown(raw_html)

    @staticmethod
    def _html_to_markdown(html: str) -> str:
        """
        BeautifulSoup ile gÃ¼rÃ¼ltÃ¼ etiketlerini temizle,
        ardÄ±ndan markdownify ile Markdown'a Ã§evir.

        NOT: "BoÅŸ element" temizliÄŸi yapÄ±lmÄ±yor â€” otel kartlarÄ± gibi
        iÃ§ iÃ§e div yapÄ±larÄ±nda parent div'in doÄŸrudan text'i olmayabilir
        ama child elementlerde fiyat/puan verisi vardÄ±r.
        """
        soup = BeautifulSoup(html, "lxml")

        # Sadece gereksiz etiketleri DOM'dan Ã§Ä±kar (script, style, nav, footer vs.)
        for tag in soup.find_all(_NOISE_TAGS):
            tag.decompose()

        clean_html = str(soup)

        # Markdown'a Ã§evir TÃœM etiketler dÃ¶nÃ¼ÅŸtÃ¼rÃ¼lsÃ¼n.
        result = md(
            clean_html,
            heading_style="ATX",
            bullets="-",
            strip=["a", "img"],
        )

        # Ã‡oklu boÅŸluklarÄ± tek boÅŸluÄŸa indir (Token tasarrufu)
        result = re.sub(r"[ \t]+", " ", result)
        # Ã‡oklu boÅŸ satÄ±rlarÄ± tek satÄ±ra indir
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip() or "(no readable content extracted)"
