"""Backend for the Couchbase Delivery mobile AI personalization demo.

  /api/*            customer sign-in (mints a Sync Gateway session), assistant,
                    status, and a REST "preview sync" used only by the browser
                    preview build
  /delivery/mcp/   the delivery-orders MCP server AOM governs

Background tasks: the Databricks export loader/poller and the offline-first
order worker.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import logging
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import aom_bootstrap, assistant, config, loader, metrics, personalization, rag_app, sgw, worker
from .aom_client import aom
from .docs import (CATALOG_ID, STATE, chat_id, ctx_id, now_iso, recs_id, customer_channel, customer_id_doc, hub_channel,
                   hub_id_doc)
from .mcp_server import mcp
from .store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("delivery.api")

PERSONA_BLURBS = {
    "S00101001": "Orders on a subway commute with no signal. Coffee pods are nearly sold out, and the stand mixer she keeps viewing is cheaper at a competitor: a price match that needs approval.",
    "S00101002": "Rural drive home with long dead zones. Two dogs: the dog food is backordered and belongs on Subscribe & Save.",
    "S00101003": "Household of five. Wants a second limited-release console (refused by the purchase limit) and a goodwill credit for a damaged delivery.",
}
_bg: list = []
_LAST_PULL: dict[str, str] = {}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await store.connect()

    auto_register = config.AOM_AUTO_REGISTER and bool(config.AOM_ADMIN_PASSWORD)

    async def initial_load():
        try:
            # With self-registration the KB is published once AOM sign-in works.
            await loader.load(kb=not auto_register)
            metrics.export_loaded(loader.STATUS.get("rows", 0))
        except Exception:  # noqa: BLE001
            log.exception("initial export load failed")

    first = asyncio.create_task(initial_load())
    _bg.append(first)
    if auto_register:
        _bg.append(asyncio.create_task(aom_bootstrap.run(first)))
    _bg.append(asyncio.create_task(worker.loop()))
    _bg.append(asyncio.create_task(loader.poll_forever()))
    async with mcp.session_manager.run():
        yield
    for t in _bg:
        t.cancel()


app = FastAPI(title="Couchbase Delivery Mobile AI Personalization Demo", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.mount("/delivery", mcp.streamable_http_app())


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def _sign(payload: str) -> str:
    return hmac.new(config.APP_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_token(customer_id: str) -> str:
    payload = f"{customer_id}|{int(time.time()) + config.APP_TOKEN_TTL_SECONDS}"
    return base64.urlsafe_b64encode(f"{payload}|{_sign(payload)}".encode()).decode()


def current_customer(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first")
    try:
        rid, exp, sig = base64.urlsafe_b64decode(authorization.split(" ", 1)[1].encode()).decode().split("|")
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "Invalid session") from None
    if not hmac.compare_digest(sig, _sign(f"{rid}|{exp}")) or int(exp) < time.time():
        raise HTTPException(401, "Session expired - sign in again")
    return rid


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    """Landing page: where everything in the demo lives."""
    rows = [
        ("http://localhost:8086/story", "The story: delivery that doesn't wait for signal, and a Databricks bill that stops growing per tap (start here)"),
        ("http://localhost:8086", "The app in a browser (docker compose service <code>web</code>)"),
        ("http://localhost:8205/api/status", "Backend status: export load, Knowledge Base publishing, AOM, Sync Gateway, Databricks offload"),
        ("http://localhost:8205/docs", "Backend API (OpenAPI)"),
        ("http://localhost:8205/delivery/mcp", "MCP server <code>delivery-orders</code> (called by AOM)"),
        ("http://localhost:18096", "Couchbase Web Console (Administrator / password123)"),
        ("ws://localhost:4994/delivery", "Sync Gateway - Couchbase Lite replicates here"),
        ("https://localhost:8090", "Couchbase Agent Operations Manager (its own stack)"),
    ]
    items = "".join(f'<li><a href="{u}">{u}</a> &nbsp;{d}</li>' for u, d in rows)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Couchbase Delivery demo backend</title>
<style>body{{font-family:-apple-system,"Helvetica Neue",Arial,sans-serif;max-width:760px;margin:48px auto;padding:0 16px;color:#0b0b0c}}
h1{{color:#ea2328}} li{{margin:10px 0}} a{{color:#ea2328;font-weight:600}}</style></head>
<body><h1>Couchbase Delivery demo</h1>
<p>This is the backend. Open the app at <a href="http://localhost:8086">http://localhost:8086</a>.
Loaded export: <b>{STATE.get("export_date") or "loading..."}</b> ({loader.STATUS.get("state")}).</p>
<ul>{items}</ul></body></html>"""


