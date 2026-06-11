"""
tests/test_deep_scraper_service.py
DeepScraperService testleri.

Test Edilen Dosya: app/services/deep_scraper_service.py
Ne Test Ediliyor:
  1. _html_to_markdown() â€” HTML â†’ Markdown dÃ¶nÃ¼ÅŸÃ¼mÃ¼ (deep scraper versiyonu)
  2. GÃ¼rÃ¼ltÃ¼ etiketlerinin temizlenmesi
  3. Tablo yapÄ±sÄ±nÄ±n korunmasÄ±
  4. Markdown formatÄ±nÄ±n doÄŸruluÄŸu
"""
import pytest

from app.services.deep_scraper_service import DeepScraperService


class TestDeepScraperHtmlToMarkdown:
    """DeepScraperService._html_to_markdown() statik metodu testleri."""

    def test_basic_conversion(self):
        """Girdi: Basit HTML
        Beklenen: Markdown metni"""
        html = "<h1>BaÅŸlÄ±k</h1><p>Ä°Ã§erik burada.</p>"
        result = DeepScraperService._html_to_markdown(html)
        assert "BaÅŸlÄ±k" in result
        assert "Ä°Ã§erik burada." in result

    def test_noise_tags_removed(self):
        """Girdi: script, nav, footer iÃ§eren HTML
        Beklenen: Bu etiketler temizlenir"""
        html = """
        <script>alert('hack');</script>
        <nav>Menu</nav>
        <div><p>AsÄ±l iÃ§erik</p></div>
        <footer>Footer bilgisi</footer>
        """
        result = DeepScraperService._html_to_markdown(html)
        assert "AsÄ±l iÃ§erik" in result
        assert "alert" not in result
        assert "Menu" not in result
        assert "Footer bilgisi" not in result

    def test_table_preserved(self):
        """Girdi: HTML tablosu
        Beklenen: Markdown tablo formatÄ± ( | ) korunur"""
        html = """
        <table>
            <tr><th>Ãœniversite</th><th>Puan</th></tr>
            <tr><td>ODTÃœ</td><td>485</td></tr>
            <tr><td>BoÄŸaziÃ§i</td><td>478</td></tr>
        </table>
        """
        result = DeepScraperService._html_to_markdown(html)
        assert "|" in result
        assert "ODTÃœ" in result
        assert "485" in result

    def test_multiple_whitespace_collapsed(self):
        """Girdi: Fazla boÅŸluklu HTML
        Beklenen: Tek boÅŸluÄŸa indirgenir"""
        html = "<p>Ã‡ok       fazla    boÅŸluk      var</p>"
        result = DeepScraperService._html_to_markdown(html)
        assert "  " not in result

    def test_form_and_button_removed(self):
        """Girdi: form ve button etiketleri
        Beklenen: Bunlar temizlenir"""
        html = """
        <div>
            <p>ÃœrÃ¼n bilgisi: 299 TL</p>
            <form action="/buy"><button>SatÄ±n Al</button></form>
        </div>
        """
        result = DeepScraperService._html_to_markdown(html)
        assert "299 TL" in result
        assert "SatÄ±n Al" not in result

    def test_svg_removed(self):
        """Girdi: SVG etiketi
        Beklenen: SVG tamamen temizlenir"""
        html = """
        <div>
            <svg xmlns="http://www.w3.org/2000/svg"><circle r="50"/></svg>
            <p>Metin devam ediyor</p>
        </div>
        """
        result = DeepScraperService._html_to_markdown(html)
        assert "Metin devam ediyor" in result
        assert "circle" not in result

    def test_real_world_university_page(self):
        """Girdi: Ãœniversite bilgi sayfasÄ± HTML'i
        Beklenen: FakÃ¼lte adÄ±, kontenjan, puan gibi veriler korunur"""
        html = """
        <div class="program-info">
            <h2>Bilgisayar MÃ¼hendisliÄŸi</h2>
            <table>
                <tr><th>Kontenjan</th><td>80</td></tr>
                <tr><th>Taban PuanÄ±</th><td>478.234</td></tr>
                <tr><th>BaÅŸarÄ± SÄ±rasÄ±</th><td>12.450</td></tr>
            </table>
        </div>
        <nav><a href="/">Anasayfa</a></nav>
        <footer><p>YÃ–K Atlas Â© 2026</p></footer>
        """
        result = DeepScraperService._html_to_markdown(html)
        assert "Bilgisayar MÃ¼hendisliÄŸi" in result
        assert "478.234" in result
        assert "12.450" in result
        assert "Anasayfa" not in result
        assert "YÃ–K Atlas" not in result
