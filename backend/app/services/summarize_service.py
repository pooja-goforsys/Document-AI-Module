"""
Document summarization service.

Provides on-demand summaries of individual documents (or a folder) by:
  1. Fetching all indexed chunks (ordered by page number)
  2. Sampling chunks for very large documents to stay within token limits
  3. Asking the AI provider to generate the requested summary type
"""
import uuid
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.folder import Folder
from app.ai_providers import get_ai_provider
from app.ai_providers.retry_utils import AIServiceUnavailableError
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

_MAX_CHARS = 40_000   # ~10k tokens; stay well within Gemini's context window
_MAX_CHUNKS = 60      # sample at most this many chunks per document

_SCOPE_PROMPTS: dict[str, str] = {
    "full": (
        "You are a document summarization assistant.\n\n"
        "Write a comprehensive summary of the document excerpts below. "
        "Cover all major topics, key facts, and conclusions. "
        "Use Markdown headings (##) to organize sections. "
        "Be factual — only include information explicitly present in the excerpts.\n\n"
    ),
    "executive": (
        "You are a document summarization assistant.\n\n"
        "Write an EXECUTIVE SUMMARY of the document excerpts below. "
        "Structure:\n"
        "**TL;DR** — one sentence.\n"
        "**Key Points** — 3-5 bullet points of the most important business-relevant facts.\n"
        "**Conclusions** — one short paragraph.\n"
        "Be factual — only include information explicitly present in the excerpts.\n\n"
    ),
    "key_takeaways": (
        "You are a document summarization assistant.\n\n"
        "Extract the KEY TAKEAWAYS from the document excerpts below. "
        "Return a numbered list (1. 2. 3. …) of the most important insights, facts, or conclusions. "
        "Each item should be one clear, concise sentence. "
        "Be factual — only include information explicitly present in the excerpts.\n\n"
    ),
}


async def summarize_document(
    doc_id: uuid.UUID,
    user_id: uuid.UUID,
    scope: str,
    db: AsyncSession,
) -> dict:
    """
    Summarise a single document.
    scope: "full" | "executive" | "key_takeaways"
    Returns: {document_id, document_name, scope, summary}
    """
    doc = await db.get(Document, doc_id)
    if not doc or doc.user_id != user_id:
        raise NotFoundError("Document")

    if doc.status != DocumentStatus.indexed:
        raise ValueError("Document is not yet indexed — please wait for indexing to complete.")

    chunks_stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.page_number.asc().nullslast(), DocumentChunk.id.asc())
        .limit(_MAX_CHUNKS)
    )
    chunks = (await db.execute(chunks_stmt)).scalars().all()

    if not chunks:
        raise ValueError("No content found for this document.")

    # Build context with page labels; trim to _MAX_CHARS
    context_parts: list[str] = []
    total_chars = 0
    for chunk in chunks:
        page = f"Page {chunk.page_number}" if chunk.page_number else "N/A"
        excerpt = f"[{page}]\n{chunk.content.strip()}"
        if total_chars + len(excerpt) > _MAX_CHARS:
            break
        context_parts.append(excerpt)
        total_chars += len(excerpt)

    context = "\n\n---\n\n".join(context_parts)
    system_prompt = _SCOPE_PROMPTS.get(scope, _SCOPE_PROMPTS["full"])

    question = (
        f"Summarise the document \"{doc.original_name}\" "
        f"using the excerpts provided."
    )

    try:
        ai = get_ai_provider()
        full_text = ""
        async for token in ai.stream_chat(system_prompt, question, f"<context>\n{context}\n</context>"):
            full_text += token
    except AIServiceUnavailableError:
        raise RuntimeError(
            "The AI service is currently experiencing high demand. "
            "Please try again in a few moments."
        )
    except Exception as exc:
        logger.error(f"[Summarize] AI error for doc {doc_id}: {exc}", exc_info=True)
        raise RuntimeError(f"AI summarization failed: {exc}") from exc

    return {
        "document_id": str(doc_id),
        "document_name": doc.original_name,
        "scope": scope,
        "summary": full_text.strip(),
    }


async def summarize_folder(
    folder_id: uuid.UUID,
    user_id: uuid.UUID,
    scope: str,
    db: AsyncSession,
) -> dict:
    """
    Summarise all indexed documents in a folder.
    Returns the same shape as summarize_document.
    """
    folder = await db.get(Folder, folder_id)
    if not folder or folder.user_id != user_id:
        raise NotFoundError("Folder")

    docs_stmt = (
        select(Document)
        .where(Document.folder_id == folder_id)
        .where(Document.user_id == user_id)
        .where(Document.status == DocumentStatus.indexed)
    )
    docs = (await db.execute(docs_stmt)).scalars().all()
    if not docs:
        raise ValueError("No indexed documents found in this folder.")

    context_parts: list[str] = []
    total_chars = 0
    per_doc_limit = _MAX_CHARS // max(len(docs), 1)

    for doc in docs:
        chunks_stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id)
            .order_by(DocumentChunk.page_number.asc().nullslast())
            .limit(10)
        )
        chunks = (await db.execute(chunks_stmt)).scalars().all()
        doc_chars = 0
        for chunk in chunks:
            page = f"Page {chunk.page_number}" if chunk.page_number else "N/A"
            excerpt = f"[{doc.original_name} — {page}]\n{chunk.content.strip()}"
            if total_chars + len(excerpt) > _MAX_CHARS or doc_chars > per_doc_limit:
                break
            context_parts.append(excerpt)
            total_chars += len(excerpt)
            doc_chars += len(excerpt)

    context = "\n\n---\n\n".join(context_parts)
    system_prompt = _SCOPE_PROMPTS.get(scope, _SCOPE_PROMPTS["full"])
    question = f"Summarise all documents in the folder \"{folder.name}\" using the excerpts provided."

    try:
        ai = get_ai_provider()
        full_text = ""
        async for token in ai.stream_chat(system_prompt, question, f"<context>\n{context}\n</context>"):
            full_text += token
    except AIServiceUnavailableError:
        raise RuntimeError(
            "The AI service is currently experiencing high demand. "
            "Please try again in a few moments."
        )
    except Exception as exc:
        logger.error(f"[Summarize] AI error for folder {folder_id}: {exc}", exc_info=True)
        raise RuntimeError(f"AI summarization failed: {exc}") from exc

    return {
        "folder_id": str(folder_id),
        "folder_name": folder.name,
        "scope": scope,
        "summary": full_text.strip(),
    }