@app.get("/api/health")
async def health():
    return {"status": "ok", "export_date": STATE.get("export_date"), "load": loader.STATUS.get("state")}


@app.get("/api/status")
async def status():
    aom_state = {"configured": aom.enabled, "url": config.AOM_URL or None, "kb_publisher": aom.admin_enabled,
                 "last_error": aom.last_error, "registration": aom_bootstrap.STATUS, "rag_app": dict(rag_app.STATUS, app_id=config.RAG_APP_ID),
                 "context_namespace": config.CONTEXT_NAMESPACE,
                 "dashboard_url": config.AOM_DASHBOARD_URL or None}
    if aom.enabled:
        try:
            aom_state["health"] = await aom.health()
        except Exception as exc:  # noqa: BLE001
            aom_state["health"] = {"error": str(exc)[:200]}
    return {"store": store.driver, "export_date": STATE.get("export_date"),
            "load": {k: v for k, v in loader.STATUS.items()}, "aom": aom_state, "metrics": metrics.snapshot(),
            "sync_gateway": {"configured": sgw.enabled(), "public_url": config.SG_PUBLIC_URL or None, "db": config.SG_DB},
            "mcp_server": {"server_id": config.AOM_MCP_SERVER_ID, "registered_url": config.AOM_MCP_PUBLIC_URL}}


@app.get("/api/demo/personas")
async def personas():
    out = []
    for sid in loader.PERSONAS:
        sh = await store.get("customers", customer_id_doc(sid))
        if not sh:
            continue
        recs = await store.get("recommendations", recs_id(sid)) or {}
        out.append({"customer_id": sid, "name": f"{sh['first_name']} {sh['last_name']}", "last_name": sh["last_name"],
                    "member_number": sh["member_number"], "city": f"{sh['address']['city']}, {sh['address']['state']}",
                    "tier": sh["membership"]["tier_name"], "smart_cart_items": len([l for l in recs.get("lines", []) if l.get("selected")]),
                    "home_hub": (sh.get("home_hub") or {}).get("name"), "blurb": PERSONA_BLURBS.get(sid, "")})
    return {"personas": out, "export_date": STATE.get("export_date")}


class LoginRequest(BaseModel):
    member_number: str
    last_name: str


def _hub_of(customer: dict) -> str | None:
    return (customer.get("home_hub") or {}).get("hub_id")


async def _session(customer: dict) -> dict:
    sid = customer["customer_id"]
    # Recommendations are pre-built for recently active customers; everyone else gets theirs here.
    if not await store.get("recommendations", recs_id(sid)):
        await personalization.refresh_recommendations(sid)
    return {"token": make_token(sid), "customer_id": sid, "sync_gateway": await sgw.mint_session(sid, _hub_of(customer)),
            "export_date": STATE.get("export_date")}


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    idx = await store.get("lookups", f"login::{req.member_number.strip()}")
    if not idx or req.last_name.strip().lower() != idx.get("last_name"):
        raise HTTPException(401, "We couldn't find that member number and last name.")
    customer = await store.get("customers", customer_id_doc(idx["customer_id"]))
    sid = customer["customer_id"]
    return {**await _session(customer),
            "customer": {"first_name": customer["first_name"], "last_name": customer["last_name"], "email": customer.get("email"),
                        "tier": customer["membership"]["tier"], "tier_name": customer["membership"]["tier_name"],
                        "home_hub": customer.get("home_hub")},
            "channels": [customer_channel(sid), hub_channel(_hub_of(customer) or "-"), "catalog"]}


