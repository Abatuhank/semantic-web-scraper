# 🧠 Semantic Web Scraper — Teknik Rehber

> Senior → Junior anlatımı. Mantık + Kod + Neden öyle yapıldı.

---

## 📁 Proje Yapısı

```
scraperbuild/
├── app/
│   ├── main.py                  # FastAPI uygulaması burada başlar
│   ├── core/
│   │   ├── config.py            # Tüm ayarlar buradan okunur
│   │   └── logging.py           # Logger fabrikası
│   ├── models/
│   │   └── schemas.py           # API'nin veri sözleşmesi (Pydantic)
│   ├── services/
│   │   ├── scraper_service.py   # Playwright ile sayfa çeken servis
│   │   └── llm_service.py       # LLM'e soran servis
│   ├── workers/
│   │   ├── celery_app.py        # Celery konfigürasyonu
│   │   └── tasks.py             # Arka planda çalışan iş
│   └── api/
│       └── routes/
│           └── scrape.py        # HTTP endpoint'leri
├── requirements.txt
├── .env / .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## 1️⃣ `app/core/config.py` — Ayarlar Merkezi

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "semantic-scraper"
    
    # Redis bağlantı adresi
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"
    
    # LLM ayarları
    openai_api_key: str = "sk-placeholder"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = ""        # Groq için: https://api.groq.com/openai/v1
    llm_provider: str = "openai"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.2
    
    # Playwright ayarları
    scraper_default_timeout_ms: int = 30_000
    scraper_headless: bool = True

    model_config = SettingsConfigDict(env_file=".env")

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

**Neden `lru_cache`?**
Her `get_settings()` çağrısında `.env` dosyası okunmasın diye.
`lru_cache(maxsize=1)` → "Bu fonksiyonu bir kez çağır, sonucu hafızada tut, hep aynı nesneyi döndür."
Bu **Singleton pattern**'in Python'daki en temiz halidir.

**Neden `pydantic-settings`?**
```bash
# .env dosyasındaki değer:
LLM_MODEL=llama-3.3-70b-versatile

# Pydantic otomatik olarak:
# 1. .env'yi okur
# 2. Tipi doğrular (str mi, int mi?)
# 3. Settings nesnesine yükler
```
Manuel `os.environ.get()` yazmana gerek kalmıyor. Tip güvenliği var.

---

## 2️⃣ `app/core/logging.py` — Logger Fabrikası

```python
import logging, sys
from functools import lru_cache
from app.core.config import get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

def _configure_root_logger():
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root = logging.getLogger()
    if not root.handlers:          # ← ÖNEMLİ: çift konfigürasyon önlenir
        root.setLevel(level)
        root.addHandler(handler)

_configure_root_logger()           # Import edilince otomatik çalışır

@lru_cache(maxsize=None)
def get_logger(name=None) -> logging.Logger:
    return logging.getLogger(name or "semantic-scraper")
```

**Kullanım:**
```python
# Her modülde aynı şekilde:
from app.core.logging import get_logger
logger = get_logger(__name__)

logger.info("İş başladı | job_id=%s url=%s", job_id, url)
# Çıktı: 2026-03-11T23:54:06 | INFO     | app.workers.tasks | İş başladı | job_id=abc url=...
```

`__name__` → Python'un modül adı. `app.workers.tasks` gibi. Hangi dosyadan log geldiğini anında görürsün.

**`if not root.handlers` neden var?**
Celery worker'ı birden fazla kez import edebilir. Bu kontrol olmasa log handler'lar üst üste binip aynı satırı 3 kez yazdırırdı.

---

## 3️⃣ `app/models/schemas.py` — Veri Sözleşmesi

```python
from pydantic import BaseModel, HttpUrl, field_validator
from enum import Enum
from typing import Optional, Any

class JobStatus(str, Enum):
    QUEUED     = "queued"
    PROCESSING = "processing"
    DONE       = "done"
    FAILED     = "failed"

