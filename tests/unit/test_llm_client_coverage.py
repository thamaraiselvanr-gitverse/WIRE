"""LLMClient transport paths without a real Gemini key (google-genai patched).
Exercises init success/failure, the fail-closed no-key path, and every
generate_json branch (valid dict, empty, non-dict, bad JSON, exception)."""

import wire.semantic.llm_client as llm_mod
from wire.semantic.llm_client import LLMClient


class _Resp:
    def __init__(self, text):
        self.text = text


class _Models:
    _next_text = "{}"
    _raise = False

    def generate_content(self, *, model, contents, config):
        if _Models._raise:
            raise RuntimeError("boom")
        return _Resp(_Models._next_text)


class _FakeClient:
    def __init__(self, *a, **k):
        self.models = _Models()


def _patch_client(monkeypatch):
    monkeypatch.setattr(llm_mod.genai, "Client", _FakeClient)


def test_no_key_is_unavailable_and_returns_none(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    client = LLMClient()
    assert client.is_available is False
    assert client.generate_json("sys", "user") is None


def test_init_success_and_valid_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    _patch_client(monkeypatch)
    _Models._raise = False
    _Models._next_text = '{"a": 1, "b": 2}'
    client = LLMClient()
    assert client.is_available is True
    assert client.generate_json("sys", "user") == {"a": 1, "b": 2}


def test_init_failure_disables_client(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")

    def _boom(*a, **k):
        raise RuntimeError("client init failed")

    monkeypatch.setattr(llm_mod.genai, "Client", _boom)
    client = LLMClient()
    assert client.is_available is False


def test_generate_json_empty_non_dict_and_bad_json(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    _patch_client(monkeypatch)
    client = LLMClient()
    _Models._raise = False

    _Models._next_text = ""
    assert client.generate_json("s", "u") is None  # empty

    _Models._next_text = "[1, 2, 3]"
    assert client.generate_json("s", "u") is None  # valid JSON but not a dict

    _Models._next_text = "not json at all"
    assert client.generate_json("s", "u") is None  # JSONDecodeError


def test_generate_json_swallows_call_exception(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    _patch_client(monkeypatch)
    client = LLMClient()
    _Models._raise = True
    try:
        assert client.generate_json("s", "u") is None
    finally:
        _Models._raise = False


def test_model_name_override(monkeypatch):
    monkeypatch.setenv("WIRE_LLM_MODEL", "gemini-custom")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    client = LLMClient()
    assert client._model_name == "gemini-custom"
