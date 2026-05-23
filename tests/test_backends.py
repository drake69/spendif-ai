"""Unit tests for core/llm_backends.py."""
import json
from unittest.mock import MagicMock, patch

import pytest

from core.llm_backends import (
    BackendFactory,
    LLMValidationError,
    OllamaBackend,
    SanitizationRequiredError,
    _validate_required,
)


class TestValidateRequired:
    def test_passes_when_all_present(self):
        _validate_required({"a": 1, "b": 2}, {"required": ["a", "b"]})

    def test_raises_when_missing(self):
        with pytest.raises(LLMValidationError):
            _validate_required({"a": 1}, {"required": ["a", "b"]})

    def test_no_required_key(self):
        _validate_required({"x": 1}, {})  # should not raise


class TestBackendFactory:
    def test_creates_ollama(self):
        backend = BackendFactory.create("local_ollama")
        assert backend.name == "local_ollama"
        assert backend.is_remote is False

    def test_creates_openai(self):
        backend = BackendFactory.create("openai")
        assert backend.name == "openai"
        assert backend.is_remote is True

    def test_creates_claude(self):
        backend = BackendFactory.create("claude")
        assert backend.name == "claude"
        assert backend.is_remote is True

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            BackendFactory.create("unknown_backend")


class TestOllamaBackend:
    def test_is_not_remote(self):
        b = OllamaBackend()
        assert b.is_remote is False

    def test_complete_structured_success(self):
        b = OllamaBackend()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "response": json.dumps({"category": "Alimentari", "subcategory": "Spesa supermercato", "confidence": "high"})
        }
        schema = {"required": ["category", "subcategory", "confidence"]}
        with patch.object(b._requests, "post", return_value=mock_resp) as mock_post:
            result = b.complete_structured("sys", "user", schema)
            assert result["category"] == "Alimentari"
            call_url = mock_post.call_args[0][0]
            assert "/api/generate" in call_url

    def test_complete_structured_invalid_json_raises(self):
        b = OllamaBackend()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"response": "not json"}
        with patch.object(b._requests, "post", return_value=mock_resp):
            with pytest.raises(LLMValidationError):
                b.complete_structured("sys", "user", {})


class TestLlamaCppErrorTranslation:
    """The LlamaCppBackend's `except Exception` must turn raw llama.cpp
    return codes into actionable user-facing messages — the bare
    `llama_decode returned -3` leaks implementation details and gives
    the user no clue what to do next."""

    def _make_backend_stub(self, n_ctx_value: int = 4096):
        """Build a LlamaCppBackend instance without loading a real model.

        We monkey-patch __init__ so we can attach a fake `self._llm` that
        only needs `tokenize`, `n_ctx`, `create_completion`."""
        from core.llm_backends import LlamaCppBackend
        from unittest.mock import MagicMock

        backend = LlamaCppBackend.__new__(LlamaCppBackend)
        backend._model_path = "/tmp/fake.gguf"
        backend._llm = MagicMock()
        backend._llm.tokenize = lambda b: [0] * 100  # 100 input tokens
        backend._llm.n_ctx = lambda: n_ctx_value
        backend._set_usage = lambda *a, **kw: None
        return backend

    def test_llama_decode_minus_3_becomes_kv_overflow_message(self):
        """The -3 return code is mapped to a KV-cache-overflow message."""
        from core.llm_backends import LlamaCppBackend, LLMValidationError
        import pytest

        backend = self._make_backend_stub(n_ctx_value=4096)
        # Simulate the llama-cpp-python error
        def _boom(**_kwargs):
            raise RuntimeError("llama_decode returned -3")
        backend._llm.create_completion = _boom

        # Stub the prompt rendering to keep this test independent of
        # the (large) chat-template machinery.
        backend._render_prompt = lambda *a, **kw: "x"

        with pytest.raises(LLMValidationError) as ei:
            backend.complete_structured(
                system_prompt="sys", user_prompt="usr",
                json_schema={"type": "object", "properties": {}, "required": []},
            )
        msg = str(ei.value).lower()
        assert "kv cache" in msg, msg
        assert "context window" in msg, msg
        assert "4096" in str(ei.value), "the current n_ctx should be surfaced"
        # The original llama_decode text is kept in the Detail tail.
        assert "llama_decode returned -3" in str(ei.value)

    def test_llama_decode_minus_2_becomes_decode_failed_message(self):
        """The -2 return code is mapped to a generic decode-failure message
        with a hint to retry/shorten the prompt."""
        from core.llm_backends import LlamaCppBackend, LLMValidationError
        import pytest

        backend = self._make_backend_stub()
        def _boom(**_kwargs):
            raise RuntimeError("llama_decode returned -2")
        backend._llm.create_completion = _boom
        backend._render_prompt = lambda *a, **kw: "x"

        with pytest.raises(LLMValidationError) as ei:
            backend.complete_structured(
                system_prompt="sys", user_prompt="usr",
                json_schema={"type": "object", "properties": {}, "required": []},
            )
        msg = str(ei.value).lower()
        assert "decode failed" in msg, msg
        assert "shorter prompt" in msg or "different model" in msg, msg

    def test_oom_message_in_english(self):
        """The OOM branch was previously in Italian; verify the new
        English copy reaches the user."""
        from core.llm_backends import LlamaCppBackend, LLMValidationError
        import pytest

        backend = self._make_backend_stub()
        def _boom(**_kwargs):
            raise RuntimeError("ggml_metal_graph_compute: command buffer 0 failed with status 5 - Out of memory")
        backend._llm.create_completion = _boom
        backend._render_prompt = lambda *a, **kw: "x"

        with pytest.raises(LLMValidationError) as ei:
            backend.complete_structured(
                system_prompt="sys", user_prompt="usr",
                json_schema={"type": "object", "properties": {}, "required": []},
            )
        msg = str(ei.value).lower()
        assert "not enough memory" in msg, msg
        assert "smaller model" in msg or "lower n_ctx" in msg, msg

    def test_unknown_runtime_error_still_wrapped(self):
        """A runtime error that doesn't match any known pattern must still
        be wrapped in LLMValidationError (not propagate as RuntimeError)."""
        from core.llm_backends import LlamaCppBackend, LLMValidationError
        import pytest

        backend = self._make_backend_stub()
        def _boom(**_kwargs):
            raise RuntimeError("model file corrupted")
        backend._llm.create_completion = _boom
        backend._render_prompt = lambda *a, **kw: "x"

        with pytest.raises(LLMValidationError) as ei:
            backend.complete_structured(
                system_prompt="sys", user_prompt="usr",
                json_schema={"type": "object", "properties": {}, "required": []},
            )
        assert "model file corrupted" in str(ei.value)
