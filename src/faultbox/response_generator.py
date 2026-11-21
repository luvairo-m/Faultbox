"""Lazy response sequences for validated scenario steps."""

from __future__ import annotations

from collections.abc import Iterator

from faultbox.models import ResponseStep


def generate_responses(steps: list[ResponseStep]) -> Iterator[ResponseStep]:
    """Yield validated, non-empty steps; repeat the last step forever.

    Configuration is only read. Consumers must also treat yielded steps as read-only.
    """
    for step in steps:
        for _ in range(step.repeat):
            yield step

    while True:
        yield steps[-1]
