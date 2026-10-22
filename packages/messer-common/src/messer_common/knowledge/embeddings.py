"""Embedding adapters.

Model ids (stored per knowledge base in ``knowledge_bases.embedding_model``; a knowledge base never
mixes models because vectors of different models are not comparable):

* ``hash-384`` — deterministic offline embedder: feature hashing of normalized, accent-stripped word
  unigrams, word bigrams and character trigrams, L2-normalized. No network, no model files. Used in tests,
  with ``MESSER_EMBEDDINGS_PROVIDER=hash`` and whenever the local model cannot be loaded.
* ``intfloat/multilingual-e5-small`` (384) — local multilingual model run with fastembed (ONNX), downloaded
  once from Hugging Face into ``<runtime_cache_dir>/fastembed``. Any other fastembed-supported model id works too.
* ``voyage/<model>`` — Voyage AI API (``VOYAGE_API_KEY``), e.g. ``voyage/voyage-3.5`` (1024).
* ``bedrock/<model>`` — Amazon Bedrock in ``AWS_REGION`` (EU), e.g. ``bedrock/amazon.titan-embed-text-v2:0`` (1024).
"""

from __future__ import annotations

import abc
import asyncio
import hashlib
import hmac
import itertools
import json
import math
import os
import re
import threading
import time
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ..logging import get_logger
from ..settings import get_settings
from .errors import EmbeddingUnavailable

log = get_logger("messer.knowledge.embeddings")

HASH_MODEL = "hash-384"
LOCAL_DEFAULT_MODEL = "intfloat/multilingual-e5-small"
VOYAGE_PREFIX = "voyage/"
BEDROCK_PREFIX = "bedrock/"


@dataclass(frozen=True, slots=True)
class LocalModelSpec:
    dim: int
    model_file: str = "onnx/model.onnx"
    query_prefix: str = ""
    passage_prefix: str = ""


# Models registered as fastembed custom models (fastembed's own catalog is also accepted).
LOCAL_MODELS: dict[str, LocalModelSpec] = {
    LOCAL_DEFAULT_MODEL: LocalModelSpec(dim=384, query_prefix="query: ", passage_prefix="passage: "),
}

VOYAGE_DIMS = {
    "voyage-3.5": 1024,
    "voyage-3.5-lite": 1024,
    "voyage-3-large": 1024,
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-multilingual-2": 1024,
    "voyage-code-3": 1024,
}
BEDROCK_DIMS = {
    "amazon.titan-embed-text-v2:0": 1024,
    "amazon.titan-embed-text-v1": 1536,
    "cohere.embed-multilingual-v3": 1024,
}


class Embedder(abc.ABC):
    """Turns text into vectors. ``embed`` is for stored passages, ``embed_query`` for search queries."""

    model: str
    dim: int
    max_batch: int = 32

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


# ---------------------------------------------------------------------------------------------- hash


