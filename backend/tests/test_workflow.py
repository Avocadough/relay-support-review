"""Workflow tests use real SQLite; only the slow model boundary is replaced."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient


def application(db):
    from relay.app import create_app
    return create_app(db)


@pytest.fixture
def client(tmp_path):
    with TestClient(application(tmp_path / "test.sqlite3"), base_url="http://127.0.0.1:8011") as connection:
        yield connection


def ticket_payload(**facts):
    return {
        "customer": "Synthetic Customer",
        "title": "Refund after trying the monthly plan",
        "body": "I tried the plan but no longer need it. Please review my request.",
        "facts": {
            "plan": "monthly", "charged_on": "2025-05-01",
            "requested_on": "2025-05-08", "usage_count": 10,
            "reason": "refund", **facts,
        },
    }


def create(client, **facts):
    response = client.post("/api/tickets", json=ticket_payload(**facts))
    assert response.status_code == 201, response.text
    return response.json()


def draft(client, ticket):
    response = client.post(f"/api/tickets/{ticket['id']}/drafts", json={
        "mode": "template", "expected_revision": ticket["revision"],
    })
    assert response.status_code == 200, response.text
    return response.json()


def review_payload(ticket, action="approve"):
    return {
        "draft_id": ticket["drafts"][0]["id"],
        "expected_revision": ticket["revision"], "action": action,
        "body": "I reviewed the request. A human will decide the next step.",
        "note": "Checked the entered dates and usage against the demo policy.",
        "reviewer": "Demo operator",
    }


@pytest.mark.parametrize("facts,decision,rule", [
    ({}, "eligible_review", "P-REFUND"),
    ({"requested_on": "2025-05-09"}, "not_eligible", "P-REFUND"),
    ({"usage_count": 11}, "not_eligible", "P-REFUND"),
    ({"requested_on": "2025-05-01", "usage_count": 0}, "eligible_review", "P-REFUND"),
    ({"plan": "annual"}, "manual_review", "P-MANUAL"),
    ({"reason": "duplicate_charge"}, "manual_review", "P-MANUAL"),
    ({"reason": "cancel"}, "manual_review", "P-MANUAL"),
    ({"usage_count": None}, "needs_information", "P-INFO"),
])
def test_policy_boundaries_are_assessed_by_server(client, facts, decision, rule):
    assessment = create(client, **facts)["assessment"]
    assert assessment["decision"] == decision
    assert {rule, "P-REVIEW"} <= set(assessment["citations"])
    if decision == "needs_information":
        assert assessment["missing_fields"] == ["usage_count"]


@pytest.mark.parametrize("change", [
    {"usage_count": -1}, {"usage_count": True}, {"usage_count": 1.5},
    {"charged_on": "2025-05-09"}, {"charged_on": "not-a-date"},
    {"requested_on": "2025-05-08T00:00:00Z"},
    {"requested_on": "2025-04-30"},
    {"decision": "eligible_review"},
])
def test_invalid_facts_do_not_create_tickets(client, change):
    before = client.get("/api/stats").json()
    response = client.post("/api/tickets", json=ticket_payload(**change))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert client.get("/api/stats").json() == before


def test_bounds_and_unexpected_fields_are_rejected(client):
    for field, value in [("customer", "  "), ("title", "x" * 161), ("body", "x" * 4001),
                         ("status", "approved")]:
        payload = ticket_payload()
        payload[field] = value
        assert client.post("/api/tickets", json=payload).status_code == 422


def test_seed_once_and_created_ticket_survives_new_app(tmp_path):
    db = tmp_path / "persistent.sqlite3"
    with TestClient(application(db), base_url="http://127.0.0.1:8011") as first:
        seed = first.get("/api/tickets").json()
        assert len(seed) == 6
        assert {x["assessment"]["decision"] for x in seed} == {
            "eligible_review", "not_eligible", "manual_review", "needs_information",
        }
        created = create(first)
    with TestClient(application(db), base_url="http://127.0.0.1:8011") as second:
        assert len(second.get("/api/tickets").json()) == 7
        detail = second.get(f"/api/tickets/{created['id']}").json()
        assert detail == created
        assert second.get("/api/health").json()["status"] == "ok"


def test_approval_keeps_original_and_edited_body_and_persistent_history(client):
    ticket = create(client)
    assert ticket["status"] == "open" and ticket["drafts"] == []
    drafted = draft(client, ticket)
    assert drafted["status"] == "draft"
    assert drafted["revision"] == ticket["revision"] + 1
    original = drafted["drafts"][0]["body"]
    assert drafted["drafts"][0]["model"] is None
    assert drafted["drafts"][0]["review"] is None
    payload = review_payload(drafted)
    response = client.post(f"/api/tickets/{ticket['id']}/review", json=payload)
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved"
    assert approved["revision"] == drafted["revision"] + 1
    assert approved["drafts"][0]["original_body"] == original
    assert approved["drafts"][0]["body"] == payload["body"]
    assert approved["drafts"][0]["review"]["note"] == payload["note"]
    assert len(approved["events"]) == 3
    assert client.get(f"/api/tickets/{ticket['id']}").json() == approved
    stats = client.get("/api/stats").json()
    assert stats["approved"] == stats["reviews"] == stats["template_drafts"] == 1
    assert stats["ai_drafts"] == 0
    assert client.post(f"/api/tickets/{ticket['id']}/review", json=payload).status_code == 409
    assert client.post(f"/api/tickets/{ticket['id']}/drafts", json={
        "mode": "template", "expected_revision": approved["revision"],
    }).status_code == 409


def test_only_latest_pending_draft_can_be_reviewed_and_reject_reopens(client):
    first = draft(client, create(client))
    second = draft(client, first)
    stale_draft = review_payload(first)
    stale_draft["expected_revision"] = second["revision"]
    path = f"/api/tickets/{second['id']}/review"
    assert client.post(path, json=stale_draft).status_code == 409
    rejected = client.post(path, json=review_payload(second, "reject")).json()
    assert rejected["status"] == "open"
    assert rejected["drafts"][0]["review"]["action"] == "reject"
    retry_review = review_payload(rejected)
    assert client.post(path, json=retry_review).status_code == 409
    assert draft(client, rejected)["status"] == "draft"


def test_review_validation_cannot_change_state(client):
    ticket = draft(client, create(client))
    for field, value in [("note", "  "), ("body", ""), ("reviewer", ""),
                         ("expected_revision", True), ("override_decision", "eligible_review")]:
        payload = review_payload(ticket)
        payload[field] = value
        response = client.post(f"/api/tickets/{ticket['id']}/review", json=payload)
        assert response.status_code == 422
    assert client.get(f"/api/tickets/{ticket['id']}").json() == ticket


def test_model_failure_leaves_no_phantom_draft_or_revision(client, monkeypatch):
    import relay.app as routes
    from relay.drafting import DraftUnavailable

    def unavailable(*args, **kwargs):
        raise DraftUnavailable("Local model is unavailable.")

    monkeypatch.setattr(routes, "generate_draft", unavailable)
    ticket = create(client)
    response = client.post(f"/api/tickets/{ticket['id']}/drafts", json={
        "mode": "ai", "expected_revision": ticket["revision"],
    })
    assert response.status_code == 503
    assert client.get(f"/api/tickets/{ticket['id']}").json() == ticket


def test_generation_rechecks_revision_after_model_returns(client, monkeypatch):
    import relay.app as routes
    real_generate = routes.generate_draft
    entered, finish = Event(), Event()

    def slow_generate(ticket, assessment, mode):
        if mode == "ai":
            entered.set()
            assert finish.wait(5)
        return real_generate(ticket, assessment, "template")

    monkeypatch.setattr(routes, "generate_draft", slow_generate)
    ticket = create(client)
    path = f"/api/tickets/{ticket['id']}/drafts"
    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(client.post, path, json={"mode": "ai", "expected_revision": ticket["revision"]})
        assert entered.wait(5)
        newer = draft(client, ticket)
        finish.set()
        assert waiting.result().status_code == 409
    assert client.get(f"/api/tickets/{ticket['id']}").json() == newer


def test_simultaneous_reviews_commit_exactly_once(client):
    ticket = draft(client, create(client))
    payload = review_payload(ticket)
    gate = Barrier(2)

    def submit():
        gate.wait()
        return client.post(f"/api/tickets/{ticket['id']}/review", json=deepcopy(payload))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert client.get("/api/stats").json()["reviews"] == 1
    detail = client.get(f"/api/tickets/{ticket['id']}").json()
    assert detail["revision"] == ticket["revision"] + 1
    assert len(detail["events"]) == 3


def test_cross_origin_mutations_and_large_payloads_are_rejected(client):
    for origin in ["https://evil.example", "null", "http://localhost:8011.evil.example"]:
        response = client.post("/api/tickets", json=ticket_payload(), headers={"Origin": origin})
        assert response.status_code == 403
    response = client.post("/api/tickets", content="x" * 20001,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert client.post("/api/tickets", json=ticket_payload(),
                       headers={"Origin": "http://127.0.0.1:8011"}).status_code == 201


def test_unknown_ticket_and_policy_contract(client):
    assert client.get("/api/tickets/no-such-ticket").status_code == 404
    policies = client.get("/api/policies").json()
    assert {p["id"] for p in policies} == {"P-REFUND", "P-MANUAL", "P-INFO", "P-REVIEW"}
    assert all(p["version"] == "demo-v1" for p in policies)


def test_unexpected_host_cannot_read_local_ticket_data(client):
    response = client.get("/api/tickets", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_chunked_payload_limit_is_enforced_without_content_length(client):
    def chunks():
        yield b"{" + b" " * 10_000
        yield b" " * 10_000 + b"}"

    response = client.post("/api/tickets", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_review_survives_restart_and_stats_are_consistent(tmp_path):
    db = tmp_path / "review.sqlite3"
    with TestClient(application(db), base_url="http://127.0.0.1:8011") as first:
        ticket = draft(first, create(first))
        approved = first.post(f"/api/tickets/{ticket['id']}/review", json=review_payload(ticket)).json()
        before = first.get("/api/stats").json()
    with TestClient(application(db), base_url="http://127.0.0.1:8011") as second:
        assert second.get(f"/api/tickets/{ticket['id']}").json() == approved
        assert second.get("/api/stats").json() == before


def test_missing_reason_is_requested_without_inventing_facts(client):
    payload = ticket_payload()
    payload["facts"] = {}
    detail = client.post("/api/tickets", json=payload).json()
    assert detail["assessment"]["decision"] == "needs_information"
    assert detail["assessment"]["missing_fields"] == ["reason"]
    assert all(value is None for value in detail["facts"].values())


def test_manual_cancellation_does_not_require_unrelated_refund_facts(client):
    payload = ticket_payload()
    payload["facts"] = {"reason": "cancel"}
    detail = client.post("/api/tickets", json=payload).json()
    assert detail["assessment"]["decision"] == "manual_review"
    assert detail["assessment"]["missing_fields"] == []