class ScrapeRequest(BaseModel):
    url: HttpUrl              # "httpX://..." veya geçersiz URL → otomatik hata
    query: str
    timeout_ms: Optional[int] = None

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must not be empty")
        return v.strip()

class ScrapeJobResponse(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    message: str = "Poll /api/scrape/status/{job_id} for results."

class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    result: Optional[Any] = None
    error: Optional[str] = None
```

**Neden `Enum`?**
```python
# Kötü yol:
if status == "done":   # Yazım hatası yapsan? "dne" → hata bulmak zorlaşır

# İyi yol:
if status == JobStatus.DONE:  # IDE tamamlar, yanlış yazamazsın
```

**`HttpUrl` ne yapıyor?**
```python
# Bu istek → 422 Unprocessable Entity hatası:
{"url": "bu-bir-url-degil", "query": "test"}

# Pydantic HTTP isteği gelmeden önce kontrol eder.
# Sen controller'a bile ulaşmadan reddedilir.
```

---

## 4️⃣ `app/services/scraper_service.py` — Playwright Scraper

```python
from playwright.async_api import (
    Browser, BrowserContext, Page,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

class ScraperService:
    def __init__(self, settings: Settings, logger: Logger) -> None:
        self._settings = settings
        self._logger = logger
    
    async def scrape(self, url: str, timeout_ms: int = None) -> str:
        timeout = timeout_ms or self._settings.scraper_default_timeout_ms
        
        async with async_playwright() as playwright:
            # Chromium tarayıcısını başlat (headless = ekransız)
            browser: Browser = await playwright.chromium.launch(
                headless=self._settings.scraper_headless,
            )
            # Yeni "sekme bağlamı" oluştur (cookie izolasyonu için)
            context: BrowserContext = await browser.new_context(
                user_agent="Mozilla/5.0 ... Chrome/124.0.0.0 Safari/537.36"
            )
            page: Page = await context.new_page()
            
            try:
                await page.goto(
                    url,
                    wait_until="networkidle",  # ← KRİTİK
                    timeout=timeout,
                )
                return await self._extract_text(page)
            finally:
                await context.close()
                await browser.close()
```

**`wait_until="networkidle"` neden kritik?**
```
Normal sites (HTML):     "domcontentloaded" yeter
React/Vue/Next.js sites: JS bundle indirilir → çalışır → veri fetch eder → DOM günceller
                         Bu süreç 2-5 saniye sürebilir

networkidle = "500ms boyunca hiç ağ isteği yoksa, sayfa hazır"
```

**`async with async_playwright()` ne anlama geliyor?**
Context manager. Python `with` bloğu bitince otomatik olarak:
- `context.close()` → tarayıcı bağlamı kapatılır
- `browser.close()` → Chromium process sonlandırılır
Bellek sızıntısı olmaz.

**`user_agent` neden ayarlandı?**
Bazı siteler bot tespiti yapıyor. Varsayılan Playwright user-agent'ı "HeadlessChrome/..." gibi görünüyor → siteleri yakıyor. Gerçek bir tarayıcı gibi görünmek için override ettik.

### `_extract_text` — "Most Content Wins" Stratejisi

```python
async def _extract_text(self, page: Page) -> str:
    candidates = [
        "main",           # Semantik HTML5 elementi
        '[role="main"]',  # ARIA accessibility attribute
        "#content",       # Yaygın ID
        ".content",       # Yaygın class
        "#main-content",
        ".main-content",
        "body",           # Son çare
    ]
    
    _MIN_CHARS = 500
    best_text  = ""
    
    for selector in candidates:
        locator = page.locator(selector).first
        count = await locator.count()
        if count == 0:
            continue
        raw = await locator.inner_text(timeout=5_000)
        cleaned = self._clean_text(raw)
        if len(cleaned) > len(best_text):
            best_text = cleaned  # En uzun metni kazandı
        if selector == "body":
            break
    
    # 500 karakter altındaysa body ile override et
    if len(best_text) < _MIN_CHARS:
        raw = await page.locator("body").first.inner_text(timeout=8_000)
        best_text = self._clean_text(raw)
    
    return best_text
```

**Neden `article` selector'ı listede yok?**
```
books.toscrape.com HTML yapısı:
<article class="product_pod">  ← Kitap 1
<article class="product_pod">  ← Kitap 2
...
<article class="product_pod">  ← Kitap 20

locator("article").first → sadece Kitap 1 döner → 48 karakter
```
Bu bug yaşandı ve "most content wins" stratejisine geçildi.

**Neden `body`'yi her zaman almıyoruz?**
`body` navigasyon, footer, cookie banner gibi gürültülü içerik içerir. `<main>` varsa daha temiz veri verir. Ama main yoksa body fallback'e geçiyoruz.

---

## 5️⃣ `app/services/llm_service.py` — LLM Servisi

```python
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, RateLimitError

_SYSTEM_PROMPT = (
    "You are a precise web research assistant. "
    "Rules you MUST follow:\n"
    "1. Answer in 1-3 sentences maximum.\n"
    "2. Use ONLY information present in the provided page content.\n"
    "3. NEVER repeat the same phrase or sentence more than once.\n"
    "4. If comparing values, list them once and stop.\n"
    "5. If the answer is not in the content, say: 'Not on the page.'"
)

class LLMService:
    def __init__(self, settings: Settings, logger: Logger) -> None:
        self._settings = settings
        self._logger = logger
        
        client_kwargs = {"api_key": settings.openai_api_key}
        if settings.llm_base_url:
            client_kwargs["base_url"] = settings.llm_base_url  # Groq, Gemini vs.
        
        self._client = AsyncOpenAI(**client_kwargs)
    
    async def analyze(self, content: str, query: str) -> str:
        truncated = content[:20_000]  # Token limitini aşmamak için
        
        response = await self._client.chat.completions.create(
            model=self._settings.llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": f"Page content:\n\n{truncated}\n\nQuestion: {query}"},
            ],
            max_tokens=self._settings.llm_max_tokens,
            temperature=self._settings.llm_temperature,
            frequency_penalty=0.5,   # ← Döngü önleme
            presence_penalty=0.3,    # ← Konu tekrarı önleme
        )
        return response.choices[0].message.content.strip()
```

**`frequency_penalty` ve `presence_penalty` ne yapar?**
```
temperature=0.2   → Düşük = tutarlı ama tekrar etme eğilimli
                    Yüksek = yaratıcı ama tutarsız

frequency_penalty=0.5 →
  Her token üretildiğinde, o tokeni daha önce kaç kez kullandıysa
  o kadar ceza alır. "daha pahalı olan" 10 kez yazıldıysa
  11. seferinde yazma ihtimali çok düşer.

presence_penalty=0.3 →
  Bir token daha önce HİÇ kullanıldıysa bile hafif ceza alır.
  Konuya geri dönmeyi engeller.
```

**Neden `base_url` enjeksiyonu yaptık?**
```python
# OpenAI default endpoint:
# https://api.openai.com/v1

# Groq ile:
client_kwargs["base_url"] = "https://api.groq.com/openai/v1"

# API formatı birebir aynı → AsyncOpenAI client değişmiyor
# Sadece nereye gideceği değişiyor
# KOD SIFIR DEĞİŞİKLİK → sadece .env değişiyor
```

**Neden `content[:20_000]`?**
Groq `llama-3.3-70b-versatile` = 128k token bağlamı.
20.000 karakter ≈ 5.000 token.
Hem maliyeti düşürür, hem de response hızı artar.

---

## 6️⃣ `app/workers/celery_app.py` — Kuyruk Konfigürasyonu

```python
from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "semantic_scraper",
    broker=settings.celery_broker_url,     # redis://redis:6379/0
    backend=settings.celery_result_backend, # redis://redis:6379/1
    include=["app.workers.tasks"],          # Hangi modüllerde task var?
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    result_expires=3_600,      # Sonuçlar 1 saat sonra silinir
    task_acks_late=True,       # Worker crash olursa task kaybolmasın
    task_reject_on_worker_lost=True,
    task_soft_time_limit=120,  # 120s'de SoftTimeLimitExceeded fırlatır
    task_time_limit=150,       # 150s'de SIGKILL gönderir
)
```

**Neden iki farklı Redis veritabanı?**
```
redis://redis:6379/0  → Broker (kuyruk)
                        "İşlenecek işler burada bekliyor"

