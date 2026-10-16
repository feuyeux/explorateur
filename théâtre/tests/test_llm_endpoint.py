"""Endpoint/key resolution: defaults stay OpenRouter; explicit overrides reroute.

The adaptation layer may point individual model slugs at their own gateways
via RSIAGENT_LLM_ENDPOINTS_FILE. Without any overrides the transport must
remain byte-identical to the historical OpenRouter client.
"""
import json

import pytest

import llm.client as llmclient


@pytest.fixture(autouse=True)
def _hermetic_llm_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RSIAGENT_ROOT", str(tmp_path))  # no stray .env
    for var in ("RSIAGENT_LLM_API_KEY", "OPENROUTER_API_KEY",
                "RSIAGENT_LLM_BASE_URL", "RSIAGENT_LLM_ENDPOINTS_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(llmclient, "_client", None)
    monkeypatch.setattr(llmclient, "_MODEL_CLIENTS", {})
    monkeypatch.setattr(llmclient, "_MODEL_ENDPOINTS", None)


def test_defaults_target_openrouter(tmp_path, monkeypatch):
    assert not (tmp_path / ".env").exists()
    assert llmclient._base_url() == "https://openrouter.ai/api/v1"
    assert llmclient._api_key() == ""
    # The SDK refuses to build a keyless client; routing identity is what is
    # under test here, so hand the default endpoint a placeholder credential.
    monkeypatch.setenv("RSIAGENT_LLM_API_KEY", "unused-default")
    assert llmclient._client_for("z-ai/glm-5.3") is llmclient._c()


def test_rsiagent_key_env_beats_openrouter_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy")
    monkeypatch.setenv("RSIAGENT_LLM_API_KEY", "primary")
    assert llmclient._api_key() == "primary"
    monkeypatch.delenv("RSIAGENT_LLM_API_KEY")
    assert llmclient._api_key() == "legacy"


def test_env_file_serves_both_key_names(tmp_path):
    (tmp_path / ".env").write_text(
        "RSIAGENT_LLM_BASE_URL=https://internal.invalid/v1\n"
        "OPENROUTER_API_KEY=legacy-file-key\n",
        encoding="utf-8")
    assert llmclient._api_key() == "legacy-file-key"
    assert llmclient._base_url() == "https://internal.invalid/v1"
    (tmp_path / ".env").write_text(
        "RSIAGENT_LLM_API_KEY=primary-file-key\n",
        encoding="utf-8")
    assert llmclient._api_key() == "primary-file-key"


def test_env_vars_beat_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "RSIAGENT_LLM_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("RSIAGENT_LLM_API_KEY", "from-env")
    assert llmclient._api_key() == "from-env"


def test_endpoint_map_routes_models_independently(tmp_path, monkeypatch):
    mapping = tmp_path / "endpoints.json"
    mapping.write_text(json.dumps({
        "MiniMax-M3": {"base_url": "https://agent.invalid/llm/v1",
                        "api_key": "m3-key"},
        "fuyao-work": {"base_url": "http://gateway.invalid/v1",
                        "api_key": "fuyao-key"},
    }), encoding="utf-8")
    monkeypatch.setenv("RSIAGENT_LLM_ENDPOINTS_FILE", str(mapping))
    monkeypatch.setenv("RSIAGENT_LLM_API_KEY", "unused-default")

    actor = llmclient._client_for("MiniMax-M3")
    curriculum = llmclient._client_for("fuyao-work")
    other = llmclient._client_for("unmapped/model")

    assert str(actor.base_url) == "https://agent.invalid/llm/v1/"
    assert str(curriculum.base_url) == "http://gateway.invalid/v1/"
    assert actor is not curriculum
    # Cached per model: a second lookup returns the same client instance.
    assert llmclient._client_for("MiniMax-M3") is actor
    # Unmapped models keep the default endpoint and the default client.
    assert other is llmclient._c()
    assert str(other.base_url) == "https://openrouter.ai/api/v1/"


def test_invalid_endpoint_map_fails_closed_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("RSIAGENT_LLM_API_KEY", "unused-default")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("RSIAGENT_LLM_ENDPOINTS_FILE", str(broken))
    assert llmclient._model_endpoints() == {}
    assert llmclient._client_for("MiniMax-M3") is llmclient._c()

    shapeless = tmp_path / "shapeless.json"
    shapeless.write_text(json.dumps({"MiniMax-M3": {"base_url": "x"}}),
                          encoding="utf-8")
    monkeypatch.setattr(llmclient, "_MODEL_ENDPOINTS", None)
    monkeypatch.setattr(llmclient, "_MODEL_CLIENTS", {})
    monkeypatch.setenv("RSIAGENT_LLM_ENDPOINTS_FILE", str(shapeless))
    # An endpoint entry without credentials is dropped, not half-applied.
    assert llmclient._model_endpoints() == {}
    assert llmclient._client_for("MiniMax-M3") is llmclient._c()


def test_missing_endpoint_map_file_fails_closed_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("RSIAGENT_LLM_API_KEY", "unused-default")
    monkeypatch.setenv("RSIAGENT_LLM_ENDPOINTS_FILE",
                        str(tmp_path / "absent.json"))
    assert llmclient._model_endpoints() == {}
    assert llmclient._client_for("MiniMax-M3") is llmclient._c()
