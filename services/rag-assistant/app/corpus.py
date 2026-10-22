"""Chargement et découpage de la base documentaire de l'assistant.

La base documentaire, ce sont les documents du projet eux-mêmes (procédures,
architecture, analyse de risques, playbooks, règles d'alerte), montés en lecture
seule dans /corpus. Chaque morceau garde sa source et sa section, pour que
l'assistant puisse citer d'où vient l'information.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

EXTENSIONS = {".md", ".yml", ".yaml"}
CHUNK_SIZE = 1100
CHUNK_OVERLAP = 150

_headers = [("#", "h1"), ("##", "h2"), ("###", "h3")]
_md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_headers, strip_headers=False)
_text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
)


@dataclass
class Chunk:
    id: str
    source: str   # chemin relatif dans le dépôt
    section: str  # titre de section le plus précis
    text: str


def _section(meta: dict) -> str:
    for key in ("h3", "h2", "h1"):
        if meta.get(key):
            return meta[key].strip()
    return ""


def load_chunks(root: Path) -> list[Chunk]:
    """Lit tous les documents de `root` et les découpe en morceaux citables."""
    chunks: list[Chunk] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        source = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue

        if path.suffix.lower() == ".md":
            sections = _md_splitter.split_text(text)
            pieces = []
            for doc in sections:
                for part in _text_splitter.split_text(doc.page_content):
                    pieces.append((_section(doc.metadata), part))
        else:  # YAML (règles d'alerte...) : découpage simple
            pieces = [("", part) for part in _text_splitter.split_text(text)]

        for section, part in pieces:
            part = part.strip()
            if len(part) < 40:
                continue
            digest = hashlib.sha1(f"{source}|{part}".encode()).hexdigest()[:12]
            chunks.append(Chunk(id=digest, source=source, section=section, text=part))
    return chunks