_STOPWORDS = frozenset(
    """
    a al algo algun alguna ante con como contra cual cuando de del desde donde dos el ella ellas ellos en entre
    era es esa ese eso esta este esto estos fue ha han hay la las le les lo los mas me mi mis muy ni no nos o os
    otra otro para pero poco por porque que quien se sea segun ser si sin sobre son su sus tambien te tiene tu un
    una uno unos y ya yo
    an and are as at be been but by can do does for from had has have he her his how i if in into is it its me
    my not of on or our she so than that the their them then there these they this those to was we were what when
    which who will with you your
    """.split()
)
_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_text(text: str) -> str:
    """Lowercase, strip accents (NFKD), keep letters/digits as word characters."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _feature_slot(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "little")
    return value % dim, (1.0 if (value >> 63) & 1 == 0 else -1.0)


class HashEmbedder(Embedder):
    """Deterministic, dependency-free embedder (feature hashing). Same input → same vector, everywhere."""

    max_batch = 256

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.model = f"hash-{dim}"

    def vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        words = _WORD_RE.findall(normalize_text(text))

        def add(feature: str, weight: float) -> None:
            slot, sign = _feature_slot(feature, self.dim)
            vec[slot] += sign * weight

        content_words: list[str] = []
        for word in words:
            stop = word in _STOPWORDS
            add("w:" + word, 0.15 if stop else 1.0)
            if stop:
                continue
            content_words.append(word)
            if len(word) >= 3:
                padded = f"#{word}#"
                grams = [padded[i : i + 3] for i in range(len(padded) - 2)]
                weight = 0.6 / math.sqrt(len(grams))
                for gram in grams:
                    add("c:" + gram, weight)
        for first, second in itertools.pairwise(content_words):
            add(f"b:{first}_{second}", 0.5)
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            # Empty or punctuation-only text: a fixed unit vector keeps cosine distance defined.
            slot, sign = _feature_slot("∅", self.dim)
            vec[slot] = sign
            return vec
        return [x / norm for x in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if len(texts) > 64:
            return await asyncio.to_thread(lambda: [self.vector(t) for t in texts])
        return [self.vector(t) for t in texts]


# ---------------------------------------------------------------------------------------------- fastembed


def fastembed_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("fastembed") is not None


def _fastembed_cache_dir() -> Path:
    path = get_settings().runtime_cache_dir / "fastembed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fastembed_catalog() -> dict[str, int]:
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return {}
    return {str(m["model"]): int(m["dim"]) for m in TextEmbedding.list_supported_models()}


class FastEmbedEmbedder(Embedder):
    """Local ONNX model through fastembed. Loading happens once per process, in a worker thread."""

    _instances: dict[str, Any] = {}
    _lock = threading.Lock()

    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        spec = LOCAL_MODELS.get(model)
        self.query_prefix = spec.query_prefix if spec else ""
        self.passage_prefix = spec.passage_prefix if spec else ""
        self.max_batch = get_settings().messer_embeddings_batch_size

    def _load_sync(self) -> Any:
        with self._lock:
            if self.model in self._instances:
                return self._instances[self.model]
            try:
                from fastembed import TextEmbedding
                from fastembed.common.model_description import ModelSource, PoolingType
            except ImportError as exc:
                raise EmbeddingUnavailable("fastembed no está instalado en este servicio") from exc
            spec = LOCAL_MODELS.get(self.model)
            if spec is not None:
                try:
                    TextEmbedding.add_custom_model(
                        model=self.model,
                        pooling=PoolingType.MEAN,
                        normalization=True,
                        sources=ModelSource(hf=self.model),
                        dim=spec.dim,
                        model_file=spec.model_file,
                    )
                except ValueError:
                    pass  # already registered in this process
            started = time.perf_counter()
            try:
                instance = TextEmbedding(model_name=self.model, cache_dir=str(_fastembed_cache_dir()))
            except Exception as exc:
                raise EmbeddingUnavailable(
                    f"No se ha podido cargar el modelo de embeddings {self.model}",
                    details={"model": self.model, "error": str(exc)[:300]},
                ) from exc
            log.info("embeddings.local_model_loaded", model=self.model, seconds=round(time.perf_counter() - started, 1))
            self._instances[self.model] = instance
            return instance

    def _embed_sync(self, texts: list[str], prefix: str) -> list[list[float]]:
        instance = self._load_sync()
        vectors = instance.embed([prefix + t for t in texts], batch_size=max(1, self.max_batch))
        return [[float(x) for x in v] for v in vectors]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts, self.passage_prefix)

    async def embed_query(self, text: str) -> list[float]:
        return (await asyncio.to_thread(self._embed_sync, [text], self.query_prefix))[0]


# ---------------------------------------------------------------------------------------------- remote APIs


async def _post_with_retries(
    client: httpx.AsyncClient, url: str, *, content: bytes, headers: dict[str, str], attempts: int = 3
) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            res = await client.post(url, content=content, headers=headers)
        except httpx.HTTPError as exc:
            last = exc
        else:
            if res.status_code < 300:
                return res.json()
            if res.status_code not in (408, 429, 500, 502, 503, 504):
                raise EmbeddingUnavailable(
                    "El proveedor de embeddings ha rechazado la petición",
                    details={"status": res.status_code, "body": res.text[:300]},
                )
            last = RuntimeError(f"HTTP {res.status_code}")
        await asyncio.sleep(0.5 * (2**attempt))
    raise EmbeddingUnavailable("El proveedor de embeddings no responde", details={"error": str(last)})


class VoyageEmbedder(Embedder):
    url = "https://api.voyageai.com/v1/embeddings"
    max_batch = 128

    def __init__(self, model: str) -> None:
        self.model = model
        self.remote_model = model.removeprefix(VOYAGE_PREFIX)
        self.dim = VOYAGE_DIMS.get(self.remote_model, 1024)

    async def _call(self, texts: list[str], input_type: str) -> list[list[float]]:
        key = get_settings().voyage_api_key
        if not key:
            raise EmbeddingUnavailable("Falta VOYAGE_API_KEY para usar embeddings de Voyage")
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60) as client:
            for start in range(0, len(texts), self.max_batch):
                batch = texts[start : start + self.max_batch]
                body = json.dumps({"input": batch, "model": self.remote_model, "input_type": input_type}).encode()
                data = await _post_with_retries(
                    client,
                    self.url,
                    content=body,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                )
                items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
                out.extend([[float(x) for x in item["embedding"]] for item in items])
        if len(out) != len(texts):
            raise EmbeddingUnavailable("Respuesta incompleta del proveedor de embeddings")
        return out

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._call(texts, "document") if texts else []

    async def embed_query(self, text: str) -> list[float]:
        return (await self._call([text], "query"))[0]


def sigv4_headers(
    *,
    method: str,
    url: str,
    region: str,
    service: str,
    body: bytes,
    access_key: str,
    secret_key: str,
    session_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """AWS Signature Version 4 headers for a JSON request (no SDK dependency)."""
    moment = now or datetime.now(UTC)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = moment.strftime("%Y%m%d")
    parts = urlsplit(url)
    canonical_uri = quote(parts.path or "/", safe="/-_.~")
    headers = {"content-type": "application/json", "host": parts.netloc, "x-amz-date": amz_date}
    if session_token:
        headers["x-amz-security-token"] = session_token
    signed = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_request = "\n".join([method, canonical_uri, parts.query, canonical_headers, signed, payload_hash])
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_signing = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode(), date_stamp), region), service), "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    result = {
        "Content-Type": "application/json",
        "X-Amz-Date": amz_date,
        "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={signature}",
    }
    if session_token:
        result["X-Amz-Security-Token"] = session_token
    return result


class BedrockEmbedder(Embedder):
    """Amazon Titan / Cohere embeddings on Bedrock, signed with SigV4 (EU region from settings)."""

    max_batch = 16

    def __init__(self, model: str) -> None:
        self.model = model
        self.model_id = model.removeprefix(BEDROCK_PREFIX)
        self.dim = BEDROCK_DIMS.get(self.model_id, 1024)

    async def _one(self, client: httpx.AsyncClient, text: str, input_type: str) -> list[float]:
        settings = get_settings()
        if not settings.has_bedrock:
            raise EmbeddingUnavailable("Faltan las claves de AWS para usar embeddings de Bedrock")
        region = settings.aws_region
        url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{quote(self.model_id, safe='')}/invoke"
        if self.model_id.startswith("cohere."):
            payload: dict[str, Any] = {"texts": [text[:2048]], "input_type": input_type}
        elif self.model_id.endswith("v1"):
            payload = {"inputText": text[:8000]}
        else:
            payload = {"inputText": text[:8000], "dimensions": self.dim, "normalize": True}
        body = json.dumps(payload).encode()
        headers = sigv4_headers(
            method="POST",
            url=url,
            region=region,
            service="bedrock",
            body=body,
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
            session_token=os.environ.get("AWS_SESSION_TOKEN") or None,
        )
        data = await _post_with_retries(client, url, content=body, headers=headers)
        if "embeddings" in data:
            return [float(x) for x in data["embeddings"][0]]
        return [float(x) for x in data["embedding"]]

    async def _call(self, texts: list[str], input_type: str) -> list[list[float]]:
        semaphore = asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=60) as client:

            async def run(text: str) -> list[float]:
                async with semaphore:
                    return await self._one(client, text, input_type)

            return list(await asyncio.gather(*(run(t) for t in texts)))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._call(texts, "search_document") if texts else []

    async def embed_query(self, text: str) -> list[float]:
        return (await self._call([text], "search_query"))[0]


# ---------------------------------------------------------------------------------------------- selection

_embedders: dict[str, Embedder] = {}


def model_dim(model: str) -> int:
    """Vector dimension of a model id (raises EmbeddingUnavailable for unknown local models)."""
    if model.startswith("hash-"):
        return int(model.split("-", 1)[1])
    if model.startswith(VOYAGE_PREFIX):
        return VOYAGE_DIMS.get(model.removeprefix(VOYAGE_PREFIX), 1024)
    if model.startswith(BEDROCK_PREFIX):
        return BEDROCK_DIMS.get(model.removeprefix(BEDROCK_PREFIX), 1024)
    if model in LOCAL_MODELS:
        return LOCAL_MODELS[model].dim
    catalog = _fastembed_catalog()
    if model in catalog:
        return catalog[model]
    raise EmbeddingUnavailable(f"Modelo de embeddings desconocido: {model}", details={"model": model})


def get_embedder(model: str) -> Embedder:
    """Embedder for a model id (cached per process)."""
    if model in _embedders:
        return _embedders[model]
    embedder: Embedder
    if model == "hash" or model.startswith("hash-"):
        dim = 384 if model == "hash" else int(model.split("-", 1)[1])
        if not 8 <= dim <= 4096:
            raise EmbeddingUnavailable(f"Dimensión no válida para {model}")
        embedder = HashEmbedder(dim)
    elif model.startswith(VOYAGE_PREFIX):
        embedder = VoyageEmbedder(model)
    elif model.startswith(BEDROCK_PREFIX):
        embedder = BedrockEmbedder(model)
    else:
        if not fastembed_installed():
            raise EmbeddingUnavailable("fastembed no está instalado en este servicio", details={"model": model})
        embedder = FastEmbedEmbedder(model, model_dim(model))
    _embedders[model] = embedder
    return embedder


_availability: dict[str, tuple[float, bool]] = {}
_AVAILABILITY_TTL_S = 600.0


def _local_model_cached(model: str) -> bool:
    cache = _fastembed_cache_dir()
    marker = "models--" + model.replace("/", "--")
    return any(p.name == marker for p in cache.iterdir()) if cache.exists() else False


async def local_model_available(model: str = LOCAL_DEFAULT_MODEL) -> bool:
    """True when fastembed is installed and the model is cached or Hugging Face is reachable."""
    if not fastembed_installed():
        return False
    cached = _availability.get(model)
    if cached and time.monotonic() - cached[0] < _AVAILABILITY_TTL_S:
        return cached[1]
    ok = await asyncio.to_thread(_local_model_cached, model)
    if not ok and model in LOCAL_MODELS:
        endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                res = await client.get(f"{endpoint}/api/models/{model}")
                ok = res.status_code == 200
        except httpx.HTTPError:
            ok = False
    _availability[model] = (time.monotonic(), ok)
    return ok


async def default_embedding_model(*, data_residency: str = "standard") -> str:
    """Model id for a new knowledge base, from settings and what is available right now.

    ``eu_strict`` organizations never use Voyage (non-EU provider): local model, Bedrock EU or hash.
    """
    settings = get_settings()
    explicit = settings.messer_embeddings_model.strip()
    if explicit and not (data_residency == "eu_strict" and explicit.startswith(VOYAGE_PREFIX)):
        return explicit
    provider = settings.messer_embeddings_provider
    if provider == "hash":
        return HASH_MODEL
    if provider == "voyage" and settings.voyage_api_key and data_residency != "eu_strict":
        return VOYAGE_PREFIX + settings.voyage_embeddings_model
    if provider == "bedrock" and settings.has_bedrock:
        return BEDROCK_PREFIX + settings.bedrock_embeddings_model
    if await local_model_available(LOCAL_DEFAULT_MODEL):
        return LOCAL_DEFAULT_MODEL
    log.warning("embeddings.local_model_unavailable", fallback=HASH_MODEL)
    return HASH_MODEL


async def available_models(*, data_residency: str = "standard") -> list[dict[str, Any]]:
    """Choices for the "create knowledge base" form, with availability."""
    settings = get_settings()
    local_ok = await local_model_available(LOCAL_DEFAULT_MODEL)
    models: list[dict[str, Any]] = [
        {"id": LOCAL_DEFAULT_MODEL, "dim": 384, "kind": "local", "available": local_ok},
        {"id": HASH_MODEL, "dim": 384, "kind": "offline", "available": True},
        {
            "id": BEDROCK_PREFIX + settings.bedrock_embeddings_model,
            "dim": BEDROCK_DIMS.get(settings.bedrock_embeddings_model, 1024),
            "kind": "bedrock",
            "available": settings.has_bedrock,
        },
    ]
    if data_residency != "eu_strict":
        models.append(
            {
                "id": VOYAGE_PREFIX + settings.voyage_embeddings_model,
                "dim": VOYAGE_DIMS.get(settings.voyage_embeddings_model, 1024),
                "kind": "voyage",
                "available": bool(settings.voyage_api_key),
            }
        )
    return models


async def embed_in_batches(
    embedder: Embedder,
    texts: Sequence[str],
    *,
    batch_size: int | None = None,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[list[float]]:
    """Embed many passages in batches, reporting progress (done, total) after each batch."""
    size = max(1, batch_size or embedder.max_batch)
    out: list[list[float]] = []
    total = len(texts)
    for start in range(0, total, size):
        batch = list(texts[start : start + size])
        vectors = await embedder.embed(batch)
        if len(vectors) != len(batch) or any(len(v) != embedder.dim for v in vectors):
            raise EmbeddingUnavailable("El modelo de embeddings devolvió vectores inesperados")
        out.extend(vectors)
        if on_progress is not None:
            await on_progress(len(out), total)
    return out


def to_pgvector(vector: Sequence[float]) -> str:
    """pgvector text literal (``[0.1,0.2,…]``)."""
    return "[" + ",".join(f"{float(x):.7g}" for x in vector) + "]"