redis://redis:6379/1  → Backend (sonuçlar)
                        "Tamamlanan işlerin sonuçları burada"

Ayrı tutulur = kuyruk trafiği ile sonuç okuma trafiği karışmaz.
```

**`task_acks_late=True` ne anlama gelir?**
```
False (default): Worker task'ı kuyruktan alır almaz "aldım" der → crash olursa veri kaybolur
True:            Worker task'ı tamamlayınca "aldım" der → crash = task yeniden kuyruğa girer
```

---

## 7️⃣ `app/workers/tasks.py` — Asıl İş

```python
import asyncio
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from app.workers.celery_app import celery_app

def _run(coro):
    """Async fonksiyonu sync Celery task içinden çalıştır."""
    return asyncio.get_event_loop().run_until_complete(coro)

@celery_app.task(
    bind=True,              # self = Task instance'ı (retry için gerekli)
    name="tasks.scrape_and_analyze",
    max_retries=2,          # Hata alınca 2 kez daha dene
    default_retry_delay=10, # Denemeler arası 10 saniye bekle
)
def scrape_and_analyze(self: Task, url: str, query: str, timeout_ms=None):
    settings = get_settings()
    logger   = get_logger(__name__)
    
    # DI: Her task çağrısında taze instance
    scraper = ScraperService(settings=settings, logger=logger)
    llm     = LLMService(settings=settings, logger=logger)
    
    try:
        # 1. Scrape
        content = _run(scraper.scrape(url=url, timeout_ms=timeout_ms))
        
        # 2. Analyze
        answer = _run(llm.analyze(content=content, query=query))
        
        return ScrapeResult(
            url=url, query=query,
            raw_text_length=len(content),
            llm_answer=answer,
        ).model_dump()
    
    except SoftTimeLimitExceeded as exc:
        raise RuntimeError("Task timed out.") from exc
    
    except RuntimeError as exc:
        raise self.retry(exc=exc)  # Celery'ye "yeniden dene" diyoruz
