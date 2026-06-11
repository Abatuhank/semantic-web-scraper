"""
app/services/llm_service.py
Single Responsibility: send scraped content + user query to the LLM
and return a concise, factual answer.

Supports any OpenAI-compatible provider via LLM_BASE_URL setting:
  - OpenAI   â†’ leave LLM_BASE_URL empty
  - Groq     â†’ LLM_BASE_URL=https://api.groq.com/openai/v1
  - Gemini   â†’ LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
  - Ollama   â†’ LLM_BASE_URL=http://ollama:11434/v1
  - Custom   â†’ LLM_BASE_URL=https://your-endpoint/v1

Token bÃ¼tÃ§esi rehberi:
  - Gemini 1.5 Pro  â†’ llm_max_content_chars: 500_000+ (2M token kapasitesi)
  - Gemini 1.5 Flashâ†’ llm_max_content_chars: 200_000
  - OpenAI GPT-4o   â†’ llm_max_content_chars: 400_000  (128K token)
  - Groq (free)     â†’ llm_max_content_chars: 38_000   (12K TPM limit)
"""
import logging
import re

from openai import AsyncOpenAI, APIConnectionError, APIStatusError, RateLimitError

from app.core.config import Settings


_SYSTEM_PROMPT = (
    "You are a precise web research assistant. "
    "Rules you MUST follow:\n"
    "1. Answer ONLY based on the page content provided. Do not use prior knowledge.\n"
    "2. Be direct and concise. Avoid repeating yourself.\n"
    "3. When answering about ratings/scores: list each item and its score once, then stop.\n"
    "4. When answering about tables (university scores, hotel ratings, etc.): "
    "present the data as a clean table or numbered list.\n"
    "5. You MUST perform calculations (averages, sums, min, max, counts) using the numbers "
    "found in the page content if the user asks for things like 'most expensive', 'cheapest', 'average', etc. "
    "Do NOT look for the exact text 'most expensive', deduce it yourself by comparing the prices/numbers. "
    "If there is only ONE item/price on the page, just return that item as the answer, do NOT say the information is not found.\n"
    "6. If the information is not in the page content, say: "
    "'Bu bilgi sayfada bulunamadÄ±.' (or in English: 'This information is not on the page.')\n"
    "7. NEVER invent data. NEVER contradict yourself. Think step-by-step to find min/max values, but only output the final logical result.\n"
    "8. Always respond in the same language as the user's question."
)

# Verinin deÄŸerli olduÄŸunu gÃ¶steren sinyal karakterler
_DATA_SIGNALS = re.compile(
    r"[â‚º$â‚¬Â£Â¥]"           # para birimleri
    r"|\d+[.,]\d+"        # ondalÄ±klÄ± sayÄ± (fiyat, puan)
    r"|\d+\s*[Tt][Ll]"   # TL/tl
    r"|%\s*\d|\d\s*%"    # yÃ¼zde
    r"|\d+/\d+"           # oran (9.5/10)
    r"|\d{4,}"            # 4+ haneli sayÄ± (puan, fiyat)
)

# Sorgu anlamÄ±nÄ± bozmayan, skor hesabÄ±na katÄ±lmayan kelimeler
_STOPWORDS = {
    # TÃ¼rkÃ§e
    "iÃ§in", "ile", "olan", "bana", "beni", "kaÃ§", "hangi", "nedir", "nasÄ±l",
    "var", "yok", "bir", "bu", "ÅŸu", "ama", "veya", "gibi", "gÃ¶ster",
    "bul", "listele", "sÃ¶yle", "ver", "tÃ¼m", "hepsi", "bazÄ±",
    # Ä°ngilizce
    "the", "and", "for", "what", "how", "show", "list", "find", "get",
    "are", "all", "any", "its", "not", "but", "with", "from", "that",
}


