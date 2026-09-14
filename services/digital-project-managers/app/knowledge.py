from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument

TERM_PATTERN = re.compile(r"[\wáéíóöőúüűÁÉÍÓÖŐÚÜŰ-]{3,}")


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be positive and overlap must be smaller than size")
    normalized = re.sub(r"\s+", " ", text).strip()
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = end - overlap
    return chunks


def add_chunks(session: Session, document: KnowledgeDocument) -> None:
    for sequence, content in enumerate(chunk_text(document.content)):
        session.add(
            KnowledgeChunk(
                document=document,
                external_project_id=document.external_project_id,
                sequence=sequence,
                content=content,
                search_text=content.lower(),
            )
        )


def search(
    session: Session,
    query: str,
    external_project_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    terms = [term.lower() for term in TERM_PATTERN.findall(query)]
    if not terms:
        return []
    statement = select(KnowledgeChunk, KnowledgeDocument).join(
        KnowledgeDocument,
        KnowledgeChunk.document_id == KnowledgeDocument.id,
    )
    if external_project_id is not None:
        statement = statement.where(
            or_(
                KnowledgeChunk.external_project_id == external_project_id,
                KnowledgeChunk.external_project_id.is_(None),
            )
        )
    else:
        statement = statement.where(KnowledgeChunk.external_project_id.is_(None))

    scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
    for chunk, document in session.execute(statement):
        score = sum(chunk.search_text.count(term) for term in terms)
        score += (1000 - document.precedence) / 10_000
        if score > 0:
            scored.append((score, chunk, document))
    scored.sort(key=lambda item: (-item[0], item[2].precedence, item[1].sequence))
    return [
        {
            "score": round(score, 4),
            "document_id": document.id,
            "external_project_id": document.external_project_id,
            "title": document.title,
            "version": document.version,
            "precedence": document.precedence,
            "chunk": chunk.content,
        }
        for score, chunk, document in scored[:limit]
    ]