```

**`bind=True` ve `self` neden gerekli?**
```python
# bind=False olsaydı:
def scrape_and_analyze(url, query):
    ...
    raise RetryError()  # Nasıl retry ederiz? Bilemeyiz.

# bind=True:
def scrape_and_analyze(self: Task, url, query):
    raise self.retry(exc=exc, countdown=10)  # "10 saniye sonra yeniden dene"
    # self.request.id → job_id
    # self.request.retries → kaçıncı deneme?
```

**`_run()` neden gerekli?**
```python
# Celery task'ları synchronous fonksiyon bekler
# Scraper ve LLM async (await kullanıyor)
# asyncio.get_event_loop().run_until_complete() = "async fonksiyonu sync olarak çalıştır"
# Python 3.10+ alternatif: asyncio.run()
```

---

## 8️⃣ `app/api/routes/scrape.py` — HTTP Katmanı

```python
from fastapi import APIRouter, status
from celery.result import AsyncResult

router = APIRouter(prefix="/api/scrape", tags=["Scraping"])

@router.post(
    "/analyze",
    response_model=ScrapeJobResponse,
    status_code=status.HTTP_202_ACCEPTED,  # "Alındı, işleniyor"
)
async def analyze(payload: ScrapeRequest) -> ScrapeJobResponse:
    task = scrape_and_analyze.delay(      # .delay() = kuyruğa ekle
        url=str(payload.url),
        query=payload.query,
        timeout_ms=payload.timeout_ms,
    )
    return ScrapeJobResponse(job_id=task.id)  # UUID döner


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: str) -> JobStatusResponse:
    task_result: AsyncResult = scrape_and_analyze.AsyncResult(job_id)
    
    # Celery state → bizim JobStatus enum'una map et
    _MAP = {
        "PENDING":  JobStatus.QUEUED,
        "RECEIVED": JobStatus.QUEUED,
        "STARTED":  JobStatus.PROCESSING,
        "RETRY":    JobStatus.PROCESSING,
        "SUCCESS":  JobStatus.DONE,
        "FAILURE":  JobStatus.FAILED,
        "REVOKED":  JobStatus.FAILED,
    }
    
    status = _MAP.get(task_result.state, JobStatus.PROCESSING)
    result = task_result.result if status == JobStatus.DONE else None
    error  = str(task_result.result) if status == JobStatus.FAILED else None
    
    return JobStatusResponse(job_id=job_id, status=status, result=result, error=error)
