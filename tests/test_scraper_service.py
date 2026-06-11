"""
tests/test_scraper_service.py
ScraperService testleri.

Test Edilen Dosya: app/services/scraper_service.py
Ne Test Ediliyor:
  1. _html_to_markdown() â€” HTML â†’ Markdown dÃ¶nÃ¼ÅŸÃ¼mÃ¼
  2. GÃ¼rÃ¼ltÃ¼ etiketlerinin (script, nav, footer) temizlenmesi
  3. Tablo yapÄ±sÄ±nÄ±n korunmasÄ±
  4. BoÅŸ HTML edge case
  5. Ã‡oklu boÅŸluklarÄ±n indirgenmesi
"""
import pytest

from app.services.scraper_service import ScraperService


class TestHtmlToMarkdown:
    """ScraperService._html_to_markdown() statik metodu testleri."""

    def test_basic_html_conversion(self):
        """Girdi: <h1>BaÅŸlÄ±k</h1><p>Paragraf</p>
        Beklenen: Markdown formatÄ±nda baÅŸlÄ±k ve paragraf"""
        html = "<h1>BaÅŸlÄ±k</h1><p>Bu bir paragraftÄ±r.</p>"
        result = ScraperService._html_to_markdown(html)
        assert "BaÅŸlÄ±k" in result
        assert "Bu bir paragraftÄ±r." in result

    def test_script_tags_removed(self):
        """Girdi: HTML iÃ§inde <script> tag'Ä±
        Beklenen: Script iÃ§eriÄŸi tamamen kaldÄ±rÄ±lÄ±r"""
        html = """
        <div>
            <p>GerÃ§ek iÃ§erik</p>
            <script>var x = 'gizli kod'; alert(x);</script>
        </div>
        """
        result = ScraperService._html_to_markdown(html)
        assert "GerÃ§ek iÃ§erik" in result
        assert "gizli kod" not in result
        assert "alert" not in result

    def test_nav_footer_removed(self):
        """Girdi: <nav> ve <footer> iÃ§eren HTML
        Beklenen: Nav ve footer iÃ§eriÄŸi kaldÄ±rÄ±lÄ±r"""
        html = """
        <nav><ul><li>Ana Sayfa</li><li>Ä°letiÅŸim</li></ul></nav>
        <main><p>Ana iÃ§erik burada.</p></main>
        <footer><p>Â© 2026 Åirket</p></footer>
        """
        result = ScraperService._html_to_markdown(html)
        assert "Ana iÃ§erik burada." in result
        assert "Ana Sayfa" not in result
        assert "Â© 2026" not in result

    def test_style_tags_removed(self):
        """Girdi: <style> tag'Ä±
        Beklenen: CSS iÃ§eriÄŸi kaldÄ±rÄ±lÄ±r"""
        html = """
        <style>.red { color: red; }</style>
        <p>GÃ¶rÃ¼nen metin</p>
        """
        result = ScraperService._html_to_markdown(html)
        assert "GÃ¶rÃ¼nen metin" in result
        assert "color: red" not in result

    def test_table_structure_preserved(self):
        """Girdi: HTML tablosu
        Beklenen: Markdown tablo formatÄ± korunur ( | col | col | )"""
        html = """
        <table>
            <thead><tr><th>ÃœrÃ¼n</th><th>Fiyat</th></tr></thead>
            <tbody>
                <tr><td>Laptop</td><td>15999 TL</td></tr>
                <tr><td>Telefon</td><td>8999 TL</td></tr>
            </tbody>
        </table>
        """
        result = ScraperService._html_to_markdown(html)
        assert "|" in result
        assert "Laptop" in result
        assert "15999" in result

    def test_multiple_spaces_collapsed(self):
        """Girdi: Ã‡ok fazla boÅŸluk iÃ§eren HTML
        Beklenen: BoÅŸluklar tek boÅŸluÄŸa indirgenir"""
        html = "<p>Bu     bir      test      cÃ¼mlesidir.</p>"
        result = ScraperService._html_to_markdown(html)
        assert "  " not in result  # Ã‡ift boÅŸluk olmamalÄ±

    def test_multiple_newlines_collapsed(self):
        """Girdi: Ã‡ok fazla boÅŸ satÄ±r iÃ§eren HTML
        Beklenen: ÃœÃ§+ boÅŸ satÄ±r iki satÄ±ra indirgenir"""
        html = "<p>SatÄ±r 1</p>\n\n\n\n\n<p>SatÄ±r 2</p>"
        result = ScraperService._html_to_markdown(html)
        assert "\n\n\n" not in result

    def test_empty_html_returns_fallback(self):
        """Girdi: BoÅŸ HTML (<body></body> gibi)
        Beklenen: Fallback mesajÄ± veya boÅŸ string"""
        result = ScraperService._html_to_markdown("")
        # BoÅŸ veya fallback mesajÄ± olmalÄ±
        assert isinstance(result, str)

    def test_links_stripped(self):
        """Girdi: <a href='...'>Link</a>
        Beklenen: Link etiketi kaldÄ±rÄ±lÄ±r, metin kalÄ±r"""
        html = '<p>Detaylar iÃ§in <a href="https://example.com">buraya tÄ±klayÄ±n</a>.</p>'
        result = ScraperService._html_to_markdown(html)
        assert "buraya tÄ±klayÄ±n" in result
        assert "href" not in result

    def test_image_tags_stripped(self):
        """Girdi: <img src='...' alt='foto'>
        Beklenen: img tag'Ä± kaldÄ±rÄ±lÄ±r"""
        html = '<div><img src="photo.jpg" alt="foto"/><p>AÃ§Ä±klama</p></div>'
        result = ScraperService._html_to_markdown(html)
        assert "AÃ§Ä±klama" in result
        assert "photo.jpg" not in result


class TestHtmlToMarkdownRealWorld:
    """GerÃ§ekÃ§i HTML Ã¶rnekleriyle dÃ¶nÃ¼ÅŸÃ¼m testleri."""

    def test_ecommerce_product_card(self):
        """Girdi: E-ticaret Ã¼rÃ¼n kartÄ± HTML'i
        Beklenen: ÃœrÃ¼n adÄ± ve fiyat bilgisi korunur"""
        html = """
        <div class="product-card">
            <h3>Samsung Galaxy S24 Ultra</h3>
            <span class="price">â‚º64.999</span>
            <span class="rating">4.8/5</span>
            <p class="desc">256GB, Titanium Black</p>
            <button>Sepete Ekle</button>
        </div>
        """
        result = ScraperService._html_to_markdown(html)
        assert "Samsung Galaxy S24 Ultra" in result
        assert "64.999" in result
        assert "4.8" in result
        # button temizlenmeli
        assert "Sepete Ekle" not in result

    def test_hotel_listing(self):
        """Girdi: Otel listeleme HTML'i
        Beklenen: Otel adÄ±, puan ve fiyat bilgisi korunur"""
        html = """
        <div class="hotel-card">
            <h2>Grand Hyatt Istanbul</h2>
            <div class="hotel-rating">9.2/10</div>
            <div class="hotel-price">$250/gece</div>
        </div>
        <nav><a href="/home">Ana Sayfa</a></nav>
        """
        result = ScraperService._html_to_markdown(html)
        assert "Grand Hyatt Istanbul" in result
        assert "9.2" in result
        assert "$250" in result
        assert "Ana Sayfa" not in result
