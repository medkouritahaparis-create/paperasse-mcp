"""The --rewrite eval mode, without network: a fake client stands in for the API."""

import json
from types import SimpleNamespace

import pytest

import main
from evals import rewrite
from evals.rewrite import RewriteUnavailable, cache_key, rewrite_all, tool_definition

QUESTIONS = [{"id": "q1", "question": "Je suis étudiant, ai-je droit aux APL ?"}]


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        call = SimpleNamespace(type="tool_use", name="search_fiche", input={"query": "APL étudiant"})
        return SimpleNamespace(content=[call], usage=SimpleNamespace(input_tokens=2000, output_tokens=100))


def test_tool_is_sent_as_the_server_publishes_it():
    tool = tool_definition()
    assert tool["name"] == "search_fiche"
    assert "translate" in tool["description"]  # the docstring the client model reads
    assert tool["input_schema"]["required"] == ["query"]


def test_rewrite_calls_model_once_then_uses_cache(tmp_path):
    cache, client = tmp_path / "rewrites.jsonl", FakeClient()
    out, cost = rewrite_all(QUESTIONS, client_factory=lambda: client, cache_path=cache)
    assert out["q1"]["arguments"] == {"query": "APL étudiant"}
    assert len(client.calls) == 1
    sent = client.calls[0]
    assert sent["model"] == rewrite.MODEL and sent["tools"][0]["name"] == "search_fiche"
    assert sent["messages"] == [{"role": "user", "content": QUESTIONS[0]["question"]}]
    assert cost["new_cost_usd"] == pytest.approx((2000 * 0.10 + 100 * 0.50) / 1e6)

    def no_client():
        raise AssertionError("cached rewrites must not call the API")

    out2, cost2 = rewrite_all(QUESTIONS, client_factory=no_client, cache_path=cache)
    assert out2 == out and cost2["new_cost_usd"] == 0
    assert cost2["full_run_cost_usd"] == cost["new_cost_usd"]
    assert len(cache.read_text().splitlines()) == 1


def test_changed_docstring_invalidates_cache():
    tool = tool_definition()
    changed = {**tool, "description": tool["description"] + " More."}
    assert cache_key("q", tool, "i") != cache_key("q", changed, "i")


def test_no_key_skips_cleanly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(rewrite, "ENV_FILE", tmp_path / "missing.env")
    with pytest.raises(RewriteUnavailable, match="ANTHROPIC_API_KEY"):
        rewrite_all(QUESTIONS, cache_path=tmp_path / "empty.jsonl")


def test_env_file_is_read_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nPAPERASSE_TEST_VAR='from-file'\n")
    monkeypatch.setattr(rewrite, "ENV_FILE", env)
    monkeypatch.delenv("PAPERASSE_TEST_VAR", raising=False)
    rewrite._load_env_file()
    import os
    assert os.environ["PAPERASSE_TEST_VAR"] == "from-file"
    monkeypatch.setenv("PAPERASSE_TEST_VAR", "already-set")
    rewrite._load_env_file()
    assert os.environ["PAPERASSE_TEST_VAR"] == "already-set"


def test_rewritten_query_and_audience_are_what_gets_searched(monkeypatch, store):
    from evals.run import run_one
    monkeypatch.setattr(main, "_store", lambda: store)
    q = {"question": "phrase brute sans rapport", "expected": ["F5"], "style": "sentence",
         "query": "micro-entrepreneur", "audience": "professionnels"}
    assert run_one(q)["rank"] == 1
