"""Policy RAG grounded on `gemini-embedding-2` (3072-d) with a local vector cache.

Clause vectors are embedded once and cached in `backend/policy_embeddings_cache.json`, keyed
by the corpus fingerprint + model, so they are rebuilt automatically when the corpus changes.
Queries are embedded live; ONLY if that call times out do we fall back to deterministic keyword
scoring, and the fallback is logged and reported via `RetrievalResult.mode` (never silent).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from google import genai
from google.genai import types

from ..domain.policy_corpus import POLICY_CORPUS, PolicyClause, corpus_fingerprint

log = logging.getLogger("praxis.policy_rag")

QUERY_CACHE_MAX_ENTRIES = 256


@dataclass
class RetrievalResult:
    clauses: list[PolicyClause]
    scores: list[float]
    mode: str  # "embedding" | "keyword_fallback"
    latency_ms: float

    @property
    def policy_ids(self) -> list[str]:
        return [c.policy_id for c in self.clauses]


class PolicyRAG:
    def __init__(
        self,
        client: genai.Client,
        *,
        model: str = "gemini-embedding-2",
        cache_path: str | Path,
        query_timeout_s: float = 1.5,
        query_cache_size: int = QUERY_CACHE_MAX_ENTRIES,
    ):
        self.client = client
        self.model = model
        self.cache_path = Path(cache_path)
        self.query_timeout_s = query_timeout_s
        self._matrix: Optional[np.ndarray] = None  # (n_clauses, dims), L2-normalised
        self._index_lock = asyncio.Lock()
        # LRU of query_text -> unit vector: repeated queries skip a gemini-embedding-2 call (free-tier RPM);
        # every NEW query still hits the live embedding endpoint.
        self._query_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._query_cache_size = query_cache_size
        self.query_cache_hits = 0
        self.query_cache_misses = 0

    # ------------------------------------------------------------------ index
    async def _embed(self, text: str, task_type: str) -> np.ndarray:
        resp = await self.client.aio.models.embed_content(
            model=self.model, contents=text, config=types.EmbedContentConfig(task_type=task_type)
        )
        vec = np.asarray(resp.embeddings[0].values, dtype=np.float32)
        return vec / (np.linalg.norm(vec) or 1.0)

    async def _embed_query(self, query_text: str) -> np.ndarray:
        cached = self._query_cache.get(query_text)
        if cached is not None:
            self._query_cache.move_to_end(query_text)
            self.query_cache_hits += 1
            return cached
        vec = await self._embed(query_text, "RETRIEVAL_QUERY")
        self.query_cache_misses += 1
        self._query_cache[query_text] = vec
        if len(self._query_cache) > self._query_cache_size:
            self._query_cache.popitem(last=False)  # evict least-recently-used
        return vec

    def _load_cache(self, fingerprint: str) -> Optional[np.ndarray]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("fingerprint") != fingerprint or data.get("model") != self.model:
            return None
        ids = [c.policy_id for c in POLICY_CORPUS]
        if data.get("policy_ids") != ids:
            return None
        return np.asarray(data["vectors"], dtype=np.float32)

    async def ensure_index(self) -> None:
        if self._matrix is not None:
            return
        async with self._index_lock:
            if self._matrix is not None:
                return
            fingerprint = corpus_fingerprint()
            cached = self._load_cache(fingerprint)
            if cached is None:
                # gemini-embedding-2 aggregates list inputs into ONE vector, so embed each clause separately.
                vecs = await asyncio.gather(*[self._embed(c.render(), "RETRIEVAL_DOCUMENT") for c in POLICY_CORPUS])
                cached = np.vstack(vecs)
                self.cache_path.write_text(
                    json.dumps(
                        {
                            "fingerprint": fingerprint,
                            "model": self.model,
                            "dims": int(cached.shape[1]),
                            "policy_ids": [c.policy_id for c in POLICY_CORPUS],
                            "vectors": cached.round(7).tolist(),
                        }
                    ),
                    encoding="utf-8",
                )
                log.info("Policy RAG index rebuilt (%d clauses, %d dims)", *cached.shape)
            self._matrix = cached

    @property
    def dims(self) -> Optional[int]:
        return None if self._matrix is None else int(self._matrix.shape[1])

    # ------------------------------------------------------------------ retrieval
    @staticmethod
    def _keyword_scores(query_text: str) -> list[float]:
        tokens = set(re.findall(r"[a-z_]+", query_text.lower()))
        return [len(tokens.intersection(c.keywords)) / len(c.keywords) for c in POLICY_CORPUS]

    async def retrieve_relevant_policies(self, query_text: str, top_k: int = 3) -> RetrievalResult:
        t0 = time.perf_counter()
        mode = "embedding"
        try:
            await asyncio.wait_for(self.ensure_index(), timeout=10.0)
            qvec = await asyncio.wait_for(self._embed_query(query_text), timeout=self.query_timeout_s)
            scores = (self._matrix @ qvec).tolist()
        except asyncio.TimeoutError:
            log.warning("gemini-embedding-2 timed out; Policy RAG using deterministic keyword fallback")
            mode, scores = "keyword_fallback", self._keyword_scores(query_text)
        order = sorted(range(len(POLICY_CORPUS)), key=lambda i: scores[i], reverse=True)[:top_k]
        return RetrievalResult(
            clauses=[POLICY_CORPUS[i] for i in order],
            scores=[round(float(scores[i]), 4) for i in order],
            mode=mode,
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
