"""Bounded correction for structured contracts crossing model/process boundaries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)
Correction = Callable[[ValidationError, Any], Any]


def validate_with_correction(
    model: type[ModelT],
    raw: Any,
    *,
    correct: Correction,
    max_corrections: int = 1,
) -> ModelT:
    """Validate, allowing a bounded external correction callback."""
    candidate = raw
    for attempt in range(max_corrections + 1):
        try:
            return model.model_validate(candidate)
        except ValidationError as error:
            if attempt >= max_corrections:
                raise
            candidate = correct(error, candidate)
    raise AssertionError("unreachable")
