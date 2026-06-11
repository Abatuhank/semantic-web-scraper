"""
tests/test_smart_trim.py
smart_trim() fonksiyonu testleri.

Test Edilen Dosya: app/services/llm_service.py â†’ smart_trim()
Ne Test Ediliyor:
  1. KÄ±sa iÃ§erik kesilmez (max_chars altÄ±nda = dokunma)
  2. Uzun iÃ§erik max_chars'a kÄ±rpÄ±lÄ±r
  3. Sorguyla alakalÄ± satÄ±rlar Ã¶nceliklendirilir
  4. Para birimi / sayÄ± sinyalleri yÃ¼ksek puanlanÄ±r
  5. Tablo satÄ±rlarÄ± korunur
  6. BaÅŸlÄ±k satÄ±rlarÄ± (#) korunur
  7. BoÅŸ iÃ§erik â†’ boÅŸ dÃ¶ner
"""
import pytest

from app.services.llm_service import smart_trim


class TestSmartTrimBasic:

    def test_short_content_untouched(self):
        """Girdi: 100 karakterlik metin, max_chars=500
        Beklenen: Ä°Ã§erik aynen dÃ¶ner (kÄ±rpma yapÄ±lmaz)"""
        content = "Bu kÄ±sa bir metin. " * 5  # ~100 char
        result = smart_trim(content, query="test", max_chars=500)
        assert result == content

    def test_long_content_trimmed(self):
        """Girdi: 10.000 karakterlik metin, max_chars=500
        Beklenen: SonuÃ§ â‰¤ 500 karakter"""
        content = "Bu bir test satÄ±rÄ±dÄ±r.\n" * 500  # ~11.000 char
        result = smart_trim(content, query="test", max_chars=500)
        assert len(result) <= 500

    def test_empty_content(self):
        """Girdi: BoÅŸ string
        Beklenen: BoÅŸ string dÃ¶ner"""
        result = smart_trim("", query="test", max_chars=500)
        assert result == ""


class TestSmartTrimRelevance:

    def test_keyword_lines_prioritized(self):
        """Girdi: 'fiyat' sorusu, iÃ§erikte sadece 1 satÄ±rda 'fiyat' geÃ§iyor
        Beklenen: O satÄ±r sonuÃ§ta yer alÄ±r"""
        lines = []
        for i in range(100):
            if i == 50:
                lines.append("Bu Ã¼rÃ¼nÃ¼n fiyat bilgisi: 299.90 TL")
            else:
                lines.append(f"AlakasÄ±z dolgu metni satÄ±r {i} burada yer alÄ±yor uzun uzun")
        content = "\n".join(lines)

        result = smart_trim(content, query="fiyat nedir?", max_chars=500)
        assert "fiyat" in result.lower()

    def test_price_signals_boosted(self):
        """Girdi: Para birimi (â‚º) olan satÄ±rlar
        Beklenen: â‚º iÃ§eren satÄ±rlar sonuÃ§ta yer alÄ±r"""
        lines = [
            "Genel bilgi paragrafÄ± " * 10,
            "Laptop A: â‚º15.999",
            "Genel bilgi paragrafÄ± " * 10,
            "Laptop B: â‚º12.499",
            "Genel bilgi paragrafÄ± " * 10,
        ]
        content = "\n".join(lines)

        result = smart_trim(content, query="en ucuz laptop", max_chars=300)
        assert "â‚º" in result

    def test_table_rows_boosted(self):
        """Girdi: Markdown tablo satÄ±rlarÄ± ( | col | col | )
        Beklenen: Tablo satÄ±rlarÄ± sonuÃ§ta yer alÄ±r"""
        lines = [
            "AlakasÄ±z metin " * 20,
            "| Otel | Puan | Fiyat |",
            "| Hotel A | 8.5 | $120 |",
            "| Hotel B | 9.2 | $180 |",
            "AlakasÄ±z metin " * 20,
        ]
        content = "\n".join(lines)

        result = smart_trim(content, query="otel puanlarÄ±", max_chars=400)
        assert "|" in result

    def test_heading_lines_boosted(self):
        """Girdi: Markdown baÅŸlÄ±k satÄ±rlarÄ± (# Heading)
        Beklenen: BaÅŸlÄ±k satÄ±rlarÄ± sonuÃ§ta yer alÄ±r"""
        lines = [
            "Filler text " * 20,
            "# Fiyat Listesi",
            "Laptop: 15999 TL",
            "Filler text " * 20,
        ]
        content = "\n".join(lines)

        result = smart_trim(content, query="fiyat listesi", max_chars=400)
        assert "Fiyat Listesi" in result


class TestSmartTrimEdgeCases:

    def test_turkish_stem_matching(self):
        """Girdi: Query 'laptop', iÃ§erikte 'laptoplarÄ±n'
        Beklenen: KÄ±smi eÅŸleÅŸme ile 'laptoplarÄ±n' satÄ±rÄ± seÃ§ilir"""
        lines = [
            "Genel dolgu metni " * 15,
            "En Ã§ok satan laptoplarÄ±n fiyatlarÄ± burada listelenmiÅŸtir.",
            "Genel dolgu metni " * 15,
        ]
        content = "\n".join(lines)

        result = smart_trim(content, query="laptop fiyatlarÄ±", max_chars=300)
        assert "laptop" in result.lower()

    def test_stopwords_ignored_in_scoring(self):
        """Girdi: Query 'bana en ucuz Ã¼rÃ¼nÃ¼ gÃ¶ster' (Ã§oÄŸu stopword)
        Beklenen: Sadece 'ucuz' ve 'Ã¼rÃ¼n' anahtar kelime olarak kullanÄ±lÄ±r"""
        lines = [
            "Dolgu metni " * 20,
            "Bu Ã¼rÃ¼n Ã§ok ucuz: 29.90 TL",
            "Dolgu metni " * 20,
            "Bana bir bardak su ver",  # 'bana' ve 'ver' stopword â€” puan dÃ¼ÅŸÃ¼k
        ]
        content = "\n".join(lines)

        result = smart_trim(content, query="bana en ucuz Ã¼rÃ¼nÃ¼ gÃ¶ster", max_chars=300)
        assert "ucuz" in result.lower() or "29.90" in result

    def test_no_matching_lines_returns_first_chars(self):
        """Girdi: HiÃ§bir satÄ±r sorguyla eÅŸleÅŸmiyor
        Beklenen: Ä°Ã§eriÄŸin ilk max_chars karakteri dÃ¶ner"""
        content = "AAAA\n" * 200  # HiÃ§bir anahtar kelime yok
        result = smart_trim(content, query="xyznonexistent", max_chars=100)
        assert len(result) <= 100
        assert result  # BoÅŸ olmamalÄ±
