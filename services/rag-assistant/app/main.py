"""rag-assistant : assistant SOC fondé sur la documentation du projet (RAG).

- Modèles servis par Ollama sur le PC Hôte (GPU) : un modèle de chat et un modèle
  d'embeddings multilingue. Orchestration avec LangChain.
- Base documentaire : les documents du dépôt, montés en lecture seule dans /corpus.
- Appelé uniquement par admin-api (qui vérifie le rôle et ajoute l'état en direct :
  incident du détecteur ML, remédiations, services). Ce service ne détient aucun
  secret et ne peut déclencher aucune action.
"""

import logging
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field

from resilience_common.http import setup_http
from resilience_common.logs import log_event, setup_logging

from .corpus import load_chunks
from .rag import Assistant

SERVICE = "rag-assistant"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
CHAT_MODEL = os.getenv("RAG_CHAT_MODEL", "ministral-3:8b-instruct-2512-q4_K_M")
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "bge-m3")
CORPUS_DIR = Path(os.getenv("RAG_CORPUS_DIR", "/corpus"))
TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RETRY_SECONDS = 15

setup_logging(SERVICE)
logger = logging.getLogger(SERVICE)
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

QUESTIONS = Counter("rag_questions_total", "Questions posées à l'assistant", ["resultat"])
DUREE = Histogram("rag_answer_seconds", "Durée de réponse de l'assistant",
                  buckets=(1, 2, 5, 10, 20, 40, 80))
CHUNKS = Gauge("rag_index_chunks", "Nombre de morceaux indexés")

assistant = Assistant(OLLAMA_URL, CHAT_MODEL, EMBED_MODEL, TOP_K)
app = FastAPI(title="RESILIENCE-ALPHA rag-assistant")
setup_http(app)


def _index_once() -> None:
    t0 = time.perf_counter()
    chunks = load_chunks(CORPUS_DIR)
    assistant.build(chunks)
    CHUNKS.set(len(chunks))
    log_event(logger, "index_built", chunks=len(chunks), sources=len(assistant.index.sources),
              seconds=round(time.perf_counter() - t0, 1))


def _index_loop() -> None:
    """Indexe au démarrage ; réessaie tant qu'Ollama n'est pas joignable."""
    while True:
        try:
            _index_once()
            return
        except Exception as exc:
            assistant.index.error = str(exc)
            log_event(logger, "index_failed", logging.WARNING, error=str(exc), retry_in=RETRY_SECONDS)
            time.sleep(RETRY_SECONDS)


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=_index_loop, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if not assistant.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Index en construction")
    return {"ready": True}


@app.get("/status")
def get_status():
    idx = assistant.index
    return {
        "ready": assistant.ready,
        "chat_model": CHAT_MODEL,
        "embed_model": EMBED_MODEL,
        "chunks": idx.chunks,
        "sources": idx.sources,
        "built_at": idx.built_at,
        "error": None if assistant.ready else idx.error,
    }


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    contexte: dict | None = None


@app.post("/ask")
def ask(body: AskIn):
    if not assistant.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "L'assistant prépare sa base documentaire, réessayez dans un instant.")
    t0 = time.perf_counter()
    try:
        result = assistant.answer(body.question.strip(), body.contexte)
    except Exception as exc:
        QUESTIONS.labels("erreur").inc()
        log_event(logger, "answer_failed", logging.ERROR, error=str(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Modèle de langage injoignable (Ollama).")
    QUESTIONS.labels("ok").inc()
    DUREE.observe(time.perf_counter() - t0)
    log_event(logger, "answered", sources=[s["source"] for s in result["sources"]], **result["timings_ms"])
    return result


@app.post("/reindex")
def reindex():
    """Reconstruit l'index (après une mise à jour de la documentation)."""
    _index_once()
    return {"ok": True, "chunks": assistant.index.chunks}
