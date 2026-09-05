from types import SimpleNamespace

import pytest

from src.hf_provider import (
    DEFAULT_MODEL_ID,
    build_hf_onboarding_model,
    build_hf_onboarding_model_from_env,
    configured_model_id,
    live_ai_enabled_from_env,
)


def test_live_ai_requires_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_AI_ENABLED", raising=False)
    monkeypatch.setenv("HF_TOKEN", "hf_synthetic")

    assert live_ai_enabled_from_env() is False
    assert build_hf_onboarding_model_from_env() is None


def test_live_ai_requires_token_even_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_AI_ENABLED", "true")
    monkeypatch.delenv("HF_TOKEN", raising=False)

    assert live_ai_enabled_from_env() is True
    assert build_hf_onboarding_model_from_env() is None


def test_configured_model_defaults_and_can_be_overridden(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_ID", raising=False)
    assert configured_model_id() == DEFAULT_MODEL_ID

    monkeypatch.setenv("MODEL_ID", "example/model")
    assert configured_model_id() == "example/model"


def test_provider_callable_uses_auto_provider_and_returns_text() -> None:
    calls: dict[str, object] = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls["create"] = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"profile_category":"STANDARD_HOUSEHOLD",'
                                '"summary":"Synthetic live-model summary."}'
                            )
                        )
                    )
                ]
            )

    class FakeClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    def fake_factory(**kwargs):
        calls["factory"] = kwargs
        return FakeClient()

    model_call = build_hf_onboarding_model(
        token="hf_synthetic",
        model_id="example/model",
        client_factory=fake_factory,
    )
    result = model_call("bounded prompt")

    assert calls["factory"] == {"api_key": "hf_synthetic", "provider": "auto"}
    create_kwargs = calls["create"]
    assert isinstance(create_kwargs, dict)
    assert create_kwargs["model"] == "example/model"
    assert create_kwargs["temperature"] == 0.1
    assert create_kwargs["response_format"] == {"type": "json_object"}
    assert create_kwargs["messages"][1]["content"] == "bounded prompt"
    assert result.startswith('{"profile_category"')


def test_provider_builder_rejects_blank_configuration() -> None:
    with pytest.raises(ValueError, match="token must be non-blank"):
        build_hf_onboarding_model(token=" ", model_id="example/model")

    with pytest.raises(ValueError, match="model_id must be non-blank"):
        build_hf_onboarding_model(token="hf_synthetic", model_id=" ")
