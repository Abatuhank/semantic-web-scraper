"""
Canli Site Entegrasyon Testleri
================================
Gercek web sitelerinde scraping + LLM analiz testleri.

Gereksinimler:
  - Docker servisleri calisiyor olmali (docker-compose up)
  - .env dosyasinda gecerli bir API key olmali

Kullanim:
  py -3 test_live_sites.py
"""
import time
import json
import sys
import httpx

BASE_URL = "http://localhost:8000/api/scrape"
POLL_INTERVAL = 3
MAX_WAIT = 180


def send_job(endpoint, payload):
    url = f"{BASE_URL}/{endpoint}"
    print(f"  POST {url}")
    print(f"  Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    resp = httpx.post(url, json=payload, timeout=15.0)
    if resp.status_code != 202:
        print(f"  [HATA] Beklenmeyen durum kodu: {resp.status_code}")
        print(f"  {resp.text}")
        return None

    data = resp.json()
    job_id = data.get("job_id")
    print(f"  [OK] Job olusturuldu: {job_id}")
    return job_id


def poll_result(job_id):
    status_url = f"{BASE_URL}/status/{job_id}"
    start = time.time()

    while True:
        elapsed = time.time() - start
        if elapsed > MAX_WAIT:
            print(f"  [TIMEOUT] {MAX_WAIT}s icinde tamamlanamadi!")
            return None

        try:
            resp = httpx.get(status_url, timeout=10.0)
            data = resp.json()
            status = data.get("status")
            print(f"  [{int(elapsed):>3}s] Durum: {status}")

            if status == "done":
                return data.get("result")
            elif status == "failed":
                print(f"  [HATA] {data.get('error')}")
                return None

        except Exception as e:
            print(f"  [UYARI] Polling hatasi: {e}")

        time.sleep(POLL_INTERVAL)


def run_test(test_name, endpoint, payload):
    print(f"\n{'='*80}")
    print(f"TEST: {test_name}")
    print(f"{'='*80}")

    job_id = send_job(endpoint, payload)
    if not job_id:
        print("  [BASARISIZ] Job gonderilemedi.\n")
        return False

    print(f"\n  Sonuc bekleniyor (maks {MAX_WAIT}s)...")
    result = poll_result(job_id)

    if result is None:
        print("  [BASARISIZ] Sonuc alinamadi.\n")
        return False

    print(f"\n  " + "-"*60)
    print(f"  LLM YANITI:")
    print(f"  " + "-"*60)

    llm_answer = result.get("llm_answer", "(bos)")
    # Unicode karakterleri guvenli yazdir
    for line in llm_answer.split("\n"):
        try:
            print(f"    {line}")
        except UnicodeEncodeError:
            print(f"    {line.encode('ascii', 'replace').decode('ascii')}")

    raw_len = result.get("raw_text_length", "?")
    print(f"\n  Ham metin uzunlugu: {raw_len} karakter")

    if "total_pages" in result:
        print(f"  Toplam taranan sayfa: {result['total_pages']}")

    print(f"  [BASARILI] Test tamamlandi.\n")
    return True


def main():
    print("=" * 80)
    print("  CANLI SITE ENTEGRASYON TESTLERI")
    print("  Tarih:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    try:
        health = httpx.get("http://localhost:8000/health", timeout=5.0)
        print(f"\n  API Durumu: {health.json()}")
    except Exception as e:
        print(f"\n  [HATA] API'ye baglanilamiyor: {e}")
        print("  Docker servisleri calisiyor mu? (docker-compose up)")
        sys.exit(1)

    tests = [
        # TEST 1: Booking.com - Antalya Otelleri (Tek Sayfa)
        {
            "name": "Booking.com - Antalya Otelleri (Tek Sayfa Analiz)",
            "endpoint": "analyze",
            "payload": {
                "url": "https://www.booking.com/searchresults.tr.html?ss=Antalya&checkin=2026-07-01&checkout=2026-07-05&group_adults=2",
                "query": "Antalya'daki ilk 5 otelin adlarini, puanlarini ve gecelik fiyatlarini listele.",
                "timeout_ms": 60000,
            },
        },

        # TEST 2: Hacker News - Guncel Haberler (Tek Sayfa)
        {
            "name": "Hacker News - Guncel Haberler (Tek Sayfa)",
            "endpoint": "analyze",
            "payload": {
                "url": "https://news.ycombinator.com/",
                "query": "Ilk 5 haberin basliklarini, puanlarini ve yorum sayilarini listele.",
                "timeout_ms": 30000,
            },
        },

        # TEST 3: Wikipedia - Antalya Sayfasi (Tek Sayfa)
        {
            "name": "Wikipedia - Antalya Bilgileri (Tek Sayfa)",
            "endpoint": "analyze",
            "payload": {
                "url": "https://tr.wikipedia.org/wiki/Antalya",
                "query": "Antalya'nin nufusu, yuzolcumu ve hangi bolgede oldugu bilgisini ver.",
                "timeout_ms": 30000,
            },
        },

        # TEST 4: Books to Scrape - Fiyat Karsilastirma (Tek Sayfa)
        {
            "name": "Books to Scrape - En Pahali Kitap (Tek Sayfa)",
            "endpoint": "analyze",
            "payload": {
                "url": "https://books.toscrape.com/",
                "query": "Sayfadaki en pahali kitap hangisi? Adini ve fiyatini belirt.",
                "timeout_ms": 30000,
            },
        },

        # TEST 5: Hacker News - Derin Arama (Multi-Page)
        {
            "name": "Hacker News - Derin Arama (Multi-Page, 3 sayfa)",
            "endpoint": "deep",
            "payload": {
                "url": "https://news.ycombinator.com/",
                "query": "En cok yorum alan haberlerin basliklarini ve yorum sayilarini listele.",
                "max_pages": 3,
                "timeout_ms": 60000,
            },
        },

        # TEST 6: Quotes to Scrape - Alintilar (Tek Sayfa)
        {
            "name": "Quotes to Scrape - Unlu Sozler (Tek Sayfa)",
            "endpoint": "analyze",
            "payload": {
                "url": "https://quotes.toscrape.com/",
                "query": "Sayfadaki tum alintilari, yazarlarini ve etiketlerini listele.",
                "timeout_ms": 30000,
            },
        },
    ]

    passed = 0
    failed = 0

    for t in tests:
        success = run_test(t["name"], t["endpoint"], t["payload"])
        if success:
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 80)
    print(f"  SONUC: {passed} basarili / {failed} basarisiz (Toplam: {passed + failed})")
    print("=" * 80)


if __name__ == "__main__":
    main()
