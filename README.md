#  Semantic Web Scraper

Yapay zeka (LLM) destekli, asenkron ve semantik web kazıma (web scraping) sistemi. Geleneksel XPath veya CSS seçici bağımlılıklarını ortadan kaldırarak, web sayfalarından doğal dil sorgularıyla yapılandırılmış veri çıkarılmasını sağlar.

---

##  Sistem Mimarisi

Proje, yüksek yük altında çalışabilecek asenkron ve mikro-servis mimarisine sahiptir:

```
[İstemci / Arayüz] ──(HTTP)──► FastAPI API Sunucusu ──(Celery .delay())──► Redis (Mesaj Kuyruğu)
                                    │                                           │
                           GET /status/{job_id}                                 ▼
                                    │                                   Celery Worker (İşçi)
                                    └◄─────────── AsyncResult ─────────── (Playwright + Gemini API)
```

### Temel Bileşenler:
- **FastAPI:** Hızlı, tip güvenli REST API katmanı.
- **Celery & Redis:** Uzun süren kazıma ve LLM analiz işlerini asenkron yöneten görev kuyruğu.
- **Playwright (Chromium):** Dinamik (JavaScript render gerektiren) web sayfalarını başsız (headless) tarayıcıda yükleyen kazıyıcı motoru.
- **Google Gemini API (2.5 Flash):** Sayfadaki ham veriyi yorumlayan ve kullanıcının sorusuna göre anlamlı veri çıkaran yapay zeka beyni.

---

##  Kurulum ve Çalıştırma

Proje, Docker ve Docker Compose kullanılarak tek bir komutla kolayca ayağa kaldırılabilir.

### 1. Gereksinimler
- Bilgisayarınızda **Docker** ve **Docker Compose** kurulu olmalıdır.
- Bir **Google Gemini API Key** (ücretsiz alabilirsiniz).

### 2. Yapılandırma (`.env` Dosyası)
Proje kök dizininde `.env.example` adında bir örnek dosya bulunmaktadır. Bu dosyayı kopyalayarak `.env` adında yeni bir dosya oluşturun:

```bash
cp .env.example .env
```

`.env` dosyasını açıp aşağıdaki ayarı kendi API anahtarınızla güncelleyin:
```env
OPENAI_API_KEY="AIzaSyYourGeminiApiKeyHere"
LLM_PROVIDER="gemini"
LLM_MODEL="gemini-2.5-flash"
```

### 3. Backend'i Docker Üzerinde Çalıştırma
Tüm arka plan servislerini (FastAPI, Redis, Celery Worker) başlatmak için kök dizinde şu komutu çalıştırın:

```bash
docker-compose up --build -d
```

Servisler başladıktan sonra API'nin durumunu kontrol etmek için tarayıcınızdan şu adrese gidebilirsiniz:
- **FastAPI Dokümantasyonu (Swagger UI):** http://localhost:8000/docs
- **Sağlık Kontrolü:** http://localhost:8000/health

### 4. Frontend'i (Arayüzü) Çalıştırma
Arayüzü başlatmak için `frontend` dizinine geçin ve bağımlılıkları yükleyip projeyi çalıştırın:

```bash
cd frontend
npm install
npm run dev
```

Ardından tarayıcınızdan http://localhost:3000 adresine giderek sistemi görsel olarak kullanabilirsiniz.

---

##  Testlerin Çalıştırılması

Projede 90'dan fazla birim (unit) testi ve gerçek web sitelerine karşı yazılmış entegrasyon testleri bulunur.

### Birim Testleri (Pytest)
Docker konteynerleri ayaktayken birim testlerini çalıştırmak için:

```bash
docker-compose exec api pytest
```

### Canlı Web Sitesi Entegrasyon Testleri
Gerçek sitelerden (Wikipedia, HackerNews vb.) canlı veri çekerek sistemi test etmek için yerel makinenizde şu komutu çalıştırabilirsiniz:

```bash
python test_live_sites.py
```

---

##  API Endpoint'leri ve Kullanım Örnekleri

### 1. Tek Sayfa Scrape + LLM Analiz (`POST /api/scrape/analyze`)
Tek bir web sayfasını kazır, içeriği temizler ve LLM'e göndererek sorunuza yanıt arar.

**Örnek İstek (cURL):**
```bash
curl -X POST "http://localhost:8000/api/scrape/analyze" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://news.ycombinator.com/",
       "query": "İlk 5 haberin başlığını ve puanını listele.",
       "timeout_ms": 30000
     }'
```

**Yanıt:**
```json
{
  "job_id": "8ac107c1-a9bd-4b39-8ac7-016665c8d834"
}
```

### 2. Durum Sorgulama (`GET /api/scrape/status/{job_id}`)
Gönderdiğiniz işin durumunu ve varsa sonucunu çekmenizi sağlar.

**Örnek İstek:**
```bash
curl -X GET "http://localhost:8000/api/scrape/status/8ac107c1-a9bd-4b39-8ac7-016665c8d834"
```

**Yanıt:**
```json
{
  "job_id": "8ac107c1-a9bd-4b39-8ac7-016665c8d834",
  "status": "done",
  "result": {
    "llm_answer": "1. πFS (210 puan)\n2. Curiosity Rover (114 puan)...",
    "raw_text_length": 4547
  },
  "error": null
}
```

### 3. Çoklu Sayfa / Derin Kazıma (`POST /api/scrape/deep`)
Bir listeleme sayfasındaki linkleri otonom olarak analiz eder, içlerinden sorunuza en uygun olan alt sayfa linklerini (LLM rehberliğinde) seçer ve onları da kazıyarak birleştirilmiş bir analiz sunar.

**Örnek İstek:**
```bash
curl -X POST "http://localhost:8000/api/scrape/deep" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://news.ycombinator.com/",
       "query": "Haberlerin detay sayfalarına gidip yorumlardaki tartışmayı özetle.",
       "max_pages": 3,
       "timeout_ms": 60000
     }'
```

---

##  Akıllı Maliyet & Token Yönetimi (Smart Trim)
Sistemimiz, LLM girdi limitlerini aşmamak ve token maliyetlerini düşürmek için **Smart Trim** algoritmasına sahiptir. Wikipedia veya haber portalları gibi devasa sayfalar (100K+ karakter) kazındığında, algoritma metni analiz eder; kullanıcının sorusuyla en alakalı kısımları, sayısal değerleri ve tablo satırlarını önceliklendirerek sadece ilgili bölümleri LLM'e gönderir. Bu sayede API maliyetleri **%90'a varan oranda optimize edilir**.
