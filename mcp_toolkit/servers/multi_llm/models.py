"""Data models for the Multi-LLM MCP server."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class ProviderName(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    XAI = "xai"


@dataclass
class LLMResponse:
    provider: ProviderName
    model: str
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker: 3 failures → 60s cooldown → auto-reset."""

    failure_threshold: int = 3
    cooldown_seconds: int = 60
    _failures: int = field(default=0, init=False, repr=False)
    _open_until: float = field(default=0.0, init=False, repr=False)

    def is_open(self) -> bool:
        """Return True if the circuit is open (provider should not be called)."""
        now = time.monotonic()
        if self._open_until > 0:
            if now < self._open_until:
                return True
            # Cooldown expired — auto-reset
            self._failures = 0
            self._open_until = 0.0
        return False

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._open_until = time.monotonic() + self.cooldown_seconds

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0
