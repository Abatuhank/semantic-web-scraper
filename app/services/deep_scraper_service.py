"""
app/services/deep_scraper_service.py
Single Responsibility: Ã‡oklu sayfa tarama.

1. BaÅŸlangÄ±Ã§ URL'sine git â†’ scroll yap â†’ linkleri topla
2. Her linke git â†’ scroll yap â†’ HTML al â†’ BeautifulSoup temizle â†’ Markdown'a Ã§evir
3. TÃ¼m sayfalarÄ±n Markdown iÃ§eriklerini birleÅŸtirip dÃ¶ndÃ¼r

Token bÃ¼tÃ§esi: smart_trim (llm_service.py) bu katmanda yapÄ±lÄ±r,
burada sadece ham iÃ§erik birleÅŸtirilir.
"""
import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from app.core.config import Settings
from app.services.llm_service import LLMService, smart_trim

# LLM iÃ§in anlamsÄ±z, sadece token tÃ¼keten etiketler.
# header kasÄ±tlÄ± olarak Ã§Ä±karÄ±lmadÄ± bazÄ± siteler iÃ§eriÄŸi header'da tutuyor.
_NOISE_TAGS = [
    "script", "style", "noscript", "iframe",
    "nav", "footer", "aside",
    "form", "button", "svg", "img",
    "meta", "link", "head",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class DeepScraperService:
    """
    Ã–nce liste sayfasÄ±ndaki linkleri toplar, sonra her linki ziyaret
    ederek iÃ§erikleri Markdown formatÄ±nda birleÅŸtirir.

    Pipeline: Playwright HTML â†’ BeautifulSoup temizleme â†’ Markdownify
    Bu sayede tablolar (| Otel | Puan |) yapÄ±sÄ±nÄ± korur.
    """

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger

    async def deep_scrape(
        self,
        url: str,
        query: str,
        link_pattern: Optional[str] = None,
        max_pages: int = 30,
        timeout_ms: Optional[int] = None,
    ) -> dict:
        """
        Args:
            url:          BaÅŸlangÄ±Ã§ (liste) sayfasÄ±nÄ±n URL'si.
            link_pattern: Sadece bu string'i iÃ§eren href'leri takip et.
                          None veya boÅŸ string = tÃ¼m internal linkler.
            max_pages:    En fazla kaÃ§ alt sayfa ziyaret edilsin.
            timeout_ms:   Sayfa yÃ¼kleme timeout'u (ms).

        Returns:
            {
              "index_url": str,
              "index_text": str,
              "pages": [{"url": str, "text": str}, ...],
              "combined_text": str,   â† LLM'e gidecek olan Markdown
              "total_pages": int,
            }
        """
        timeout = timeout_ms or self._settings.scraper_default_timeout_ms
        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        self._logger.info(
            "DeepScrape started | url=%s pattern=%s max_pages=%d",
            url, link_pattern, max_pages,
        )

        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(
                headless=self._settings.scraper_headless,
            )
            context: BrowserContext = await browser.new_context(
                user_agent=_USER_AGENT,
                java_script_enabled=True,
                viewport={"width": 1920, "height": 1080},
            )

            try:
                # AdÄ±m 1: Ana liste sayfasÄ±nÄ± yÃ¼kle + scroll + linkleri topla
                index_page: Page = await context.new_page()
                index_text, links = await self._load_and_extract_links(
                    index_page, url, base, link_pattern, timeout
                )
                await index_page.close()

                self._logger.info(
                    "Index page scraped | chars=%d links_found=%d",
                    len(index_text), len(links),
                )

                # AdÄ±m 2: AkÄ±llÄ± Link SeÃ§imi (Smart Routing)
                llm = LLMService(settings=self._settings, logger=self._logger)
                
                self._logger.info("Calling LLM to select best links among %d candidates...", len(links))
                selected_urls = await llm.select_best_links(query, links, max_pages)
                
                if not selected_urls:
                    self._logger.warning("No suitable links found by LLM. Falling back to default.")
                    selected_urls = [link['url'] for link in links[:max_pages]]

                pages_data = []
                links_to_visit = selected_urls

                for i, link_url in enumerate(links_to_visit, 1):
                    self._logger.info(
                        "Visiting sub-page %d/%d | url=%s",
                        i, len(links_to_visit), link_url,
                    )
                    sub_page: Page = await context.new_page()
                    try:
                        sub_text = await self._load_page_markdown(
                            sub_page, link_url, timeout
                        )
                        if sub_text:
                            pages_data.append({"url": link_url, "text": sub_text})
                    except Exception as exc:  # noqa: BLE001
                        self._logger.warning(
                            "Sub-page failed | url=%s error=%s", link_url, str(exc)
                        )
                    finally:
                        await sub_page.close()

                    # Rate-limit: sayfalar arasÄ± 500ms bekle
                    await asyncio.sleep(0.5)

                # AdÄ±m 3: BirleÅŸtir ve Her SayfayÄ± AyrÄ± AyrÄ± KÄ±rp
                target_chars = getattr(self._settings, "llm_target_content_chars", 15_000)
                # Alt sayfa sayÄ±sÄ±na gÃ¶re sayfa baÅŸÄ± karakter hedefini belirle (min 2000)
                per_page_target = max(2000, target_chars // max(1, len(pages_data) + 1))

                combined_parts = []
                if index_text:
                    trimmed_index = smart_trim(index_text, query, per_page_target)
                    combined_parts.append(
                        f"## ANA SAYFA\nURL: {url}\n\n{trimmed_index}"
                    )
                for pd in pages_data:
                    trimmed_sub = smart_trim(pd['text'], query, per_page_target)
                    combined_parts.append(
                        f"## ALT SAYFA\nURL: {pd['url']}\n\n{trimmed_sub}"
                    )

                combined_text = "\n\n---\n\n".join(combined_parts)

                self._logger.info(
                    "DeepScrape complete | sub_pages=%d total_chars=%d",
                    len(pages_data), len(combined_text),
                )

                return {
                    "index_url": url,
                    "index_text": index_text,
                    "pages": pages_data,
                    "combined_text": combined_text,
                    "total_pages": len(pages_data) + 1,
                }

            finally:
                await context.close()
                await browser.close()

    # Private helpers

    async def _load_and_extract_links(
        self,
        page: Page,
        url: str,
        base: str,
        link_pattern: Optional[str],
        timeout: int,
    ) -> tuple[str, list[dict]]:
        """SayfayÄ± yÃ¼kle, scroll yap, Markdown metnini al ve geÃ§erli linkleri Ã§Ä±kar."""
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await self._wait_for_content(page)
        # Ana liste sayfasÄ±nda da scroll yap lazy-load linkleri gÃ¶rÃ¼nÃ¼r olsun
        await self._scroll_to_load_all(page)
        text = await self._extract_page_markdown(page)

        anchors = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => ({href: a.getAttribute('href'), text: a.innerText.trim()}))
                       .filter(a => a.href && !a.href.startsWith('#') && !a.href.startsWith('javascript') && a.text.length > 0)
        """)

        links = []
        seen = set()
        for a in anchors:
            href = a['href']
            text = a['text']
            full_url = href if href.startswith("http") else urljoin(base, href)
            if urlparse(full_url).netloc != urlparse(base).netloc:
                continue
            if link_pattern and link_pattern not in full_url:
                continue
            if full_url not in seen and full_url != url:
                seen.add(full_url)
                links.append({"url": full_url, "text": text})

        return text, links

    async def _load_page_markdown(self, page: Page, url: str, timeout: int) -> str:
        """Tek bir alt sayfayÄ± yÃ¼kle, scroll yap ve Markdown iÃ§eriÄŸini dÃ¶ndÃ¼r."""
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await self._wait_for_content(page)
        await self._scroll_to_load_all(page)
        return await self._extract_page_markdown(page)

    async def _wait_for_content(self, page: Page) -> None:
        """JS/AJAX iÃ§eriÄŸinin yÃ¼klenmesi iÃ§in bekle."""
        for sel in [
            "table", "tbody tr",
            "[class*='hotel']", "[class*='otel']",
            "[class*='card']", "[class*='listing']",
            "[class*='property']", "[class*='result']",
            "[class*='price']", "[class*='fiyat']",
            "[class*='rating']", "[class*='puan']",
            "main", "article", "[class*='content']",
            "[class*='grid']", "[class*='list']",
        ]:
            try:
                await page.wait_for_selector(sel, state="visible", timeout=4_000)
                break
            except PlaywrightTimeout:
                continue
        await page.wait_for_timeout(2_000)

    async def _scroll_to_load_all(
        self,
        page: Page,
        max_scrolls: int = 8,
        scroll_pause_ms: int = 1_500,
    ) -> None:
        """
        Sonsuz scroll (infinite scroll) yÃ¼kleme stratejisi.
        scrollHeight duruncaya kadar veya max_scrolls'a ulaÅŸÄ±nca kadar scroll yapar.
        Deep scrape iÃ§in max_scrolls daha dÃ¼ÅŸÃ¼k (8) tutuldu â€” Ã§ok sayfa ziyaret ediliyor.
        """
        prev_height: int = 0
        for i in range(max_scrolls):
            try:
                current_height: int = await page.evaluate(
                    "document.documentElement.scrollHeight"
                )
                if current_height == prev_height:
                    break
                prev_height = current_height
                await page.evaluate(
                    "window.scrollTo(0, document.documentElement.scrollHeight)"
                )
                await page.wait_for_timeout(scroll_pause_ms)
            except PlaywrightError as exc:
                self._logger.debug("Scroll error (ignored) | %s", str(exc))
                break

    async def _extract_page_markdown(self, page: Page) -> str:
        """SayfanÄ±n HTML'ini Markdown'a Ã§evir (tablo yapÄ±sÄ±nÄ± koruyarak)."""
        try:
            raw_html = await page.locator("body").first.inner_html(timeout=8_000)
            return self._html_to_markdown(raw_html)
        except PlaywrightError:
            return ""

    @staticmethod
    def _html_to_markdown(html: str) -> str:
        """
        BeautifulSoup ile gÃ¼rÃ¼ltÃ¼ etiketlerini temizle,
        ardÄ±ndan markdownify ile Markdown'a Ã§evir.
        """
        soup = BeautifulSoup(html, "lxml")

        for tag in soup.find_all(_NOISE_TAGS):
            tag.decompose()

        clean_html = str(soup)

        result = md(
            clean_html,
            heading_style="ATX",
            bullets="-",
            strip=["a", "img"],
        )

        # Ã‡oklu boÅŸluklarÄ± tek boÅŸluÄŸa indir (Token tasarrufu)
        result = re.sub(r"[ \t]+", " ", result)
        # Ã‡oklu satÄ±rlarÄ± Ã§ift satÄ±ra indir
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()
