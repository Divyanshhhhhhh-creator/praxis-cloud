"""Praxis Vaulted Execution Proxy — FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .adapters.payment_vault import PaymentVault
from .adapters.storage import SQLiteRepository, StorageRepository
from .config import Settings, get_settings
from .domain.models import AuditDecision, InterceptRequest, MetricsSummary, PolicyConfig
from .services.gemini_client import get_genai_client
from .services.layer2_auditor import GeminiLayer2Auditor
from .services.policy_compiler import CompileRequest, CompileResult, PolicyCompileError, PolicyCompiler
from .services.policy_rag import PolicyRAG
from .services.proxy_service import IdempotencyConflictError, ProxyService
from .services.rbi_reporting import NotReportableError, build_rbi_incident_report


log = logging.getLogger("praxis.main")
_AUTO: Any = object()  # sentinel: build from settings
WARMUP_TIMEOUT_S = 30.0  # free-tier cold starts can exceed 50s; never block boot on it


class DemoResetRequest(BaseModel):
    agent_id: Optional[str] = None
    windows_only: bool = False


def build_gemini_services(settings: Settings, storage: StorageRepository):
    """Construct the live Gemini auditor + policy compiler (None if no API key / disabled)."""
    if not settings.gemini_api_key:
        return None, None
    client = get_genai_client(settings.gemini_api_key)
    rag = PolicyRAG(client, model=settings.embedding_model, cache_path=settings.policy_embeddings_cache_path)
    auditor = (
        GeminiLayer2Auditor(
            client, rag, model=settings.l2_auditor_model,
            text_timeout_s=settings.l2_text_timeout_s, multimodal_timeout_s=settings.l2_multimodal_timeout_s,
            service_tier=settings.l2_service_tier or None,
        )
        if settings.layer2_enabled
        else None
    )
    compiler = PolicyCompiler(
        client, storage, model=settings.policy_compiler_model, fallback_model=settings.policy_compiler_fallback_model
    )
    return auditor, compiler


def create_app(
    *,
    settings: Optional[Settings] = None,
    storage: Optional[StorageRepository] = None,
    vault: Optional[PaymentVault] = None,
    layer2_auditor: Any = _AUTO,
    policy_compiler: Any = _AUTO,
) -> FastAPI:
    settings = settings or get_settings()
    storage = storage or SQLiteRepository(settings.praxis_db_path)
    vault = vault or PaymentVault()
    if layer2_auditor is _AUTO or policy_compiler is _AUTO:
        auto_auditor, auto_compiler = build_gemini_services(settings, storage)
        layer2_auditor = auto_auditor if layer2_auditor is _AUTO else layer2_auditor
        policy_compiler = auto_compiler if policy_compiler is _AUTO else policy_compiler
    proxy = ProxyService(storage=storage, vault=vault, layer2_auditor=layer2_auditor)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if layer2_auditor is not None and hasattr(layer2_auditor, "warmup"):
            try:  # build Policy RAG index + prime the Gemini connection so the first audit isn't cold
                await asyncio.wait_for(layer2_auditor.warmup(), timeout=WARMUP_TIMEOUT_S)
            except Exception as exc:  # never block startup; audits fail closed if Gemini is down
                log.warning("Layer 2 warm-up failed: %s", exc)
        yield

    app = FastAPI(title="Praxis Vaulted Execution Proxy", version="0.2.0", lifespan=lifespan)
    app.state.settings, app.state.storage, app.state.vault, app.state.proxy = settings, storage, vault, proxy
    app.state.layer2_auditor, app.state.policy_compiler = layer2_auditor, policy_compiler
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_agent_token(x_agent_token: Optional[str] = Header(default=None)) -> None:
        expected = settings.praxis_agent_token
        if not expected:  # fail closed if the server has no token configured
            raise HTTPException(status_code=503, detail="PRAXIS_AGENT_TOKEN not configured; proxy is fail-closed.")
        if not x_agent_token or not hmac.compare_digest(x_agent_token.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="Invalid or missing X-Agent-Token.")

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "praxis-proxy",
            "storage_backend": settings.storage_backend,
            "payment_vault": {"configured": vault.is_configured, "test_mode": vault.is_test_mode, "rail": "razorpay_test_mode"},
            "layer2_auditor": getattr(layer2_auditor, "model", None) or "disabled",
            "policy_compiler": getattr(policy_compiler, "model", None) or "disabled",
            "region": settings.gcp_region,
        }

    @app.post("/v1/intercept", response_model=AuditDecision, dependencies=[Depends(require_agent_token)])
    async def intercept(req: InterceptRequest, response: Response):
        try:
            outcome = await proxy.intercept(req)
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response.headers["X-Praxis-Idempotent-Replay"] = "true" if outcome.replayed else "false"
        return outcome.decision

    @app.get("/v1/policies", response_model=list[PolicyConfig])
    async def list_policies():
        return await storage.list_policies()

    @app.post("/v1/policies/compile", response_model=CompileResult)
    async def compile_policy(body: CompileRequest):
        if policy_compiler is None:
            raise HTTPException(status_code=503, detail="Policy compiler unavailable (GEMINI_API_KEY not configured).")
        try:
            return await policy_compiler.compile(body)
        except PolicyCompileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/approvals")
    async def list_approvals(
        status: Optional[Literal["PENDING", "APPROVED", "REJECTED", "EXECUTED", "EXPIRED"]] = None,
        limit: int = Query(200, ge=1, le=1000),
    ):
        return await storage.list_approvals(status=status, limit=limit)

    @app.put("/v1/policies/{policy_id}", response_model=PolicyConfig)
    async def put_policy(policy_id: str, policy: PolicyConfig):
        if policy.policy_id != policy_id:
            raise HTTPException(status_code=422, detail="Path policy_id must match body policy_id.")
        return await storage.upsert_policy(policy)

    @app.get("/v1/audits", response_model=list[AuditDecision])
    async def list_audits(limit: int = Query(100, ge=1, le=1000), agent_id: Optional[str] = None):
        return await storage.list_audits(limit=limit, agent_id=agent_id)

    @app.get("/v1/audits/{audit_id}/rbi-incident-report")
    async def rbi_incident_report(audit_id: str):
        decision = await storage.get_audit(audit_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Audit not found.")
        try:
            return build_rbi_incident_report(decision, gcp_region=settings.gcp_region)
        except NotReportableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/metrics", response_model=MetricsSummary)
    async def metrics(agent_id: Optional[str] = None, policy_id: Optional[str] = None):
        return await storage.get_metrics(agent_id=agent_id, policy_id=policy_id)

    @app.post("/v1/demo/reset")
    async def demo_reset(body: Optional[DemoResetRequest] = None):
        body = body or DemoResetRequest()
        if body.windows_only:
            return {"reset": "windows", "ledger_rows": await storage.reset_demo_windows(body.agent_id)}
        return {"reset": "all_demo_data", "policies_preserved": True, **(await storage.reset_demo_data(body.agent_id))}

    return app


app = create_app()
