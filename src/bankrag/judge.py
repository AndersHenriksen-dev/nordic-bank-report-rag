"""Grade an answer against its gold answer with Claude as the judge, by the rubric in evals/judge_rubric.md.

The figure checks in `evaluate.py` cannot tell whether a "why" answer names the right drivers, or whether a comparison
with correct figures contradicts itself. The judge reads the question, the gold answer and the system's answer, and
returns a `Verdict` on three criteria through structured output, so the result is always valid JSON.
"""

from __future__ import annotations

from functools import cache

from pydantic import ValidationError

from bankrag.answer import api_client, cost_usd
from bankrag.config import JUDGE_MODEL, ROOT
from bankrag.models import Question, Verdict

RUBRIC_FILE = ROOT / "evals" / "judge_rubric.md"
MAX_OUTPUT_TOKENS = 4096  # thinking counts towards the limit; verdicts use a few hundred tokens


@cache
def _rubric() -> str:
    return RUBRIC_FILE.read_text(encoding="utf-8")


def judge_prompt(question: Question, answer_text: str) -> str:
    """Put the question, the gold answer and the answer to grade into one message."""
    return (
        f"<question>\n{question.question}\n</question>\n\n"
        f"<gold_answer>\n{question.gold_answer}\n</gold_answer>\n\n"
        f"<answer>\n{answer_text}\n</answer>"
    )


def judge(question: Question, answer_text: str) -> tuple[Verdict, float]:
    """Grade one answer. Calls the paid API once.

    Returns:
        The verdict and the cost of the call in USD.

    Raises:
        SystemExit: If no API key is configured.
        RuntimeError: If the judge declined or was cut off, so there is no verdict to record.
    """
    try:
        response = api_client().messages.parse(
            model=JUDGE_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=[{"type": "text", "text": _rubric(), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": judge_prompt(question, answer_text)}],
            output_config={"effort": "low"},
            output_format=Verdict,
        )
    except ValidationError as error:  # output cut off at the token limit is not valid JSON
        raise RuntimeError(f"No verdict for {question.id}: the judge's output is not a complete verdict.") from error
    if response.parsed_output is None:
        raise RuntimeError(f"No verdict for {question.id}: the judge stopped with {response.stop_reason!r}.")
    return response.parsed_output, cost_usd(JUDGE_MODEL, response.usage)
