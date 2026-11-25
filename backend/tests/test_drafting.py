import json
from unittest.mock import patch

import httpx
import pytest

from relay.drafting import DraftUnavailable, generate_draft


TICKET = {"customer": "Demo Alex", "title": "Please cancel", "body": "Please review my monthly payment.", "facts": {}}
ASSESSMENT = {"decision": "eligible_review", "reason": "Monthly plan, 2 days, 4 usage units.", "missing_fields": [], "citations": ["P-REFUND", "P-REVIEW"], "facts": {"plan": "monthly", "usage_count": 4}}


def response(body, citations=None):
    return httpx.Response(200, json={"message": {"content": json.dumps({"body": body, "citations": citations or ["P-REFUND", "P-REVIEW"]})}}, request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"))


def test_template_never_calls_model_or_claims_payment_happened():
    with patch("httpx.post", side_effect=AssertionError("template must stay offline")):
        draft = generate_draft(TICKET, ASSESSMENT, "template")
    assert draft["mode"] == "template"
    assert draft["model"] is None
    assert "review" in draft["body"].lower()
    assert "processed your refund" not in draft["body"].lower()
    assert draft["citations"] == ["P-REFUND", "P-REVIEW"]


def test_missing_information_template_names_the_missing_facts():
    assessment = {**ASSESSMENT, "decision": "needs_information", "missing_fields": ["charged_on", "usage_count"]}
    draft = generate_draft(TICKET, assessment, "template")
    assert "charge date" in draft["body"].lower()
    assert "usage" in draft["body"].lower()


def test_real_adapter_records_model_and_validates_citations():
    with patch("httpx.post", return_value=response("Thank you. Your request qualifies for a review; no refund has been approved.")) as send:
        draft = generate_draft(TICKET, ASSESSMENT, "ai")
    assert draft["mode"] == "ai"
    assert draft["model"] == "gemma3:1b"
    assert draft["latency_ms"] >= 0
    payload = send.call_args.kwargs["json"]
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert TICKET["body"] not in payload["messages"][0]["content"]
    assert "eligible_review" in payload["messages"][1]["content"]


@pytest.mark.parametrize("bad", [
    httpx.Response(200, json={"message": {"content": "not JSON"}}),
    response("Thanks", ["P-INVENTED"]),
    response("Your refund has been processed."),
    response("Thanks " * 900),
])
def test_invalid_model_output_is_not_silently_replaced_with_a_template(bad):
    with patch("httpx.post", return_value=bad):
        with pytest.raises(DraftUnavailable):
            generate_draft(TICKET, ASSESSMENT, "ai")


def test_timeout_keeps_ai_failure_explicit():
    with patch("httpx.post", side_effect=httpx.ReadTimeout("timeout")):
        with pytest.raises(DraftUnavailable, match="unavailable"):
            generate_draft(TICKET, ASSESSMENT, "ai")


def test_unknown_mode_does_not_start_a_model_call():
    with patch("httpx.post", side_effect=AssertionError("unexpected network")):
        with pytest.raises(ValueError):
            generate_draft(TICKET, ASSESSMENT, "remote")
