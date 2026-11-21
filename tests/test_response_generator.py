from __future__ import annotations

from copy import deepcopy
from itertools import islice

import pytest

from faultbox.models import ResponseStep
from faultbox.response_generator import generate_responses


@pytest.mark.parametrize(
    ("steps", "expected_statuses"),
    [
        (
            [ResponseStep(status=500, repeat=2), ResponseStep(status=200)],
            [500, 500, 200, 200],
        ),
        ([ResponseStep(status=201, repeat=2)], [201, 201, 201, 201]),
        (
            [
                ResponseStep(status=503),
                ResponseStep(status=500, repeat=2),
                ResponseStep(status=200, repeat=2),
            ],
            [503, 500, 500, 200, 200, 200],
        ),
    ],
    ids=["retry", "single-step", "several-steps"],
)
def test_generate_responses_repeats_steps_in_order(
    steps: list[ResponseStep], expected_statuses: list[int]
) -> None:
    responses = generate_responses(steps)

    assert [step.status for step in islice(responses, len(expected_statuses))] == (
        expected_statuses
    )


def test_new_generator_starts_from_first_step() -> None:
    steps = [ResponseStep(status=500), ResponseStep(status=200)]
    first = generate_responses(steps)
    assert [step.status for step in islice(first, 2)] == [500, 200]

    second = generate_responses(steps)

    assert next(second).status == 500
    assert next(first).status == 200


def test_generate_responses_handles_large_repeat_lazily() -> None:
    steps = [ResponseStep(status=500, repeat=10**12), ResponseStep(status=200)]
    responses = generate_responses(steps)

    assert [step.status for step in islice(responses, 3)] == [500, 500, 500]


def test_generate_responses_preserves_configuration() -> None:
    steps = [
        ResponseStep(
            status=500,
            headers={"Retry-After": "1"},
            body="temporary failure",
            delay_ms=100,
            repeat=2,
        ),
        ResponseStep(
            status=200,
            headers={"Content-Type": "text/plain"},
            body="loaded text",
            body_file="response.txt",
        ),
    ]
    original = deepcopy(steps)

    responses = list(islice(generate_responses(steps), 4))

    assert responses == [original[0], original[0], original[1], original[1]]
    assert steps == original