def smart_trim(content: str, query: str, max_chars: int) -> str:
    """
    Sorguya gÃ¶re en alakalÄ± iÃ§eriÄŸi seÃ§ â€” token israfÄ±nÄ± Ã¶nle.

    Strateji:
      1. Sorgudan anahtar kelimeler Ã§Ä±kar.
      2. Her satÄ±rÄ± keyword eÅŸleÅŸmesi + veri sinyali (â‚º, sayÄ±, puan) ile puanla.
      3. YÃ¼ksek puanlÄ± satÄ±rlarÄ± komÅŸu satÄ±rlarÄ±yla birlikte al (baÄŸlam iÃ§in).
      4. max_chars sÄ±nÄ±rÄ±na kadar en iyi satÄ±rlarÄ± birleÅŸtir.

    EÄŸer iÃ§erik zaten max_chars altÄ±ndaysa dokunma.
    O(n log n) karmaÅŸÄ±klÄ±k â€” bÃ¼yÃ¼k sayfalarda gÃ¼venli.
    """
    if len(content) <= max_chars:
        return content

    query_lower = query.lower()
    keywords = [
        w for w in re.findall(r"\b\w{3,}\b", query_lower)
        if w not in _STOPWORDS
    ]

    lines = content.splitlines()
    scored: list[tuple[float, int]] = []

    for i, line in enumerate(lines):
        line_lower = line.lower()
        score = 0.0

        # Keyword eÅŸleÅŸmesi tam eÅŸleÅŸme + TÃ¼rkÃ§e kÃ¶k eÅŸleÅŸmesi
        # Ã–rn: "laptoplarÄ±n" â†’ "laptop" (5+ char prefix)
        for kw in keywords:
            if kw in line_lower:
                score += 2.0
            elif len(kw) >= 5 and kw[:5] in line_lower:
                score += 1.0  # KÄ±smi eÅŸleÅŸme (TÃ¼rkÃ§e Ã§ekim ekleri iÃ§in)

        # Veri sinyali var mÄ±?
        if _DATA_SIGNALS.search(line):
            score += 1.5

        # BaÅŸlÄ±k satÄ±rÄ±?
        if line.startswith("#"):
            score += 0.5

        # Tablo satÄ±rÄ±?
        if "|" in line and line.count("|") >= 2:
            score += 1.0

        if score > 0:
            scored.append((score, i))

    # Skora gÃ¶re sÄ±rala (yÃ¼ksekten dÃ¼ÅŸÃ¼ÄŸe)
    scored.sort(key=lambda x: x[0], reverse=True)

    # En iyi satÄ±rlarÄ± ve komÅŸularÄ±nÄ± topla O(n) running total ile
    selected_indices: set[int] = set()
    running_total = 0

    for _, idx in scored:
        candidates = []
        for offset in (-1, 0, 1):
            ni = idx + offset
            if 0 <= ni < len(lines) and ni not in selected_indices:
                candidates.append(ni)

        added_chars = sum(len(lines[ni]) + 1 for ni in candidates)  # +1 for newline
        if running_total + added_chars > max_chars:
            break

        for ni in candidates:
            selected_indices.add(ni)
        running_total += added_chars

    # SeÃ§ilen satÄ±rlarÄ± orijinal sÄ±rayla birleÅŸtir
    result_lines = [lines[i] for i in sorted(selected_indices)]
    result = "\n".join(result_lines)

    # HÃ¢lÃ¢ max_chars Ã¼stÃ¼nde ise kaba kesmek zorundayÄ±z
    if len(result) > max_chars:
        result = result[:max_chars]

    return result or content[:max_chars]


