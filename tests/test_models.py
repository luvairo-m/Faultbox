import pytest

from faultbox.models import ResponseStep, Route


def test_response_step_defaults() -> None:
    step = ResponseStep(status=200)

    assert step.headers == {}
    assert step.body == ""
    assert step.body_file is None
    assert step.delay_ms == 0
    assert step.repeat == 1


def test_file_step_has_no_inline_body() -> None:
    step = ResponseStep(status=200, body_file="responses/payment.json")

    assert step.body is None
    assert step.body_file == "responses/payment.json"


def test_empty_inline_body_conflicts_with_body_file() -> None:
    with pytest.raises(ValueError, match="body and body_file"):
        ResponseStep(status=200, body="", body_file="responses/payment.json")


def test_default_dictionaries_are_independent() -> None:
    first = Route(
        id="first", method="GET", path="/users", steps=[ResponseStep(status=200)]
    )
    second = Route(
        id="second", method="GET", path="/users", steps=[ResponseStep(status=200)]
    )

    assert first.match.headers == second.match.headers == {}
    assert first.match.query == second.match.query == {}
    assert first.match.headers is not second.match.headers
    assert first.match.query is not second.match.query
    assert first.steps[0].headers is not second.steps[0].headers