```

**202 vs 200 ne farkı var?**
```
200 OK          → "İsteğin tamamlandı, sonuç burada"
202 Accepted    → "İsteğini aldım, arka planda işliyorum, sonucu sonra al"

Scraping 30 saniye sürüyor. 200 dönsek HTTP bağlantısı açık kalırdı.
202 dönüp job_id veriyoruz. Kullanıcı istediği zaman poll eder.
```

**`.delay()` nasıl çalışıyor?**
```python
task = scrape_and_analyze.delay(url="...", query="...")
# Arka planda:
# 1. task argümanları JSON'a serialize edilir
# 2. Redis'e yazılır: LPUSH celery {"task": "tasks.scrape_and_analyze", "args": [...]}
# 3. Worker Redis'i dinliyor → görür → çalıştırır
# 4. task.id = UUID (örn: "84c3c6b6-5c57-48b1-a8db-84d478b6dc09")
```

---

## 9️⃣ `app/main.py` — FastAPI Fabrikası

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Uygulama başlıyor...")
    yield                           # ← Uygulama burada çalışır
    logger.info("Uygulama kapanıyor...")

def create_app() -> FastAPI:
    app = FastAPI(
        title="Semantic Web Scraper API",
        version="1.0.0",
        lifespan=lifespan,
    )
    # CORS: Frontend'den (localhost:3000 vs) istek gelebilsin
    app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
    app.include_router(scrape_router.router)
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    return app

app = create_app()  # Uvicorn bu nesneyi kullanır
```

**Neden `create_app()` factory pattern?**
Test yazarken: `app = create_app()` ile başka config'li instance yaratabilirsin.
Direkt `app = FastAPI()` yazsaydın global state olurdu → test izolasyonu zorlaşırdı.

---

## 🐳 `docker-compose.yml` — Neden 3 Servis?

```yaml
services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]  # Redis hazır mı?
    networks: [scraper_net]

  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
    depends_on:
      redis:
        condition: service_healthy  # Redis hazır olmadan başlama
    networks: [scraper_net]

  worker:
    build: .
    command: celery -A app.workers.celery_app worker --concurrency=4
    depends_on:
      redis:
        condition: service_healthy
    networks: [scraper_net]
```

**Neden aynı image'dan iki farklı servis (api + worker)?**
```
Aynı kod, farklı komut:
  api    → uvicorn    (HTTP sunucu)
  worker → celery     (Kuyruk tüketici)

Ölçeklendirme:
  İş yükü arttı → docker compose up --scale worker=5
  5 worker paralel iş yapar, API tek kalır
```

