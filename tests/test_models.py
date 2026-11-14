import pytest

from faultbox.models import ResponseStep, Route


def test_response_step_uses_defaults() -> None:
    step = ResponseStep(status=200)

    assert step.headers == {}
    assert step.body == ""
    assert step.body_file is None
    assert step.delay_ms == 0
    assert step.repeat == 1


def test_response_step_with_body_file_has_no_inline_body() -> None:
    step = ResponseStep(status=200, body_file="responses/payment.json")

    assert step.body is None
    assert step.body_file == "responses/payment.json"


def test_response_step_rejects_empty_inline_body_with_body_file() -> None:
    with pytest.raises(ValueError, match="body and body_file"):
        ResponseStep(status=200, body="", body_file="responses/payment.json")


def test_route_defaults_use_independent_dictionaries() -> None:
    first_route = Route(
        id="first", method="GET", path="/users", steps=[ResponseStep(status=200)]
    )
    second_route = Route(
        id="second", method="GET", path="/users", steps=[ResponseStep(status=200)]
    )

    assert first_route.match.headers == second_route.match.headers == {}
    assert first_route.match.query == second_route.match.query == {}
    assert first_route.match.headers is not second_route.match.headers
    assert first_route.match.query is not second_route.match.query
    assert first_route.steps[0].headers is not second_route.steps[0].headers
