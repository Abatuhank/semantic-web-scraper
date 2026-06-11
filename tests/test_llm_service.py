"""
tests/test_llm_service.py
LLMService testleri (mock'lu â€” gerÃ§ek API Ã§aÄŸrÄ±sÄ± YAPMAZ).

Test Edilen Dosya: app/services/llm_service.py
Ne Test Ediliyor:
  1. analyze() â€” LLM Ã§aÄŸrÄ±sÄ±nÄ±n doÄŸru parametrelerle yapÄ±lmasÄ±
  2. Ä°Ã§erik kÄ±rpma (smart_trim) entegrasyonu
  3. Hata senaryolarÄ±: RateLimitError, APIConnectionError, APIStatusError
  4. Provider'a gÃ¶re penalty parametreleri
  5. select_best_links() â€” JSON parse ve fallback
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_service import LLMService


# Fixtures

@pytest.fixture()
def llm_service(mock_settings, test_logger):
    """Mock settings ile LLMService oluÅŸtur."""
    return LLMService(settings=mock_settings, logger=test_logger)


def _make_mock_response(content: str, total_tokens: int = 100):
    """OpenAI API response mock'u oluÅŸtur."""
    choice = MagicMock()
    choice.message.content = content

    usage = MagicMock()
    usage.total_tokens = total_tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


# analyze() BaÅŸarÄ±lÄ± Ã§aÄŸrÄ±lar

class TestLLMAnalyze:

    @pytest.mark.asyncio
    async def test_analyze_success(self, llm_service):
        """Girdi: content='Laptop A: â‚º15999', query='en ucuz laptop'
        Beklenen: LLM'den gelen cevap dÃ¶ner"""
        mock_response = _make_mock_response("En ucuz laptop: Laptop A, â‚º15.999")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            result = await llm_service.analyze(
                content="Laptop A: â‚º15999\nLaptop B: â‚º24999",
                query="en ucuz laptop hangisi?"
            )

        assert "Laptop A" in result
        assert "15.999" in result or "15999" in result

    @pytest.mark.asyncio
    async def test_analyze_trims_long_content(self, llm_service):
        """Girdi: 10000 karakterlik iÃ§erik (target_chars=3000 Ã¼stÃ¼nde)
        Beklenen: LLM'e gÃ¶nderilen iÃ§erik kÄ±rpÄ±lÄ±r"""
        long_content = "A" * 10_000
        mock_response = _make_mock_response("Cevap")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            result = await llm_service.analyze(
                content=long_content, query="test"
            )

        # create Ã§aÄŸrÄ±sÄ±nÄ±n yapÄ±ldÄ±ÄŸÄ±nÄ± doÄŸrula
        mock_client.chat.completions.create.assert_called_once()

        # GÃ¶nderilen mesajdaki content uzunluÄŸunu kontrol et
        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args.kwargs["messages"][1]["content"]
        # 10000 char olan orijinalden daha kÄ±sa olmalÄ± (smart_trim Ã§alÄ±ÅŸtÄ±)
        assert len(user_msg) < 10_000

    @pytest.mark.asyncio
    async def test_analyze_strips_whitespace(self, llm_service):
        """Girdi: LLM '  cevap  ' dÃ¶ner (boÅŸluklu)
        Beklenen: BoÅŸluklar temizlenerek 'cevap' dÃ¶ner"""
        mock_response = _make_mock_response("  cevap  ")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            result = await llm_service.analyze(content="test", query="test")

        assert result == "cevap"


# analyze() Hata senaryolarÄ±

class TestLLMErrors:

    @pytest.mark.asyncio
    async def test_rate_limit_raises_runtime_error(self, llm_service):
        """Girdi: LLM 429 RateLimitError fÄ±rlatÄ±r
        Beklenen: RuntimeError (rate limit mesajÄ±yla)"""
        from openai import RateLimitError

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_response.json.return_value = {"error": {"message": "rate limit"}}
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RateLimitError(
                message="Rate limit exceeded",
                response=mock_response,
                body=None,
            )
        )

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="rate limit"):
                await llm_service.analyze(content="test", query="test")

    @pytest.mark.asyncio
    async def test_connection_error_raises_runtime_error(self, llm_service):
        """Girdi: LLM API'ye baÄŸlanamÄ±yor
        Beklenen: RuntimeError (connection error mesajÄ±yla)"""
        from openai import APIConnectionError

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=APIConnectionError(request=MagicMock())
        )

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="connect"):
                await llm_service.analyze(content="test", query="test")


