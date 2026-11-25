"""SQLite workflow, with revision checks inside every write transaction."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .policy import assess


class MissingTicket(Exception):
    pass


class Conflict(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier():
    return uuid4().hex


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self, write=False):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY, customer TEXT NOT NULL, title TEXT NOT NULL,
                body TEXT NOT NULL, facts TEXT NOT NULL, status TEXT NOT NULL,
                revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
                body TEXT NOT NULL, original_body TEXT NOT NULL, citations TEXT NOT NULL,
                mode TEXT NOT NULL, model TEXT, latency_ms REAL NOT NULL, warnings TEXT NOT NULL,
                created_at TEXT NOT NULL, review TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
                kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS drafts_ticket ON drafts(ticket_id)")
            db.execute("CREATE INDEX IF NOT EXISTS events_ticket ON events(ticket_id)")
            if not db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
                if db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0:
                    for payload in seed_tickets():
                        self._insert_ticket(db, payload)
                db.execute("INSERT INTO metadata(key,value) VALUES('seeded','demo-v1')")

    def _insert_ticket(self, db, payload):
        ticket_id, timestamp = identifier(), now()
        db.execute("INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?)", (
            ticket_id, payload["customer"], payload["title"], payload["body"],
            json.dumps(payload["facts"]), "open", 0, timestamp, timestamp,
        ))
        self._event(db, ticket_id, "created", "Synthetic ticket created for local review.", timestamp)
        return ticket_id

    def _event(self, db, ticket_id, kind, message, timestamp):
        db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (identifier(), ticket_id, kind, message, timestamp))

    def _ticket(self, db, ticket_id):
        row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if row is None:
            raise MissingTicket("Ticket not found.")
        ticket = dict(row)
        ticket["facts"] = json.loads(ticket["facts"])
        ticket["assessment"] = assess(ticket["facts"])
        return ticket

    def _check_revision(self, ticket, expected):
        if ticket["revision"] != expected:
            raise Conflict("Ticket changed. Reload it before trying again.")

    def _detail(self, db, ticket_id):
        ticket = self._ticket(db, ticket_id)
        ticket["drafts"] = []
        for row in db.execute("SELECT * FROM drafts WHERE ticket_id=? ORDER BY rowid DESC", (ticket_id,)):
            draft = dict(row)
            draft.pop("ticket_id")
            for key in ("citations", "warnings", "review"):
                draft[key] = json.loads(draft[key]) if draft[key] is not None else None
            ticket["drafts"].append(draft)
        ticket["events"] = [dict(row) for row in db.execute(
            "SELECT id,kind,message,created_at FROM events WHERE ticket_id=? ORDER BY rowid", (ticket_id,))]
        return ticket

    def detail(self, ticket_id):
        with self.connection() as db:
            return self._detail(db, ticket_id)

    def list_tickets(self):
        with self.connection() as db:
            return [self._ticket(db, row["id"]) for row in db.execute("SELECT id FROM tickets ORDER BY rowid DESC").fetchall()]

    def create(self, payload):
        with self.connection(write=True) as db:
            ticket_id = self._insert_ticket(db, payload)
            return self._detail(db, ticket_id)

    def draft_snapshot(self, ticket_id, expected_revision):
        with self.connection() as db:
            ticket = self._ticket(db, ticket_id)
            self._check_revision(ticket, expected_revision)
            if ticket["status"] == "approved":
                raise Conflict("This ticket is already approved. No new draft can be generated.")
            return ticket

    def save_draft(self, ticket_id, expected_revision, draft):
        with self.connection(write=True) as db:
            ticket = self._ticket(db, ticket_id)
            self._check_revision(ticket, expected_revision)
            if ticket["status"] == "approved":
                raise Conflict("This ticket is already approved.")
            timestamp = now()
            db.execute("INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                identifier(), ticket_id, draft["body"], draft["body"], json.dumps(draft["citations"]),
                draft["mode"], draft["model"], draft["latency_ms"], json.dumps(draft["warnings"]), timestamp, None,
            ))
            db.execute("UPDATE tickets SET status='draft', revision=revision+1, updated_at=? WHERE id=?", (timestamp, ticket_id))
            self._event(db, ticket_id, "draft_created", f"{draft['mode'].capitalize()} draft created; human review required.", timestamp)
            return self._detail(db, ticket_id)

    def review(self, ticket_id, payload):
        with self.connection(write=True) as db:
            ticket = self._ticket(db, ticket_id)
            self._check_revision(ticket, payload["expected_revision"])
            latest = db.execute("SELECT * FROM drafts WHERE ticket_id=? ORDER BY rowid DESC LIMIT 1", (ticket_id,)).fetchone()
            if ticket["status"] != "draft" or latest is None or latest["id"] != payload["draft_id"] or latest["review"] is not None:
                raise Conflict("Only the latest pending draft can be reviewed once.")
            timestamp = now()
            review = {key: payload[key] for key in ("action", "body", "note", "reviewer")}
            review["created_at"] = timestamp
            db.execute("UPDATE drafts SET body=?, review=? WHERE id=?", (payload["body"], json.dumps(review), latest["id"]))
            status = "approved" if payload["action"] == "approve" else "open"
            db.execute("UPDATE tickets SET status=?, revision=revision+1, updated_at=? WHERE id=?", (status, timestamp, ticket_id))
            self._event(db, ticket_id, "review_" + payload["action"],
                        f"Draft {payload['action']} recorded by {payload['reviewer']}. Nothing was sent or processed.", timestamp)
            return self._detail(db, ticket_id)

    def stats(self):
        with self.connection() as db:
            result = {"total": 0, "open": 0, "draft": 0, "approved": 0}
            for row in db.execute("SELECT status, COUNT(*) AS count FROM tickets GROUP BY status"):
                result[row["status"]] = row["count"]
                result["total"] += row["count"]
            result["reviews"] = db.execute("SELECT COUNT(*) FROM drafts WHERE review IS NOT NULL").fetchone()[0]
            for mode in ("ai", "template"):
                result[mode + "_drafts"] = db.execute("SELECT COUNT(*) FROM drafts WHERE mode=?", (mode,)).fetchone()[0]
            return result


def seed_tickets():
    common = {"plan": "monthly", "charged_on": "2025-05-01", "requested_on": "2025-05-05", "usage_count": 3, "reason": "refund"}
    rows = [
        ("Avery Chen", "Monthly plan no longer needed", "Synthetic request: our evaluation finished early. Could you review a refund for this month's plan?", {}),
        ("Sam Rivera", "Refund at the policy boundary", "Synthetic request: I used the service ten times and requested review seven days after the charge.", {"requested_on": "2025-05-08", "usage_count": 10}),
        ("Morgan Lee", "Request after an extended trial", "Synthetic request: our team continued testing and has now decided to stop. Please check the entered billing facts.", {"requested_on": "2025-05-09", "usage_count": 11}),
        ("Jordan Park", "Annual plan review", "Synthetic request: we purchased an annual subscription but our project has changed. What information is needed for a review?", {"plan": "annual"}),
        ("Casey Smith", "Cancel the next renewal", "Synthetic request: please help cancel the next renewal. I understand a staff member needs to review the account separately.", {"reason": "cancel"}),
        ("Taylor Brooks", "Refund with incomplete usage facts", "Synthetic request: I would like a refund review but have not confirmed how much the account was used.", {"usage_count": None}),
    ]
    return [{"customer": customer, "title": title, "body": body, "facts": {**common, **facts}}
            for customer, title, body, facts in rows]
