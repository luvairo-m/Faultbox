"""Configuration models for a Faultbox scenario."""

from dataclasses import dataclass, field
from typing import Literal


DEFAULT_DELAY_MS = 0
DEFAULT_REPEAT = 1

HttpMethod = Literal["GET", "POST"]
SUPPORTED_METHODS: tuple[HttpMethod, ...] = ("GET", "POST")


@dataclass
class RouteMatch:
    headers: dict[str, str] = field(default_factory=dict)
    query: dict[str, str] = field(default_factory=dict)


@dataclass
class ResponseStep:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    body_file: str | None = None
    delay_ms: int = DEFAULT_DELAY_MS
    repeat: int = DEFAULT_REPEAT

    def __post_init__(self) -> None:
        if self.body is not None and self.body_file is not None:
            raise ValueError("body and body_file cannot be set together")

        if self.body is None and self.body_file is None:
            self.body = ""


@dataclass
class Route:
    id: str
    method: HttpMethod
    path: str
    steps: list[ResponseStep]
    match: RouteMatch = field(default_factory=RouteMatch)


@dataclass
class Scenario:
    routes: list[Route]