**`networks: [scraper_net]` neden var?**
```
Container'lar birbirini IP ile değil, isimle bulur:
  api  → "redis" diyerek Redis'e bağlanır
  worker → "redis" diyerek Redis'e bağlanır

Dış dünya sadece 8000 portunda API'yi görür.
Redis (6379) ve Celery'ye dışarıdan erişilemez → güvenlik.
```

---

## 🔁 Tam Veri Akışı — Kod Seviyesinde

```
1. curl POST /api/scrape/analyze
   body: {"url": "https://books.toscrape.com/...", "query": "en pahalı kitap?"}

2. FastAPI → ScrapeRequest(url=..., query=...) olarak parse eder (Pydantic)
   Geçersiz URL veya boş query → 422 hatası (controller'a ulaşmaz)

3. scrape_and_analyze.delay(url=..., query=...)
   → JSON serialize → Redis'e yaz
   → {"job_id": "84c3c6b6-...", "status": "queued"} döner (202)

4. Celery Worker Redis'ten task'ı alır
   → ScraperService.scrape("https://books.toscrape.com/...")
   → Playwright Chromium başlar (headless)
   → page.goto(url, wait_until="networkidle", timeout=30000)
   → networkidle beklenir (tüm ajax biter)
   → _extract_text: main/body taranır, en uzun içerik alınır
   → "A Light in the Attic £51.77 In stock\nTipping..." (1610 karakter)

5. LLMService.analyze(content="...", query="en pahalı?")
   → POST https://api.groq.com/openai/v1/chat/completions
   → model=llama-3.3-70b-versatile
   → system=kısa cevap ver, tekrarlama
   → user=sayfa metni + soru
   → response: "En pahalı: £54.86 (Dune #1)"

6. ScrapeResult nesne → dict → Redis'e yaz (job_id key ile)

7. curl GET /api/scrape/status/84c3c6b6-...
   → AsyncResult(job_id) → Redis'ten çek
   → state="SUCCESS" → JobStatus.DONE
   → result={"llm_answer": "En pahalı: £54.86 (Dune #1)"}
```

---

## ⚡ Öğrenmen Gereken Kritik Kavramlar

| Kavram | Nerede kullanıldı | Neden önemli |
|--------|------------------|--------------|
| Singleton | `get_settings()` lru_cache | Her yerde aynı config nesnesi |
| Dependency Injection | ScraperService(settings, logger) | Test edilebilirlik |
| Async/Await | scraper_service, llm_service | I/O blocking olmadan bekle |
| Job Queue | Celery + Redis | Uzun işleri background'a at |
| Polling | GET /status/{id} | 202 pattern'inin tamamlayıcısı |
| Retry | max_retries=2 | Geçici hatalara dayanıklılık |
| SOLID-S | Her sınıf tek iş | Değişiklikler izole kalır |

---

## 🤔 Sıkça Sorulan Sorular

**Q: `asyncio` neden kullanıyoruz?**
```python
# Sync (kötü):
content = scraper.scrape(url1)   # 10 saniye bekle
content = scraper.scrape(url2)   # 10 saniye daha bekle
# Toplam: 20 saniye

# Async (iyi):
content1, content2 = await asyncio.gather(
    scraper.scrape(url1),
    scraper.scrape(url2),
)
# Toplam: 10 saniye (paralel)
```
Async = "ben beklerken başkası çalışabilir"

**Q: Celery neden ayrı process?**
FastAPI içinde `background_tasks.add_task()` da vardı. Neden Celery?
- FastAPI restart → in-memory tasklar kaybolur
- Celery taskları Redis'te → restart sonra kaldığı yerden devam eder
- Celery = production-grade, izleme araçları (Flower), retry mekanizması

**Q: Neden `str(payload.url)` yazıyoruz?**
```python
# payload.url → Pydantic'in HttpUrl nesnesi (str değil)
# Redis'e JSON serialize için str olmalı
task = scrape_and_analyze.delay(url=str(payload.url), ...)
```