# analyze() Provider'a gÃ¶re parametreler

class TestLLMProviderParams:

    @pytest.mark.asyncio
    async def test_openai_provider_sends_penalties(self, mock_settings, test_logger):
        """Girdi: llm_provider='openai'
        Beklenen: frequency_penalty ve presence_penalty parametreleri gÃ¶nderilir"""
        mock_settings.llm_provider = "openai"
        service = LLMService(settings=mock_settings, logger=test_logger)

        mock_response = _make_mock_response("test cevap")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(service, "_get_client", return_value=mock_client):
            await service.analyze(content="test", query="test")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "frequency_penalty" in call_kwargs
        assert "presence_penalty" in call_kwargs

    @pytest.mark.asyncio
    async def test_gemini_provider_no_penalties(self, mock_settings, test_logger):
        """Girdi: llm_provider='gemini'
        Beklenen: frequency_penalty ve presence_penalty gÃ¶nderilMEZ"""
        mock_settings.llm_provider = "gemini"
        service = LLMService(settings=mock_settings, logger=test_logger)

        mock_response = _make_mock_response("test cevap")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(service, "_get_client", return_value=mock_client):
            await service.analyze(content="test", query="test")

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "frequency_penalty" not in call_kwargs
        assert "presence_penalty" not in call_kwargs


#  select_best_links()

class TestSelectBestLinks:

    @pytest.mark.asyncio
    async def test_empty_links_returns_empty(self, llm_service):
        """Girdi: BoÅŸ link listesi
        Beklenen: BoÅŸ liste dÃ¶ner"""
        result = await llm_service.select_best_links(
            query="test", links=[], max_pages=5
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_fewer_links_than_max_returns_all(self, llm_service):
        """Girdi: 3 link, max_pages=10
        Beklenen: TÃ¼m 3 link LLM Ã§aÄŸrÄ±sÄ± yapmadan dÃ¶ner"""
        links = [
            {"url": "https://example.com/1", "text": "Sayfa 1"},
            {"url": "https://example.com/2", "text": "Sayfa 2"},
            {"url": "https://example.com/3", "text": "Sayfa 3"},
        ]
        result = await llm_service.select_best_links(
            query="test", links=links, max_pages=10
        )
        assert len(result) == 3
        assert result[0] == "https://example.com/1"

    @pytest.mark.asyncio
    async def test_select_parses_llm_json(self, llm_service):
        """Girdi: 20 link, max_pages=3, LLM geÃ§erli JSON dÃ¶ner
        Beklenen: LLM'in seÃ§tiÄŸi 3 URL dÃ¶ner"""
        links = [
            {"url": f"https://example.com/{i}", "text": f"Sayfa {i}"}
            for i in range(20)
        ]

        selected_json = json.dumps({
            "links": [
                "https://example.com/5",
                "https://example.com/12",
                "https://example.com/7",
            ]
        })
        mock_response = _make_mock_response(selected_json)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            result = await llm_service.select_best_links(
                query="en ucuz otel", links=links, max_pages=3
            )

        assert len(result) == 3
        assert "https://example.com/5" in result

    @pytest.mark.asyncio
    async def test_select_fallback_on_invalid_json(self, llm_service):
        """Girdi: LLM geÃ§ersiz JSON dÃ¶ner
        Beklenen: Ä°lk max_pages link'e fallback yapÄ±lÄ±r"""
        links = [
            {"url": f"https://example.com/{i}", "text": f"Sayfa {i}"}
            for i in range(20)
        ]

        mock_response = _make_mock_response("Bu geÃ§erli JSON deÄŸil!!!")

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            result = await llm_service.select_best_links(
                query="test", links=links, max_pages=5
            )

        # Fallback: ilk 5 link dÃ¶ner
        assert len(result) == 5
        assert result[0] == "https://example.com/0"

    @pytest.mark.asyncio
    async def test_select_handles_markdown_wrapped_json(self, llm_service):
        """Girdi: LLM ```json ... ``` sarmalÄ± ile JSON dÃ¶ner
        Beklenen: Markdown temizlenir, JSON parse edilir"""
        links = [
            {"url": f"https://example.com/{i}", "text": f"Sayfa {i}"}
            for i in range(20)
        ]

        wrapped = '```json\n{"links": ["https://example.com/3"]}\n```'
        mock_response = _make_mock_response(wrapped)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_service, "_get_client", return_value=mock_client):
            result = await llm_service.select_best_links(
                query="test", links=links, max_pages=5
            )

        assert "https://example.com/3" in result
