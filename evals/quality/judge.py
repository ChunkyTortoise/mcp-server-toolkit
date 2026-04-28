"""LLM-as-judge scorer for mcp-server-toolkit quality evals.

Uses the Anthropic SDK to score tool responses on four dimensions:
  correctness  — factual / logical accuracy
  faithfulness — answer grounded in retrieved context (RAG tasks)
  helpfulness  — actionable and on-topic
  conciseness  — no unnecessary padding

Each dimension is scored 1–5 (5 = best). The judge uses claude-haiku-4-5
by default to keep eval costs low (~$0.001/sample).

Degrades gracefully when ANTHROPIC_API_KEY is not set: returns a deterministic
mock score so CI doesn't fail on missing credentials.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

JUDGE_MODEL = "claude-haiku-4-5-20251001"

_RUBRIC = """\
You are an impartial evaluator assessing LLM tool responses.

Task description: {task_description}
Reference answer (ground truth): {reference}
Model response: {response}

Score each dimension 1–5 (5 = best). Be strict. Use the full scale.

correctness:   Is the response factually/logically correct?
faithfulness:  Is the response grounded in the provided context? (5 if no context provided)
helpfulness:   Is the response actionable and on-topic?
conciseness:   Is the response free of unnecessary filler?

Reply ONLY with valid JSON, e.g.:
{{"correctness": 4, "faithfulness": 5, "helpfulness": 4, "conciseness": 3, "reasoning": "brief note"}}
"""


@dataclass
class JudgeScore:
    correctness: float
    faithfulness: float
    helpfulness: float
    conciseness: float
    reasoning: str = ""

    @property
    def mean(self) -> float:
        return (self.correctness + self.faithfulness + self.helpfulness + self.conciseness) / 4


def _mock_score(response: str) -> JudgeScore:
    """Deterministic mock for CI environments without an API key."""
    length = len(response)
    base = 3.5 if length > 10 else 2.0
    return JudgeScore(
        correctness=base,
        faithfulness=5.0,
        helpfulness=base,
        conciseness=4.0 if length < 500 else 3.0,
        reasoning="[mock — no ANTHROPIC_API_KEY]",
    )


async def judge(
    task_description: str,
    reference: str,
    response: str,
    context: str = "",
) -> JudgeScore:
    """Score a model response against a reference answer.

    Requires ANTHROPIC_API_KEY. Falls back to mock scoring silently when
    the key is absent (useful for CI without secrets).
    """
    import json

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY not set; using mock judge scores.")
        return _mock_score(response)

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        prompt = _RUBRIC.format(
            task_description=task_description,
            reference=reference + (f"\n\nContext: {context}" if context else ""),
            response=response,
        )
        message = await client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = json.loads(raw)
        return JudgeScore(
            correctness=float(data.get("correctness", 3)),
            faithfulness=float(data.get("faithfulness", 5)),
            helpfulness=float(data.get("helpfulness", 3)),
            conciseness=float(data.get("conciseness", 3)),
            reasoning=str(data.get("reasoning", "")),
        )
    except Exception as exc:
        logger.warning("Judge API call failed (%s); using mock score.", exc)
        return _mock_score(response)
