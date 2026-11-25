"""Fictional demo policy. Eligibility is never a payment authorization."""
from datetime import date


POLICIES = [
    {"id": "P-REFUND", "title": "Monthly refund review", "version": "demo-v1",
     "text": "Synthetic demo policy: monthly refund requests made 0 to 7 calendar days after the charge, inclusive, with usage_count at most 10, are eligible for human review. Requests beyond either limit are not eligible under this demo policy."},
    {"id": "P-MANUAL", "title": "Special cases", "version": "demo-v1",
     "text": "Synthetic demo policy: annual-plan refunds, duplicate-charge requests and cancellation requests require manual review. The application does not cancel accounts or determine special-case outcomes."},
    {"id": "P-INFO", "title": "Missing information", "version": "demo-v1",
     "text": "Synthetic demo policy: identify the request reason first. Monthly refunds require the plan, charge date, request date and usage count. Ask for missing facts before assessing eligibility; never invent them."},
    {"id": "P-REVIEW", "title": "Human review required", "version": "demo-v1",
     "text": "Synthetic demo policy: all drafts and eligibility assessments need human review. Approval only records the reviewed text locally. No message is sent, no account is changed and no refund is processed."},
]


def assess(facts: dict) -> dict:
    facts = dict(facts)
    charged = date.fromisoformat(facts["charged_on"]) if facts.get("charged_on") else None
    requested = date.fromisoformat(facts["requested_on"]) if facts.get("requested_on") else None
    if charged and requested and charged > requested:
        raise ValueError("Charge date cannot be after the request date.")

    def result(decision, reason, rule, missing=None):
        return {"decision": decision, "reason": reason, "missing_fields": missing or [],
                "citations": [rule, "P-REVIEW"], "facts": facts}

    if not facts.get("reason"):
        return result("needs_information", "Confirm the request reason before choosing a policy.", "P-INFO", ["reason"])
    if facts["reason"] in {"duplicate_charge", "cancel"} or facts.get("plan") == "annual":
        return result("manual_review", "This special case requires manual review; no account or payment action is authorized.", "P-MANUAL")
    missing = [key for key in ("plan", "charged_on", "requested_on", "usage_count") if facts.get(key) is None]
    if missing:
        return result("needs_information", "Confirm the missing facts before assessing this refund request.", "P-INFO", missing)
    elapsed = (requested - charged).days
    usage = facts["usage_count"]
    if elapsed <= 7 and usage <= 10:
        return result("eligible_review", f"Request is {elapsed} calendar days after the charge with {usage} uses, within both demo limits. A human must review it.", "P-REFUND")
    exceeded = []
    if elapsed > 7:
        exceeded.append(f"{elapsed} calendar days exceeds the 7-day window")
    if usage > 10:
        exceeded.append(f"{usage} uses exceeds the 10-use limit")
    return result("not_eligible", "; ".join(exceeded) + ". Not eligible under the demo policy; human review is still required.", "P-REFUND")