class LLMService:
    """
    Sends scraped page content and a natural-language query to any
    OpenAI-compatible LLM provider and returns the generated answer.

    The provider is fully controlled by Settings:
      - ``openai_api_key``         â†’ API key (or arbitrary string for local Ollama)
      - ``llm_base_url``           â†’ empty = OpenAI, or any compatible endpoint
      - ``llm_model``              â†’ model name on the chosen provider
      - ``llm_max_content_chars``  â†’ max chars sent to LLM (0 = no limit)

    Usage::
        service = LLMService(settings=get_settings(), logger=get_logger(__name__))
        answer = await service.analyze(content="...", query="What is the average rating?")
    """

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger

        self._client_kwargs: dict = {"api_key": settings.openai_api_key}
        if settings.llm_base_url:
            self._client_kwargs["base_url"] = settings.llm_base_url
            self._logger.info(
                "LLM provider: %s | base_url=%s | model=%s",
                settings.llm_provider,
                settings.llm_base_url,
                settings.llm_model,
            )
        else:
            self._logger.info(
                "LLM provider: openai | model=%s", settings.llm_model
            )

    def _get_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(**self._client_kwargs)

    async def analyze(self, content: str, query: str) -> str:
        """
        Analyse *content* against *query* using the configured LLM.

        Args:
            content: Markdown-formatted text scraped from the target page.
            query:   Natural-language question from the end user.

        Returns:
            LLM-generated answer string.

        Raises:
            RuntimeError: Wraps any LLM API error.
        """
        # AkÄ±llÄ± iÃ§erik seÃ§imi (sorguya gÃ¶re alakalÄ± satÄ±rlar)
        # SÄ±nÄ±r aÅŸÄ±lmasa bile her zaman hedeflenen boyuta (Ã¶rn. 15.000) kÄ±rparak token tasarrufu saÄŸlar.
        target_chars = getattr(self._settings, "llm_target_content_chars", 15_000)
        max_chars = self._settings.llm_max_content_chars or 38_000
        original_len = len(content)

        if original_len > target_chars:
            trimmed = smart_trim(content, query, target_chars)
            # EÄŸer target_chars'dan sonra yine de max_chars'Ä± aÅŸan (beklenmedik) bir durum varsa hard trim
            if len(trimmed) > max_chars:
                trimmed = trimmed[:max_chars]

            self._logger.info(
                "Smart trim applied | original=%d trimmed=%d saved=%d%% query=%.60s",
                original_len,
                len(trimmed),
                int((1 - len(trimmed) / original_len) * 100),
                query,
            )
        else:
            trimmed = content

        user_message = (
            f"Page content (Markdown format):\n\n{trimmed}\n\n"
            f"Question: {query}"
        )

        self._logger.info(
            "LLM request | provider=%s model=%s content_chars=%d query=%.80s",
            self._settings.llm_provider,
            self._settings.llm_model,
            len(trimmed),
            query,
        )

        try:
            # Gemini ve Ollama bazÄ± OpenAI parametrelerini desteklemez.
            # Sadece OpenAI ve Groq'ta frequency/presence penalty gÃ¶nder.
            _PENALTY_PROVIDERS = {"openai", "groq"}
            extra_params: dict = {}
            if self._settings.llm_provider.lower() in _PENALTY_PROVIDERS:
                extra_params = {
                    "frequency_penalty": 0.3,
                    "presence_penalty": 0.1,
                }

            client = self._get_client()
            response = await client.chat.completions.create(
                model=self._settings.llm_model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=self._settings.llm_max_tokens,
                temperature=self._settings.llm_temperature,
                **extra_params,
            )

            answer = response.choices[0].message.content or ""
            self._logger.info(
                "LLM response received | tokens_used=%s answer_preview=%.80s",
                getattr(response.usage, "total_tokens", "unknown"),
                answer,
            )
            return answer.strip()

        except RateLimitError as exc:
            self._logger.error("LLM rate limit exceeded | error=%s", str(exc))
            raise RuntimeError(f"LLM rate limit exceeded. Retry later. {exc}") from exc

        except APIConnectionError as exc:
            self._logger.error("LLM connection error | error=%s", str(exc))
            raise RuntimeError(f"Could not connect to LLM API: {exc}") from exc

        except APIStatusError as exc:
            self._logger.error(
                "LLM API error | status=%d error=%s", exc.status_code, str(exc)
            )
            raise RuntimeError(
                f"LLM API returned status {exc.status_code}: {exc.message}"
            ) from exc

        except Exception as exc:  # noqa: BLE001
            self._logger.exception("Unexpected LLM error | error=%s", str(exc))
            raise RuntimeError(f"Unexpected LLM error: {exc}") from exc

    async def select_best_links(
        self, query: str, links: list[dict], max_pages: int
    ) -> list[str]:
        """
        KullanÄ±cÄ±nÄ±n sorusuna en uygun olan linkleri seÃ§er.
        
        Args:
            query: KullanÄ±cÄ±nÄ±n sorusu
            links: [{'url': '...', 'text': '...'}, ...] listesi
            max_pages: SeÃ§ilecek maksimum link sayÄ±sÄ±
            
        Returns:
            SeÃ§ilen url'lerin (string) listesi.
        """
        if not links:
            return []
            
        if len(links) <= max_pages:
            return [link['url'] for link in links]

        import json
        
        system_prompt = (
            "You are an intelligent web crawler agent. Your job is to select the most relevant links "
            "to answer the user's query.\n"
            "Rules:\n"
            "1. You will be provided with a JSON array of links containing 'url' and 'text'.\n"
            f"2. You must select the top {max_pages} most relevant links that are likely to contain the answer.\n"
            "3. You must output a valid JSON object exactly in this format: {\"links\": [\"url1\", \"url2\"]}\n"
            "Do NOT output any markdown blocks, explanations, or backticks. Only the JSON object."
        )
        
        # Limit to 300 links to avoid LLM context overflow or parsing errors with massive JSON prompts
        links_to_send = links[:300]
        
        user_message = (
            f"Query: {query}\n\n"
            f"Links: {json.dumps(links_to_send, ensure_ascii=False)}"
        )
        
        self._logger.info("LLM select_best_links request | links_count=%d max_pages=%d", len(links_to_send), max_pages)
        
        try:
            extra_params = {}
            if self._settings.llm_provider.lower() in {"openai", "groq", "gemini"}:
                extra_params["response_format"] = {"type": "json_object"}

            client = self._get_client()
            response = await client.chat.completions.create(
                model=self._settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                max_tokens=1024,
                temperature=0.0,
                **extra_params,
            )
            
            answer = response.choices[0].message.content or "{}"
            
            # Temizleme: Markdown formatÄ±ndaysa JSON'u Ã§Ä±kar
            answer = answer.strip()
            if answer.startswith("```json"):
                answer = answer[7:]
            if answer.startswith("```"):
                answer = answer[3:]
            if answer.endswith("```"):
                answer = answer[:-3]
            answer = answer.strip()
            
            try:
                parsed_json = json.loads(answer)
                selected_urls = parsed_json.get("links", [])
                if not isinstance(selected_urls, list):
                    selected_urls = []
            except json.JSONDecodeError as e:
                self._logger.error("JSON parse error in select_best_links. Raw answer: %s", answer)
                raise e
                
            # Limit the output just in case
            selected_urls = selected_urls[:max_pages]
            
            self._logger.info("LLM selected %d links out of %d", len(selected_urls), len(links))
            return selected_urls
            
        except Exception as exc:
            self._logger.warning("Failed to select links via LLM: %s. Falling back to first %d links.", str(exc), max_pages)
            return [link['url'] for link in links[:max_pages]]
