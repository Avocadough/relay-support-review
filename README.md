# Relay Support Review

Relay is a local app for reviewing refund and cancellation requests. A reviewer can check the customer's billing details against a policy, edit a draft reply, and approve or reject it. SQLite keeps the original draft, the edited reply, and the reviewer's note. The tickets and policies are fictional. Approvals only update the local record.

## Try a review

1. Open **Refund at the policy boundary**. The customer requested a refund seven days after the charge and used the service ten times. Both values are exactly at the monthly plan's limits. Read **P-REFUND** under **Policy reference**.
2. Select **Use template**, edit a sentence, and enter a reviewer name. Choose **Approve draft**.
3. Open **Activity** and expand the draft. You can compare the original text with your edit and see who approved it. Reload the page to see the saved decision.

A reviewer name is a label entered on the form. If two reviewers submit a decision for the same draft, the first one is saved and the second reviewer is asked to reload. The [workflow tests](backend/tests/test_workflow.py) cover this case.

## Run locally

Use Python 3.12 and Node.js 20.18 or newer. On Windows, run these commands from the repository root.

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.\scripts\start.ps1
~~~

On macOS or Linux, use these commands from the repository root.

~~~sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn relay.app:app --app-dir backend --host 127.0.0.1 --port 8011
~~~

Open [Relay on localhost](http://127.0.0.1:8011). The template works offline after setup. To use **Generate AI draft**, run Ollama locally with the `gemma3:1b` model.

## What the model got wrong

In a [recorded run with three fictional tickets](examples/model-probe.json), one customer asked about a refund two days after subscribing. The model called this a “2-calendar-day timeframe.” The actual policy allows up to **seven** days. The reply cited a valid policy and passed the format check, so the reviewer still had to catch the incorrect number. The file includes the input, rule assessment, template reply, and model reply for each case.

The [policy rules](backend/relay/policy.py) determine eligibility. The [drafting code](backend/relay/drafting.py) supplies the assessment to the model and checks the returned text and policy IDs. To repeat the three examples with Ollama running, use the project's Python environment to run `python scripts/probe_ai.py`.

## Run the tests

The backend tests use temporary databases and a simulated model response. On Windows, use these commands from the repository root.

~~~powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m pytest backend/tests -q
~~~

On macOS or Linux, run `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q`.
