"""Bounded model-assisted classification for the service-request workflow.

The model may propose only a classification value. Application code controls the
prompt inputs, parses strict JSON, validates the proposal with Pydantic, and returns
normalized data to the workflow. The model never receives or controls workflow
state, route tables, handler identifiers, retry limits, or approval decisions.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError


ModelCall = Callable[[str], str]


class RequestClassification(str, Enum):
    ACCESS_REQUEST = "ACCESS_REQUEST"
    BILLING_REQUEST = "BILLING_REQUEST"
    GENERAL_SERVICE_REQUEST = "GENERAL_SERVICE_REQUEST"


class ClassificationProposal(BaseModel):
    """Strict structured output accepted from a classification model."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    classification: RequestClassification
    rationale: str = Field(min_length=1, max_length=300)


class ModelClassificationError(ValueError):
    """Raised when model output cannot be accepted as a bounded proposal."""


def build_classification_prompt(*, request_type: str, description: str) -> str:
    """Build a minimal prompt containing only information needed for classification."""

    return (
        "Classify this synthetic service request. Return ONLY a JSON object with "
        "exactly two fields: classification and rationale. "
        "classification must be exactly one of ACCESS_REQUEST, BILLING_REQUEST, "
        "GENERAL_SERVICE_REQUEST. rationale must be a short plain-text explanation.\n\n"
        f"request_type: {request_type}\n"
        f"description: {description}"
    )


def classify_with_model(
    model_call: ModelCall,
    *,
    request_type: str,
    description: str,
) -> dict[str, str]:
    """Call a model and strictly validate its bounded classification proposal.

    Errors are deliberately sanitized because executor error text is included in
    control-plane audit events. Rejected model output is never copied into those
    events.
    """

    prompt = build_classification_prompt(
        request_type=request_type,
        description=description,
    )

    try:
        raw_response = model_call(prompt)
    except Exception as exc:
        raise ModelClassificationError("model classification call failed") from exc

    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ModelClassificationError("model response must be a non-blank JSON string")

    try:
        proposal = ClassificationProposal.model_validate_json(raw_response)
    except (ValidationError, ValueError) as exc:
        raise ModelClassificationError(
            "model classification output failed schema validation"
        ) from exc

    return {
        "classification": proposal.classification.value,
        "rationale": proposal.rationale,
        "source": "MODEL_ASSISTED",
    }
