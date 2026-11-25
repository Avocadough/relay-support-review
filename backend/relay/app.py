"""Loopback-only API for the synthetic Relay review workflow."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .drafting import DraftUnavailable, generate_draft
from .models import DraftInput, ReviewInput, TicketInput
from .policy import POLICIES
from .store import Conflict, MissingTicket, Store


ROOT = Path(__file__).resolve().parents[2]
ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1", "[::1]") for port in (8011, 5174)}
HOSTS = {origin.removeprefix("http://") for origin in ORIGINS} | {"localhost", "127.0.0.1", "[::1]"}


class RequestBoundary:
    """Reject unexpected hosts/origins; read at most 16 KiB for mutations."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        if headers.get(b"host", b"").decode("latin-1") not in HOSTS:
            return await JSONResponse({"detail": "Unexpected request host."}, status_code=400)(scope, receive, send)
        if scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        origin = headers.get(b"origin")
        if origin is not None and origin.decode("latin-1") not in ORIGINS:
            return await JSONResponse({"detail": "Unexpected request origin."}, status_code=403)(scope, receive, send)
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid content length."}, status_code=400)(scope, receive, send)
        if length > 16_384:
            return await JSONResponse({"detail": "Request body is too large."}, status_code=413)(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 16_384:
                return await JSONResponse({"detail": "Request body is too large."}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(db_path=None):
    store = Store(db_path or os.environ.get("RELAY_DB") or ROOT / "data" / "relay.sqlite3")

    @asynccontextmanager
    async def lifespan(application):
        store.initialize()
        yield

    application = FastAPI(title="Relay — synthetic local review", lifespan=lifespan)
    application.add_middleware(RequestBoundary)

    @application.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError):
        details = []
        for issue in error.errors():
            field = ".".join(str(part) for part in issue["loc"] if part != "body") or "request"
            details.append(f"{field}: {issue['msg']}")
        return JSONResponse({"detail": "; ".join(details)}, status_code=422)

    @application.exception_handler(MissingTicket)
    async def missing(request: Request, error: MissingTicket):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @application.exception_handler(Conflict)
    async def conflict(request: Request, error: Conflict):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @application.exception_handler(DraftUnavailable)
    async def unavailable(request: Request, error: DraftUnavailable):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @application.get("/api/health")
    def health():
        return {"status": "ok", "synthetic": True, "local_only": True, "policy_version": "demo-v1"}

    @application.get("/api/policies")
    def policies():
        return POLICIES

    @application.get("/api/tickets")
    def tickets():
        return store.list_tickets()

    @application.post("/api/tickets", status_code=201)
    def new_ticket(payload: TicketInput):
        return store.create(payload.model_dump(mode="json"))

    @application.get("/api/tickets/{ticket_id}")
    def detail(ticket_id: str):
        return store.detail(ticket_id)

    @application.post("/api/tickets/{ticket_id}/drafts")
    def draft(ticket_id: str, payload: DraftInput):
        ticket = store.draft_snapshot(ticket_id, payload.expected_revision)
        generated = generate_draft(ticket, ticket["assessment"], payload.mode)
        return store.save_draft(ticket_id, payload.expected_revision, generated)

    @application.post("/api/tickets/{ticket_id}/review")
    def review(ticket_id: str, payload: ReviewInput):
        return store.review(ticket_id, payload.model_dump())

    @application.get("/api/stats")
    def stats():
        return store.stats()

    built_ui = ROOT / "frontend" / "dist"
    if built_ui.is_dir():
        application.mount("/", StaticFiles(directory=built_ui, html=True), name="ui")
    return application


app = create_app()
