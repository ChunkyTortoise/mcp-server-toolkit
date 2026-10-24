"""LLM-as-judge scorer for mcp-server-toolkit quality evals.

Uses the Anthropic SDK to score tool responses on four dimensions:
  correctness  - factual / logical accuracy
  faithfulness - answer grounded in retrieved context (RAG tasks)
  helpfulness  - actionable and on-topic
  conciseness  - no unnecessary padding

Each dimension is scored 1-5 (5 = best). The judge uses claude-haiku-4-5
by default to keep eval costs low (~$0.001/sample).

Returns None when ANTHROPIC_API_KEY is not set or the API call fails, so no
placeholder score is ever reported.
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

Score each dimension 1-5 (5 = best). Be strict. Use the full scale.

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


async def judge(
    task_description: str,
    reference: str,
    response: str,
    context: str = "",
) -> JudgeScore | None:
    """Score a model response against a reference answer.

    Requires ANTHROPIC_API_KEY. Returns None (no score) when the key is absent
    or the API call fails.
    """
    import json

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.debug("ANTHROPIC_API_KEY not set; skipping judge.")
        return None

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
        logger.warning("Judge API call failed (%s); no score recorded.", exc)
        return None
