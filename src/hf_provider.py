"""Hugging Face Inference Providers adapter for the bounded onboarding AI node.

This module intentionally knows nothing about workflow state, routes, retries, or
human decisions. It converts one text prompt into one text response. The existing
Pydantic model boundary in ``src.model_assist`` remains responsible for validating
that response before the workflow can use it.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from huggingface_hub import InferenceClient


DEFAULT_MODEL_ID = "Qwen/Qwen2.5-7B-Instruct-1M"


def live_ai_enabled_from_env() -> bool:
    """Return whether the deployment explicitly opted into live inference."""

    value = os.getenv("LIVE_AI_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def configured_model_id() -> str:
    """Return the configured model id without exposing any credentials."""

    value = os.getenv("MODEL_ID", DEFAULT_MODEL_ID).strip()
    return value or DEFAULT_MODEL_ID


def build_hf_onboarding_model_from_env() -> Callable[[str], str] | None:
    """Build a live HF model callable only when deployment explicitly enables it.

    Both ``LIVE_AI_ENABLED=true`` and a non-blank ``HF_TOKEN`` are required. This
    avoids accidental provider usage just because a token happens to exist in the
    environment.
    """

    if not live_ai_enabled_from_env():
        return None

    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        return None

    return build_hf_onboarding_model(token=token, model_id=configured_model_id())


def build_hf_onboarding_model(
    *,
    token: str,
    model_id: str,
    client_factory: Callable[..., InferenceClient] = InferenceClient,
) -> Callable[[str], str]:
    """Return a provider callable compatible with ``ModelCall``.

    The provider is asked for JSON to improve reliability, but its output is still
    treated as untrusted text. ``organize_onboarding_with_model`` performs the strict
    schema validation and rejects extra workflow-control fields.
    """

    normalized_token = token.strip()
    normalized_model_id = model_id.strip()
    if not normalized_token:
        raise ValueError("token must be non-blank")
    if not normalized_model_id:
        raise ValueError("model_id must be non-blank")

    client = client_factory(api_key=normalized_token, provider="auto")

    def model_call(prompt: str) -> str:
        completion = client.chat.completions.create(
            model=normalized_model_id,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only a valid JSON object matching the user's requested "
                        "schema. Do not include Markdown fences or commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=220,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider returned an empty response")
        return content.strip()

    return model_call