@app.post("/api/auth/refresh")
async def refresh(customer_id: str = Depends(current_customer)):
    """Re-mint the Sync Gateway session (24h) for a signed-in customer - called
    by the app on launch when it has connectivity."""
    customer = await store.get("customers", customer_id_doc(customer_id))
    if not customer:
        raise HTTPException(401, "Sign in again")
    return await _session(customer)


@app.get("/api/me")
async def me(customer_id: str = Depends(current_customer)):
    return await store.get("customers", customer_id_doc(customer_id))


async def _customer_docs(customer_id: str) -> list[dict]:
    out = []
    customer = await store.get("customers", customer_id_doc(customer_id))
    if not customer:
        return out
    out.append({"collection": "customers", "id": customer_id_doc(customer_id), "doc": customer})
    sid = _hub_of(customer)
    pairs = [("recommendations", recs_id(customer_id)), ("assistant", chat_id(customer_id)), ("catalog", CATALOG_ID)]
    if sid:
        pairs.append(("hubs", hub_id_doc(sid)))
    pairs += [("context_cache", ctx_id(customer_id, key)) for key in assistant.CONTEXT_KEYS]
    for col, key in pairs:
        d = await store.get(col, key)
        if d:
            out.append({"collection": col, "id": key, "doc": d})
    for d in await store.orders_for_customer(customer_id):
        key = d.pop("_id")
        out.append({"collection": "orders", "id": key, "doc": d})
    return out


@app.get("/api/sync/pull")
async def sync_pull(customer_id: str = Depends(current_customer)):
    """Browser-preview stand-in for Sync Gateway: the same documents and ids
    the customer's channels would replicate into Couchbase Lite."""
    docs = await _customer_docs(customer_id)
    # Count only what changed since this customer's last pull, the way a
    # Couchbase Lite replicator only moves changed revisions - a poll that
    # finds nothing new is not a warehouse query avoided.
    fp = hashlib.sha1("|".join(f"{d['id']}:{d['doc'].get('updated_at') or d['doc'].get('generated_at') or d['doc'].get('rev', '')}:{d['doc'].get('status', '')}"
                               for d in docs).encode()).hexdigest()
    if _LAST_PULL.get(customer_id) != fp:
        metrics.sync_pull(len(docs) if customer_id not in _LAST_PULL else max(1, len(docs) // 10))
        _LAST_PULL[customer_id] = fp
    return {"docs": docs, "at": now_iso(), "export_date": STATE.get("export_date")}


class PushDoc(BaseModel):
    collection: str
    id: str
    doc: dict


class PushRequest(BaseModel):
    docs: list[PushDoc] = Field(default_factory=list)


@app.post("/api/sync/push")
async def sync_push(req: PushRequest, customer_id: str = Depends(current_customer)):
    """Browser-preview stand-in for a push replication. Same rule the Sync
    Gateway sync function enforces: a customer may only create `orders`
    documents, only as themselves, only as `pending`."""
    accepted = []
    for d in req.docs:
        if d.collection != "orders" or d.doc.get("customer_id") != customer_id or not d.id.startswith(f"order::{customer_id}::"):
            raise HTTPException(403, "Only your own orders can be pushed")
        if await store.get("orders", d.id):
            continue
        doc = {**d.doc, "type": "request", "status": "pending", "channels": [customer_channel(customer_id)],
               "received_at": now_iso()}
        await store.upsert("orders", d.id, doc)
        accepted.append(d.id)
    if accepted:
        _bg.append(asyncio.create_task(worker.run_once()))
    return {"accepted": accepted}


class AskRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.post("/api/assistant")
async def ask(req: AskRequest, customer_id: str = Depends(current_customer)):
    if not req.message.strip():
        raise HTTPException(400, "Ask me something")
    try:
        return await assistant.ask(customer_id, req.message[:1000], req.session_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.post("/api/admin/reload")
async def reload_dump(force: bool = True):
    return {k: v for k, v in (await loader.load(force=force)).items()}
