"""Praxis Vaulted Execution Proxy — FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import importlib.util
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .adapters.payment_vault import PaymentVault
from .adapters.storage import SQLiteRepository, StorageRepository
from .agent.fintech_agent import AgentModelUnavailableError, AgentRunResult, FinTechAgentRunner
from .config import Settings, get_settings
from .domain.models import AuditDecision, InterceptRequest, MetricsSummary, PolicyConfig
from .services.gemini_client import get_genai_client
from .services.hitl_service import (
    ApprovalConflictError,
    ApprovalIntegrityError,
    ApprovalNotFoundError,
    ApprovalSettlementError,
    HitlService,
)
from .services.layer2_auditor import GeminiLayer2Auditor
from .services.policy_compiler import CompileRequest, CompileResult, PolicyCompileError, PolicyCompiler
from .services.policy_rag import PolicyRAG
from .services.proxy_service import IdempotencyConflictError, ProxyService
from .services.rbi_reporting import NotReportableError, build_rbi_incident_report


log = logging.getLogger("praxis.main")
_AUTO: Any = object()  # sentinel: build from settings
WARMUP_TIMEOUT_S = 30.0  # free-tier cold starts can exceed 50s; never block boot on it


DEMO_PDF_PRESETS = {
    "clean_480": "invoice_clean_480.pdf",
    "poisoned_48000": "invoice_poisoned_480_to_48000.pdf",
}


class DemoResetRequest(BaseModel):
    agent_id: Optional[str] = None
    windows_only: bool = False


class DecideRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reviewer_id: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=1000)


class AgentRunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    untrusted_context: Optional[str] = Field(default=None, max_length=20000)
    attachment_base64: Optional[str] = None
    attachment_mime: Optional[str] = None
    policy_id: str = "default-fintech-treasury"
    contact_changed_hours_ago: Optional[float] = Field(default=None, ge=0)
    destination_mode: Optional[Literal["original_source", "alternate_account"]] = None
    simulate_timeout: bool = False
    preset_pdf: Optional[Literal["clean_480", "poisoned_48000"]] = None


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
    agent_runner: Any = _AUTO,
) -> FastAPI:
    settings = settings or get_settings()
    storage = storage or SQLiteRepository(settings.praxis_db_path)
    vault = vault or PaymentVault()
    if layer2_auditor is _AUTO or policy_compiler is _AUTO:
        auto_auditor, auto_compiler = build_gemini_services(settings, storage)
        layer2_auditor = auto_auditor if layer2_auditor is _AUTO else layer2_auditor
        policy_compiler = auto_compiler if policy_compiler is _AUTO else policy_compiler
    proxy = ProxyService(storage=storage, vault=vault, layer2_auditor=layer2_auditor)
    hitl = HitlService(storage=storage, vault=vault)
    if agent_runner is _AUTO:
        agent_runner = (
            FinTechAgentRunner(
                client=get_genai_client(settings.gemini_api_key), proxy_service=proxy, model=settings.agent_model
            )
            if settings.gemini_api_key
            else None
        )
    pdf_dir = Path(settings.demo_pdf_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if layer2_auditor is not None and hasattr(layer2_auditor, "warmup"):
            try:  # build Policy RAG index + prime the Gemini connection so the first audit isn't cold
                await asyncio.wait_for(layer2_auditor.warmup(), timeout=WARMUP_TIMEOUT_S)
            except Exception as exc:  # never block startup; audits fail closed if Gemini is down
                log.warning("Layer 2 warm-up failed: %s", exc)
        yield

    app = FastAPI(title="Praxis Vaulted Execution Proxy", version="0.3.0", lifespan=lifespan)
    app.state.settings, app.state.storage, app.state.vault, app.state.proxy = settings, storage, vault, proxy
    app.state.layer2_auditor, app.state.policy_compiler = layer2_auditor, policy_compiler
    app.state.hitl, app.state.agent_runner = hitl, agent_runner
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

    def require_reviewer_token(x_reviewer_token: Optional[str] = Header(default=None)) -> None:
        expected = settings.praxis_reviewer_token
        if expected and not (x_reviewer_token and hmac.compare_digest(x_reviewer_token.encode(), expected.encode())):
            raise HTTPException(status_code=401, detail="Invalid or missing X-Reviewer-Token.")

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "service": "praxis-proxy",
            "storage_backend": settings.storage_backend,
            "payment_vault": {"configured": vault.is_configured, "test_mode": vault.is_test_mode, "rail": "razorpay_test_mode"},
            "layer2_auditor": getattr(layer2_auditor, "model", None) or "disabled",
            "policy_compiler": getattr(policy_compiler, "model", None) or "disabled",
            "adk_agent": getattr(agent_runner, "model", None) or "disabled",
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
        status: Optional[Literal["PENDING", "PROCESSING", "APPROVED", "REJECTED", "INTEGRITY_FAILED"]] = None,
        limit: int = Query(200, ge=1, le=1000),
    ):
        rows = await storage.list_approvals(status=status, limit=limit)
        for row in rows:  # join the escalation audit so reviewers see why it was held
            audit = await storage.get_audit(row["audit_id"])
            row["escalation"] = (
                {
                    "agent_id": audit.agent_id,
                    "tool_name": audit.tool_name,
                    "merchant_id": audit.merchant_id,
                    "amount_inr": audit.amount_inr,
                    "reason": audit.reason,
                    "policy_citations": audit.policy_citations,
                    "risk_score": audit.risk_score,
                    "threat_category": audit.threat_category,
                    "layer_decided": audit.layer_decided,
                    "model_used": audit.model_used,
                }
                if audit
                else None
            )
        return rows

    # ------------------------------------------------------------------ red-team benchmark
    results_path = Path(settings.evals_results_path)
    eval_lock = asyncio.Lock()
    suite_cache: dict[str, Any] = {}

    def _load_suite():
        if "mod" not in suite_cache:
            spec = importlib.util.spec_from_file_location("praxis_redteam_suite", settings.evals_suite_path)
            if spec is None or spec.loader is None:
                raise HTTPException(status_code=503, detail="Red-team suite not found.")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod  # dataclasses resolve annotations via sys.modules
            spec.loader.exec_module(mod)
            suite_cache["mod"] = mod
        return suite_cache["mod"]

    @app.get("/v1/evals/latest")
    async def latest_eval():
        if not results_path.is_file():
            return {"status": "not_run_yet"}
        return json.loads(results_path.read_text(encoding="utf-8"))

    @app.post("/v1/evals/run")
    async def run_eval():
        if eval_lock.locked():
            raise HTTPException(status_code=409, detail="A benchmark run is already in progress.")
        async with eval_lock:
            suite = _load_suite()
            return await suite.run_benchmark(settings, results_path=results_path)

    @app.post(
        "/v1/approvals/{approval_id}/decide",
        response_model=AuditDecision,
        dependencies=[Depends(require_reviewer_token)],
    )
    async def decide_approval(approval_id: str, body: DecideRequest):
        try:
            return await hitl.decide_approval(approval_id, body.decision, body.reviewer_id, body.note)
        except ApprovalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ApprovalConflictError, ApprovalIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ApprovalSettlementError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/v1/agent/run", response_model=AgentRunResult)
    async def run_agent(body: AgentRunRequest):
        if agent_runner is None:
            raise HTTPException(status_code=503, detail="ADK agent unavailable (GEMINI_API_KEY not configured).")
        attachment_b64, attachment_mime = body.attachment_base64, body.attachment_mime
        if body.preset_pdf:
            path = pdf_dir / DEMO_PDF_PRESETS[body.preset_pdf]
            if not path.is_file():
                raise HTTPException(status_code=404, detail=f"Preset PDF {path.name} not found.")
            attachment_b64, attachment_mime = base64.b64encode(path.read_bytes()).decode(), "application/pdf"
        try:
            return await agent_runner.run(
                body.prompt,
                untrusted_context=body.untrusted_context,
                attachment_base64=attachment_b64,
                attachment_mime=attachment_mime,
                policy_id=body.policy_id,
                contact_changed_hours_ago=body.contact_changed_hours_ago,
                destination_mode=body.destination_mode,
                timeout_override_s=0.001 if body.simulate_timeout else None,
            )
        except AgentModelUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:  # e.g. invalid base64 attachment
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _demo_pdfs() -> dict[str, Path]:
        return {p.name: p for p in sorted(pdf_dir.glob("*.pdf"))} if pdf_dir.is_dir() else {}

    @app.get("/v1/demo/pdfs")
    async def list_demo_pdfs():
        presets = {v: k for k, v in DEMO_PDF_PRESETS.items()}
        return [
            {
                "name": name,
                "preset": presets.get(name),
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mime": "application/pdf",
                "url": f"/v1/demo/pdfs/{name}",
            }
            for name, path in _demo_pdfs().items()
        ]

    @app.get("/v1/demo/pdfs/{name}")
    async def get_demo_pdf(name: str):
        path = _demo_pdfs().get(name)  # whitelist lookup: no path traversal
        if path is None:
            raise HTTPException(status_code=404, detail="Unknown demo PDF.")
        return FileResponse(path, media_type="application/pdf", filename=name)

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
