#!/usr/bin/env python3
"""Routing eval runner for mcp-server-toolkit.

Tests routing priority logic and circuit breaker behavior without live API calls.
All providers are stubbed -- no API keys required.

Usage:
    python evals/run_evals.py
    python evals/run_evals.py --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Add repo root to path when running directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_toolkit.servers.multi_llm.models import CircuitBreaker, LLMResponse, ProviderName
from mcp_toolkit.servers.multi_llm.router import BEST_PRIORITY, CHEAP_PRIORITY


@dataclass
class EvalResult:
    case_id: str
    description: str
    passed: bool
    expected: str
    actual: str
    error: str = ""


def _make_provider(default_model: str) -> Any:
    """Return a stub provider with a working circuit breaker."""
    p = MagicMock()
    p.default_model = default_model
    p.circuit_breaker = CircuitBreaker()
    return p


def _make_providers(scenario: str) -> dict[ProviderName, Any]:
    """Build a provider map for the given scenario name."""
    all_providers = {
        ProviderName.GEMINI: _make_provider("gemini-2.5-pro"),
        ProviderName.OPENAI: _make_provider("gpt-5.5"),
        ProviderName.XAI: _make_provider("grok-4.20-0309-non-reasoning"),
    }

    if scenario == "all_providers":
        return all_providers

    if scenario == "openai_only":
        return {ProviderName.OPENAI: all_providers[ProviderName.OPENAI]}

    if scenario == "gemini_only":
        return {ProviderName.GEMINI: all_providers[ProviderName.GEMINI]}

    if scenario == "xai_only":
        return {ProviderName.XAI: all_providers[ProviderName.XAI]}

    if scenario == "gemini_flash_lite_open":
        # Gemini provider is present but flash-lite circuit is "open"
        # Simulate by making flash-lite the first entry fail -- we trip the breaker manually.
        # In CHEAP_PRIORITY: gemini-2.0-flash-lite is first, gemini-2.5-flash is second.
        # We can't open per-model breakers (breakers are per-provider), so we trip the
        # Gemini breaker and add a second Gemini entry with a fresh breaker.
        # Instead, we test the next Gemini model by returning all providers but with
        # the Gemini breaker tripped and then reset for the second entry.
        # NOTE: The current router uses per-provider breakers, not per-model.
        # So "flash-lite circuit open" = "Gemini circuit open" = fallthrough to OpenAI.
        # This case tests that the router skips to the next *provider* in CHEAP_PRIORITY.
        providers = {
            ProviderName.GEMINI: all_providers[ProviderName.GEMINI],
            ProviderName.OPENAI: all_providers[ProviderName.OPENAI],
            ProviderName.XAI: all_providers[ProviderName.XAI],
        }
        # Trip the Gemini breaker
        for _ in range(3):
            providers[ProviderName.GEMINI].circuit_breaker.record_failure()
        return providers

    if scenario == "gemini_all_open":
        providers = {
            ProviderName.GEMINI: all_providers[ProviderName.GEMINI],
            ProviderName.OPENAI: all_providers[ProviderName.OPENAI],
            ProviderName.XAI: all_providers[ProviderName.XAI],
        }
        for _ in range(3):
            providers[ProviderName.GEMINI].circuit_breaker.record_failure()
        return providers

    if scenario == "gemini_and_openai_open":
        providers = {
            ProviderName.GEMINI: all_providers[ProviderName.GEMINI],
            ProviderName.OPENAI: all_providers[ProviderName.OPENAI],
            ProviderName.XAI: all_providers[ProviderName.XAI],
        }
        for _ in range(3):
            providers[ProviderName.GEMINI].circuit_breaker.record_failure()
            providers[ProviderName.OPENAI].circuit_breaker.record_failure()
        return providers

    if scenario == "openai_open":
        providers = {
            ProviderName.GEMINI: all_providers[ProviderName.GEMINI],
            ProviderName.OPENAI: all_providers[ProviderName.OPENAI],
            ProviderName.XAI: all_providers[ProviderName.XAI],
        }
        for _ in range(3):
            providers[ProviderName.OPENAI].circuit_breaker.record_failure()
        return providers

    raise ValueError(f"Unknown scenario: {scenario}")


def _select_route(
    priority_list: list[tuple[ProviderName, str]],
    providers: dict[ProviderName, Any],
) -> tuple[str, str] | None:
    """Apply the router priority logic and return (provider_name, model) or None."""
    for pn, model in priority_list:
        p = providers.get(pn)
        if p is not None and not p.circuit_breaker.is_open():
            return (pn.value, model)
    return None


def run_case(case: dict) -> EvalResult:
    """Run a single eval case and return the result."""
    case_id = case["id"]
    description = case["description"]
    tool = case["tool"]
    scenario = case.get("scenario")

    try:
        if tool == "cache":
            from mcp_toolkit.framework.caching import CacheLayer

            cache = CacheLayer()
            op = case["operation"]

            if op == "set_get":
                key = CacheLayer.make_key("f", ("v",), {})
                asyncio.run(cache.set(key, "hello", ttl=300))
                result = asyncio.run(cache.get(key))
                passed = result == "hello"
                return EvalResult(case_id, description, passed, "hello", str(result))

            elif op == "get_missing":
                key = CacheLayer.make_key("missing", ("x",), {})
                result = asyncio.run(cache.get(key))
                passed = result is None
                return EvalResult(case_id, description, passed, "None", str(result))

            elif op == "ttl_expiry":
                key = CacheLayer.make_key("ttl", ("v",), {})
                asyncio.run(cache.set(key, "temp", ttl=1))
                time.sleep(1.1)
                result = asyncio.run(cache.get(key))
                passed = result is None
                return EvalResult(case_id, description, passed, "None", str(result))

            elif op == "key_determinism":
                k1 = CacheLayer.make_key("f", ("a",), {"b": 1})
                k2 = CacheLayer.make_key("f", ("a",), {"b": 1})
                passed = k1 == k2
                return EvalResult(case_id, description, passed, "same_key", f"k1={k1[:8]} k2={k2[:8]}")

            elif op == "key_uniqueness":
                k1 = CacheLayer.make_key("f", ("a",), {})
                k2 = CacheLayer.make_key("f", ("b",), {})
                passed = k1 != k2
                return EvalResult(case_id, description, passed, "different_keys", f"k1={k1[:8]} k2={k2[:8]}")

            elif op == "clear":
                key = CacheLayer.make_key("clr", ("v",), {})
                asyncio.run(cache.set(key, "data", ttl=300))
                asyncio.run(cache.clear())
                result = asyncio.run(cache.get(key))
                passed = result is None
                return EvalResult(case_id, description, passed, "None", str(result))

            elif op == "overwrite":
                key = CacheLayer.make_key("ow", ("v",), {})
                asyncio.run(cache.set(key, "old", ttl=300))
                asyncio.run(cache.set(key, "new", ttl=300))
                result = asyncio.run(cache.get(key))
                passed = result == "new"
                return EvalResult(case_id, description, passed, "new", str(result))

            return EvalResult(case_id, description, False, "known op", f"unknown op: {op}")

        elif tool == "a2a":
            from mcp_toolkit import EnhancedMCP
            from mcp_toolkit.framework.a2a_adapter import A2AAdapter

            mcp = EnhancedMCP("eval-test")

            @mcp.tool()
            async def answer(question: str) -> str:
                return f"Answer: {question}"

            adapter = A2AAdapter(mcp, base_url="http://eval.local")
            op = case["operation"]

            if op == "valid_tool":
                status = asyncio.run(adapter.handle_task("t1", "answer", {"question": "hi"}))
                passed = status.status == "completed"
                return EvalResult(case_id, description, passed, "completed", status.status)

            elif op == "unknown_tool":
                status = asyncio.run(adapter.handle_task("t2", "nonexistent_tool", {}))
                passed = status.status == "failed"
                return EvalResult(case_id, description, passed, "failed", status.status)

            elif op == "agent_card":
                card = asyncio.run(adapter.get_agent_card())
                passed = isinstance(card, dict) and "skills" in card and len(card["skills"]) >= 1
                return EvalResult(case_id, description, passed, "dict with skills>=1", str(type(card)))

            elif op == "task_status":
                asyncio.run(adapter.handle_task("t3", "answer", {"question": "test"}))
                status = adapter.get_task_status("t3")
                passed = status is not None and status.task_id == "t3"
                return EvalResult(case_id, description, passed, "task_id=t3", str(status.task_id if status else None))

            elif op == "list_tasks":
                asyncio.run(adapter.handle_task("t4", "answer", {"question": "a"}))
                asyncio.run(adapter.handle_task("t5", "answer", {"question": "b"}))
                tasks = adapter.list_tasks()
                passed = len(tasks) >= 2
                return EvalResult(case_id, description, passed, ">=2 tasks", str(len(tasks)))

            return EvalResult(case_id, description, False, "known op", f"unknown op: {op}")

        elif tool == "rate_limiter":
            from mcp_toolkit.framework.rate_limiter import RateLimiter, RateLimitConfig

            op = case["operation"]

            if op == "first_call":
                rl = RateLimiter()
                result = asyncio.run(rl.check("user1", max_calls=10, window=60))
                passed = result is True
                return EvalResult(case_id, description, passed, "True", str(result))

            elif op == "at_limit":
                rl = RateLimiter()
                for _ in range(3):
                    asyncio.run(rl.check("user2", max_calls=3, window=60))
                result = asyncio.run(rl.check("user2", max_calls=3, window=60))
                passed = result is False
                return EvalResult(case_id, description, passed, "False", str(result))

            elif op == "reset":
                rl = RateLimiter()
                for _ in range(3):
                    asyncio.run(rl.check("user3", max_calls=3, window=60))
                asyncio.run(rl.reset("user3"))
                result = asyncio.run(rl.check("user3", max_calls=3, window=60))
                passed = result is True
                return EvalResult(case_id, description, passed, "True", str(result))

            elif op == "get_remaining":
                rl = RateLimiter(default_config=RateLimitConfig(max_calls=5, window_seconds=60))
                asyncio.run(rl.check("user4"))
                asyncio.run(rl.check("user4"))
                remaining = rl.get_remaining("user4")
                passed = remaining == 3
                return EvalResult(case_id, description, passed, "3", str(remaining))

            return EvalResult(case_id, description, False, "known op", f"unknown op: {op}")

        elif tool == "circuit_breaker":
            cb = CircuitBreaker()
            expected_failures = case["expected_open_after_failures"]
            for i in range(expected_failures - 1):
                cb.record_failure()
                if cb.is_open():
                    return EvalResult(
                        case_id=case_id,
                        description=description,
                        passed=False,
                        expected=f"open after {expected_failures} failures",
                        actual=f"opened early after {i + 1} failures",
                    )
            cb.record_failure()  # final failure
            if cb.is_open():
                return EvalResult(
                    case_id=case_id,
                    description=description,
                    passed=True,
                    expected=f"open after {expected_failures} failures",
                    actual=f"open after {expected_failures} failures",
                )
            return EvalResult(
                case_id=case_id,
                description=description,
                passed=False,
                expected=f"open after {expected_failures} failures",
                actual="still closed",
            )

        # Routing cases
        providers = _make_providers(scenario)
        priority_list = CHEAP_PRIORITY if tool == "query_cheap" else BEST_PRIORITY
        result = _select_route(priority_list, providers)

        expected_provider = case["expected_provider"]
        expected_model = case["expected_model"]
        expected_str = f"{expected_provider}/{expected_model}"

        if result is None:
            return EvalResult(
                case_id=case_id,
                description=description,
                passed=False,
                expected=expected_str,
                actual="no route selected (None)",
            )

        actual_provider, actual_model = result
        actual_str = f"{actual_provider}/{actual_model}"
        passed = actual_provider == expected_provider and actual_model == expected_model

        return EvalResult(
            case_id=case_id,
            description=description,
            passed=passed,
            expected=expected_str,
            actual=actual_str,
        )

    except Exception as e:
        return EvalResult(
            case_id=case_id,
            description=description,
            passed=False,
            expected=case.get("expected_provider", "?") + "/" + case.get("expected_model", "?"),
            actual="",
            error=str(e),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run routing evals for mcp-server-toolkit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all cases, not just failures")
    args = parser.parse_args()

    golden_path = Path(__file__).parent / "golden_set.jsonl"
    cases = [json.loads(line) for line in golden_path.read_text().splitlines() if line.strip()]

    results: list[EvalResult] = []
    start = time.monotonic()
    for case in cases:
        results.append(run_case(case))
    elapsed_ms = (time.monotonic() - start) * 1000

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    pass_rate = passed / total * 100

    print(f"\nmcp-server-toolkit routing evals -- {passed}/{total} passed ({pass_rate:.0f}%)")
    print(f"Elapsed: {elapsed_ms:.1f}ms\n")

    for r in results:
        if args.verbose or not r.passed:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.case_id}: {r.description}")
            if not r.passed:
                print(f"         expected: {r.expected}")
                print(f"         actual:   {r.actual}")
                if r.error:
                    print(f"         error:    {r.error}")

    print()
    if passed < total:
        print(f"FAILED: {total - passed} cases did not match expected routing.")
        return 1

    print("All evals passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
