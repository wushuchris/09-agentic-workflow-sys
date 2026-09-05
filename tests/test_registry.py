import pytest

from src.registry import (
    DuplicateHandlerError,
    HandlerRegistry,
    HandlerRegistryError,
    UnknownHandlerError,
)


def echo_handler(payload: dict) -> dict:
    return {"echo": payload}


def validate_handler(payload: dict) -> dict:
    return {"valid": bool(payload)}


def test_registered_handler_can_be_resolved() -> None:
    registry = HandlerRegistry()
    registry.register("echo", echo_handler)

    resolved = registry.resolve("echo")

    assert resolved is echo_handler
    assert resolved({"message": "hello"}) == {"echo": {"message": "hello"}}


def test_unknown_handler_is_rejected() -> None:
    registry = HandlerRegistry()

    with pytest.raises(UnknownHandlerError, match="is not registered"):
        registry.resolve("arbitrary_function")


def test_duplicate_handler_id_is_rejected() -> None:
    registry = HandlerRegistry()
    registry.register("validate", validate_handler)

    with pytest.raises(DuplicateHandlerError, match="already registered"):
        registry.register("validate", echo_handler)


def test_blank_handler_id_is_rejected_on_registration() -> None:
    registry = HandlerRegistry()

    with pytest.raises(HandlerRegistryError, match="must not be blank"):
        registry.register("   ", echo_handler)


def test_blank_handler_id_is_rejected_on_resolution() -> None:
    registry = HandlerRegistry()

    with pytest.raises(UnknownHandlerError, match="must not be blank"):
        registry.resolve("   ")


def test_non_callable_handler_is_rejected() -> None:
    registry = HandlerRegistry()

    with pytest.raises(HandlerRegistryError, match="must be callable"):
        registry.register("bad", {"not": "callable"})  # type: ignore[arg-type]


def test_handler_ids_are_normalized_and_lookup_is_whitespace_tolerant() -> None:
    registry = HandlerRegistry()
    registry.register("  validate_request  ", validate_handler)

    assert registry.contains("validate_request") is True
    assert registry.resolve(" validate_request ") is validate_handler


def test_registered_ids_are_deterministic_and_do_not_expose_registry_mutation() -> None:
    registry = HandlerRegistry()
    registry.register("zeta", echo_handler)
    registry.register("alpha", validate_handler)

    assert registry.registered_ids() == ("alpha", "zeta")


def test_contains_returns_false_for_unknown_or_blank_ids() -> None:
    registry = HandlerRegistry()
    registry.register("echo", echo_handler)

    assert registry.contains("echo") is True
    assert registry.contains("missing") is False
    assert registry.contains("   ") is False
