"""Quality eval task definitions for mcp-server-toolkit.

Each task is a (sample_id, task_description, input_kwargs, reference_answer)
tuple. Tasks are grouped by server/capability:

  - multi_llm: routing priority logic (deterministic, no live calls)
  - multi_llm_quality: response quality via LLM-as-judge (live API optional)
  - costing: CostTracker accuracy
  - auth: JWTAuth correctness
  - caching: CacheLayer semantics

Tasks that require live API calls are gated behind EVAL_LIVE_API=1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Coroutine


@dataclass
class EvalTask:
    id: str
    description: str
    category: str
    fn: Callable[[], Coroutine[Any, Any, str]]
    reference: str
    requires_api: bool = False


# ── Multi-LLM routing (deterministic) ────────────────────────────────────────

async def _routing_cheap_selects_cheapest() -> str:
    from unittest.mock import MagicMock
    from mcp_toolkit.servers.multi_llm.models import CircuitBreaker, ProviderName
    from mcp_toolkit.servers.multi_llm.router import CHEAP_PRIORITY

    providers = {
        ProviderName.GEMINI: MagicMock(circuit_breaker=CircuitBreaker()),
        ProviderName.OPENAI: MagicMock(circuit_breaker=CircuitBreaker()),
        ProviderName.XAI: MagicMock(circuit_breaker=CircuitBreaker()),
    }
    # CHEAP_PRIORITY is a flat list of (ProviderName, model_string) tuples
    for provider_name, model in CHEAP_PRIORITY:
        p = providers.get(provider_name)
        if p and not p.circuit_breaker.is_open():
            return f"{provider_name.value}/{model}"
    return "none"


async def _routing_best_selects_gpt() -> str:
    from unittest.mock import MagicMock
    from mcp_toolkit.servers.multi_llm.models import CircuitBreaker, ProviderName
    from mcp_toolkit.servers.multi_llm.router import BEST_PRIORITY

    providers = {
        ProviderName.GEMINI: MagicMock(circuit_breaker=CircuitBreaker()),
        ProviderName.OPENAI: MagicMock(circuit_breaker=CircuitBreaker()),
        ProviderName.XAI: MagicMock(circuit_breaker=CircuitBreaker()),
    }
    # BEST_PRIORITY is a flat list of (ProviderName, model_string) tuples
    for provider_name, model in BEST_PRIORITY:
        p = providers.get(provider_name)
        if p and not p.circuit_breaker.is_open():
            return f"{provider_name.value}/{model}"
    return "none"


async def _circuit_breaker_trips_at_threshold() -> str:
    from mcp_toolkit.servers.multi_llm.models import CircuitBreaker
    cb = CircuitBreaker(failure_threshold=3)
    for _ in range(3):
        cb.record_failure()
    return "open" if cb.is_open() else "closed"


# ── CostTracker accuracy ──────────────────────────────────────────────────────

async def _cost_1m_gpt55_input() -> str:
    from mcp_toolkit.framework.costing import CostTracker
    cost = CostTracker._compute_cost("openai", "gpt-5.5", 1_000_000, 0)
    return f"{cost:.2f}"


async def _cost_haiku_cheaper_than_sonnet() -> str:
    from mcp_toolkit.framework.costing import CostTracker
    haiku = CostTracker._compute_cost("anthropic", "claude-haiku-4-5-20251001", 100_000, 10_000)
    sonnet = CostTracker._compute_cost("anthropic", "claude-sonnet-4-6", 100_000, 10_000)
    return "haiku_cheaper" if haiku < sonnet else "sonnet_cheaper"


# ── Auth correctness ──────────────────────────────────────────────────────────

async def _jwt_valid_hs256() -> str:
    import jwt as pyjwt
    import time
    from mcp_toolkit.framework.auth import JWTAuth
    token = pyjwt.encode({"sub": "u1", "scope": "read", "exp": time.time() + 3600}, "eval-secret-long-enough-32ch", algorithm="HS256")
    auth = JWTAuth(secret="eval-secret-long-enough-32ch")
    result = await auth.authenticate(token)
    return "authenticated" if result.authenticated else f"rejected: {result.error}"


async def _jwt_expired_rejected() -> str:
    import jwt as pyjwt
    import time
    from mcp_toolkit.framework.auth import JWTAuth
    token = pyjwt.encode({"sub": "u1", "scope": "read", "exp": time.time() - 120}, "eval-secret-long-enough-32ch", algorithm="HS256")
    auth = JWTAuth(secret="eval-secret-long-enough-32ch")
    result = await auth.authenticate(token)
    return "rejected" if not result.authenticated else "authenticated"


async def _jwt_wrong_secret_rejected() -> str:
    import jwt as pyjwt
    import time
    from mcp_toolkit.framework.auth import JWTAuth
    token = pyjwt.encode({"sub": "u1", "scope": "read", "exp": time.time() + 3600}, "wrong-secret", algorithm="HS256")
    auth = JWTAuth(secret="eval-secret-long-enough-32ch")
    result = await auth.authenticate(token)
    return "rejected" if not result.authenticated else "authenticated"


# ── Cache semantics ───────────────────────────────────────────────────────────

async def _cache_hit_returns_stored() -> str:
    from mcp_toolkit.framework.caching import CacheLayer, InMemoryCache
    layer = CacheLayer(InMemoryCache())
    layer.initialize()
    await layer.set("k1", "stored_value", ttl=60)
    result = await layer.get("k1")
    return result if result else "miss"


async def _cache_key_deterministic() -> str:
    from mcp_toolkit.framework.caching import CacheLayer
    k1 = CacheLayer.make_key("fn", (1,), {"a": "b"})
    k2 = CacheLayer.make_key("fn", (1,), {"a": "b"})
    return "deterministic" if k1 == k2 else "nondeterministic"


# ── Task registry ─────────────────────────────────────────────────────────────

TASKS: list[EvalTask] = [
    EvalTask(
        id="q-routing-01",
        description="query_cheap selects cheapest available provider",
        category="routing",
        fn=_routing_cheap_selects_cheapest,
        reference="gemini/gemini-2.0-flash-lite",
    ),
    EvalTask(
        id="q-routing-02",
        description="query_best selects highest-quality provider first",
        category="routing",
        fn=_routing_best_selects_gpt,
        reference="openai/gpt-5.5",
    ),
    EvalTask(
        id="q-routing-03",
        description="Circuit breaker opens after 3 failures",
        category="routing",
        fn=_circuit_breaker_trips_at_threshold,
        reference="open",
    ),
    EvalTask(
        id="q-cost-01",
        description="1M input tokens on gpt-5.5 costs $2.00",
        category="costing",
        fn=_cost_1m_gpt55_input,
        reference="2.00",
    ),
    EvalTask(
        id="q-cost-02",
        description="Claude Haiku is cheaper than Claude Sonnet for same workload",
        category="costing",
        fn=_cost_haiku_cheaper_than_sonnet,
        reference="haiku_cheaper",
    ),
    EvalTask(
        id="q-auth-01",
        description="Valid HS256 JWT authenticates successfully",
        category="auth",
        fn=_jwt_valid_hs256,
        reference="authenticated",
    ),
    EvalTask(
        id="q-auth-02",
        description="Expired JWT is rejected (> leeway threshold)",
        category="auth",
        fn=_jwt_expired_rejected,
        reference="rejected",
    ),
    EvalTask(
        id="q-auth-03",
        description="JWT signed with wrong secret is rejected",
        category="auth",
        fn=_jwt_wrong_secret_rejected,
        reference="rejected",
    ),
    EvalTask(
        id="q-cache-01",
        description="Cache hit returns stored value",
        category="cache",
        fn=_cache_hit_returns_stored,
        reference="stored_value",
    ),
    EvalTask(
        id="q-cache-02",
        description="Cache key generation is deterministic",
        category="cache",
        fn=_cache_key_deterministic,
        reference="deterministic",
    ),
]
