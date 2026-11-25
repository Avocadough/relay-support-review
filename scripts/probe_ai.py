"""Run the three example tickets through the template and the local model."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from relay.drafting import DraftUnavailable, generate_draft
from relay.policy import assess


# Use the same inputs as the published run so its replies can be compared.
def main():
    example = ROOT / "examples" / "model-probe.json"
    recorded_cases = json.loads(example.read_text(encoding="utf-8"))["cases"]
    started = datetime.now(timezone.utc)
    results = []
    for recorded in recorded_cases:
        ticket = recorded["case"]
        assessment = assess(ticket["facts"])
        result = {
            "case": ticket,
            "assessment": assessment,
            "template": generate_draft(ticket, assessment, "template"),
        }
        try:
            result["ai"] = generate_draft(ticket, assessment, "ai")
            result["transport_and_shape"] = "passed"
        except DraftUnavailable as error:
            result["transport_and_shape"] = "rejected"
            result["error"] = str(error)
        results.append(result)

    run = {
        "created_at": started.isoformat(),
        "kind": "development_probe_not_holdout",
        "cases": results,
    }
    report = json.dumps(run, indent=2, ensure_ascii=False)
    output = ROOT / "artifacts" / f"ai_probe_{started:%Y%m%dT%H%M%S%fZ}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(report + "\n", encoding="utf-8")
    print(output)
    print(report)


if __name__ == "__main__":
    main()
