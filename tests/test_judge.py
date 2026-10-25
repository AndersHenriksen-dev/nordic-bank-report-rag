"""Tests for the LLM judge: the request it sends and how it reads the verdict.

No API call is made: the SDK's HTTP transport is replaced by one that records the request and returns a canned reply.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2
import pytest

from bankrag import judge as judge_module
from bankrag.models import Question, Verdict

QUESTION = Question(
    id="q99",
    question="Why did Jyske Bank's net interest income fall in 2024?",
    lang="en",
    category="why",
    answerable=True,
    gold_answer="It fell 3% because Danmarks Nationalbank cut its deposit rate.",
)


def fake_client(reply: dict[str, Any], requests: list[dict[str, Any]]) -> anthropic.Anthropic:
    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=reply)

    transport = httpx2.MockTransport(handle)
    return anthropic.Anthropic(api_key="test", http_client=anthropic.DefaultHttpxClient(transport=transport))


def reply(text: str | None, stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [] if text is None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0},
    }


class TestJudge:
    def run(self, monkeypatch: pytest.MonkeyPatch, text: str) -> tuple[Verdict, float, dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        client = fake_client(reply(text), requests)
        monkeypatch.setattr(judge_module, "api_client", lambda: client)
        verdict, cost = judge_module.judge(QUESTION, "Net interest income fell 3% [1].")
        return verdict, cost, requests[0]

    def test_reads_the_verdict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = '{"reason": "Names the rate cut.", "correct": true, "complete": true, "consistent": true}'
        verdict, cost, _ = self.run(monkeypatch, text)
        assert verdict.passed
        assert verdict.reason == "Names the rate cut."
        assert cost == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)

    def test_one_failed_criterion_fails_the_answer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = '{"reason": "Misses the driver.", "correct": true, "complete": false, "consistent": true}'
        verdict, _, _ = self.run(monkeypatch, text)
        assert not verdict.passed

    def test_sends_the_rubric_and_a_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = '{"reason": "ok", "correct": true, "complete": true, "consistent": true}'
        _, _, request = self.run(monkeypatch, text)
        assert request["system"][0]["text"] == judge_module.RUBRIC_FILE.read_text(encoding="utf-8")
        assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
        schema = request["output_config"]["format"]["schema"]
        assert set(schema["required"]) == {"reason", "correct", "complete", "consistent"}
        assert request["output_config"]["effort"] == "medium"
        assert QUESTION.gold_answer in request["messages"][0]["content"]

    @pytest.mark.parametrize(
        ("text", "stop_reason"),
        [(None, "refusal"), ('{"reason": "Cut off", "correct": tr', "max_tokens")],
    )
    def test_no_verdict_raises(self, monkeypatch: pytest.MonkeyPatch, text: str | None, stop_reason: str) -> None:
        requests: list[dict[str, Any]] = []
        client = fake_client(reply(text, stop_reason), requests)
        monkeypatch.setattr(judge_module, "api_client", lambda: client)
        with pytest.raises(RuntimeError, match="q99"):
            judge_module.judge(QUESTION, "An answer.")
