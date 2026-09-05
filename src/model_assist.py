"""Bounded model assistance for the synthetic wealth-onboarding workflow.

The model may organize onboarding notes and propose only a household profile category
plus a concise summary. Application code controls prompt inputs, parses strict JSON,
validates the proposal with Pydantic, and returns normalized data to the workflow.
The model never receives or controls workflow state, exception routing, handler
identifiers, retry limits, document rules, identity-review status, or human decisions.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError


ModelCall = Callable[[str], str]


class HouseholdProfileCategory(str, Enum):
    STANDARD_HOUSEHOLD = "STANDARD_HOUSEHOLD"
    COMPLEX_HOUSEHOLD = "COMPLEX_HOUSEHOLD"
    SPECIAL_STRUCTURE = "SPECIAL_STRUCTURE"


class OnboardingAIProposal(BaseModel):
    """Strict structured output accepted from the onboarding model boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    profile_category: HouseholdProfileCategory
    summary: str = Field(min_length=1, max_length=400)


class ModelOnboardingError(ValueError):
    """Raised when model output cannot be accepted as a bounded proposal."""


def build_onboarding_prompt(*, household_type: str, onboarding_notes: str) -> str:
    """Build a minimal prompt containing only information needed for intake organization."""

    return (
        "Organize this fictional wealth-management onboarding intake. Return ONLY a JSON "
        "object with exactly two fields: profile_category and summary. "
        "profile_category must be exactly one of STANDARD_HOUSEHOLD, COMPLEX_HOUSEHOLD, "
        "SPECIAL_STRUCTURE. summary must be a concise plain-text intake summary. "
        "Do not recommend approval, rejection, routing, account opening, or any workflow action.\n\n"
        f"household_type: {household_type}\n"
        f"onboarding_notes: {onboarding_notes}"
    )


def organize_onboarding_with_model(
    model_call: ModelCall,
    *,
    household_type: str,
    onboarding_notes: str,
) -> dict[str, str]:
    """Call a model and strictly validate its bounded onboarding proposal.

    Errors are deliberately sanitized because executor error text is included in
    control-plane audit events. Rejected model output is never copied into those events.
    """

    prompt = build_onboarding_prompt(
        household_type=household_type,
        onboarding_notes=onboarding_notes,
    )

    try:
        raw_response = model_call(prompt)
    except Exception as exc:
        raise ModelOnboardingError("model onboarding call failed") from exc

    if not isinstance(raw_response, str) or not raw_response.strip():
        raise ModelOnboardingError("model response must be a non-blank JSON string")

    try:
        proposal = OnboardingAIProposal.model_validate_json(raw_response)
    except (ValidationError, ValueError) as exc:
        raise ModelOnboardingError(
            "model onboarding output failed schema validation"
        ) from exc

    return {
        "profile_category": proposal.profile_category.value,
        "summary": proposal.summary,
        "source": "MODEL_ASSISTED",
    }
