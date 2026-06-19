import time
from pathlib import Path
import logging
from app.parsers.base import BaseParser, ParsedChunk
from app.core.config import settings

logger = logging.getLogger(__name__)

# Log extraction progress every N pages (keeps large-file logs readable)
_PROGRESS_EVERY = 10


class PDFParser(BaseParser):
    def extract_chunks(self, file_path: str) -> list[ParsedChunk]:
        t0 = time.perf_counter()

        extractor = (settings.PDF_EXTRACTOR or "auto").lower()
        if extractor in {"auto", "pdfplumber"}:
            try:
                import pdfplumber
                return self._extract_pdfplumber(pdfplumber, file_path, t0)
            except ImportError:
                if extractor == "pdfplumber":
                    raise
                logger.warning("[PDF] pdfplumber not installed; falling back to PyMuPDF")
            except Exception as exc:
                if extractor == "pdfplumber":
                    raise
                logger.warning(f"[PDF/pdfplumber] Failed; falling back to PyMuPDF: {exc!r}")

        # PyMuPDF (fitz) is a C/C++ library — 10-50× faster than pypdf for
        # text-heavy documents and handles corrupt/complex PDFs more robustly.
        # Fall back to pypdf when PyMuPDF is not installed.
        try:
            import fitz  # PyMuPDF
            chunks = self._extract_pymupdf(fitz, file_path, t0)
        except ImportError:
            logger.warning(
                "[PDF] PyMuPDF not installed — using pypdf (slower). "
                "Run: pip install PyMuPDF"
            )
            chunks = self._extract_pypdf(file_path, t0)

        return chunks

    # ── PyMuPDF path (fast) ───────────────────────────────────────────────────

    def _extract_pdfplumber(self, pdfplumber, file_path: str, t0: float) -> list[ParsedChunk]:
        """Extract page text and tables while preserving page metadata."""
        chunks: list[ParsedChunk] = []
        skipped = 0
        idx = 0
        doc_name = Path(file_path).name

        try:
            pdf = pdfplumber.open(file_path)
        except Exception as exc:
            raise ValueError(f"Cannot open PDF with pdfplumber: {exc}") from exc

        total_pages = len(pdf.pages)
        logger.info(f"[PDF/pdfplumber] Starting extraction: {total_pages} pages")

        try:
            for page_num, page in enumerate(pdf.pages, start=1):
                try:
                    text = (page.extract_text(x_tolerance=1, y_tolerance=3) or "").strip()
                    tables = page.extract_tables() or []
                    table_blocks: list[str] = []
                    for table_idx, table in enumerate(tables, start=1):
                        rows = [
                            [str(cell or "").strip().replace("\n", " ") for cell in row]
                            for row in table
                            if row and any(str(cell or "").strip() for cell in row)
                        ]
                        if not rows:
                            continue
                        table_blocks.append(
                            "[[TABLE_START]]\n"
                            f"Table {table_idx} on page {page_num}\n"
                            + "\n".join(" | ".join(row) for row in rows)
                            + "\n[[TABLE_END]]"
                        )
                    page_text = "\n\n".join(part for part in [text, *table_blocks] if part).strip()
                except Exception as exc:
                    skipped += 1
                    logger.warning(
                        f"[PDF/pdfplumber] Page {page_num}/{total_pages} skipped: {exc!r}"
                    )
                    continue

                if not page_text:
                    continue

                new_chunks = self._split_with_page(
                    page_text,
                    page_number=page_num,
                    base_index=idx,
                    metadata={
                        "extractor": "pdfplumber",
                        "document_name": doc_name,
                        "tables_on_page": len(tables),
                    },
                )
                idx += len(new_chunks)
                chunks.extend(new_chunks)

                if page_num % _PROGRESS_EVERY == 0 or page_num == total_pages:
                    elapsed = time.perf_counter() - t0
                    logger.info(
                        f"[PDF/pdfplumber] {page_num}/{total_pages} pages "
                        f"-> {len(chunks)} chunks ({elapsed:.1f}s)"
                    )
        finally:
            pdf.close()

        elapsed = time.perf_counter() - t0
        logger.info(
            f"[PDF/pdfplumber] Done: {total_pages} pages, "
            f"{len(chunks)} chunks, {skipped} skipped ({elapsed:.1f}s)"
        )
        return chunks

    def _extract_pymupdf(self, fitz, file_path: str, t0: float) -> list[ParsedChunk]:
        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            raise ValueError(f"Cannot open PDF with PyMuPDF: {exc}") from exc

        total_pages  = len(doc)
        chunks: list[ParsedChunk] = []
        skipped      = 0
        idx          = 0

        logger.info(f"[PDF/pymupdf] Starting extraction: {total_pages} pages")

        for page_num in range(total_pages):
            try:
                text = doc[page_num].get_text()
                text = (text or "").strip()
            except Exception as exc:
                skipped += 1
                logger.warning(
                    f"[PDF/pymupdf] Page {page_num + 1}/{total_pages} skipped: {exc!r}"
                )
                continue

            if not text:
                continue

            new_chunks = self._split_with_page(
                text,
                page_number=page_num + 1,
                base_index=idx,
                metadata={
                    "extractor": "pymupdf",
                    "document_name": Path(file_path).name,
                },
            )
            idx    += len(new_chunks)
            chunks.extend(new_chunks)

            display_page = page_num + 1
            if display_page % _PROGRESS_EVERY == 0 or display_page == total_pages:
                elapsed = time.perf_counter() - t0
                logger.info(
                    f"[PDF/pymupdf] {display_page}/{total_pages} pages "
                    f"→ {len(chunks)} chunks  ({elapsed:.1f}s)"
                )

        doc.close()
        elapsed = time.perf_counter() - t0
        logger.info(
            f"[PDF/pymupdf] Done: {total_pages} pages, "
            f"{len(chunks)} chunks, {skipped} skipped  ({elapsed:.1f}s)"
        )
        return chunks

    # ── pypdf fallback path (slower, no extra dependency) ────────────────────

    def _extract_pypdf(self, file_path: str, t0: float) -> list[ParsedChunk]:
        from pypdf import PdfReader

        try:
            reader = PdfReader(file_path, strict=False)
        except Exception as exc:
            raise ValueError(f"Cannot open PDF with pypdf: {exc}") from exc

        total_pages  = len(reader.pages)
        chunks: list[ParsedChunk] = []
        skipped      = 0
        idx          = 0

        logger.info(f"[PDF/pypdf] Starting extraction: {total_pages} pages")

        for page_num, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
                text = text.strip()
            except Exception as exc:
                skipped += 1
                logger.warning(
                    f"[PDF/pypdf] Page {page_num}/{total_pages} skipped: {exc!r}"
                )
                continue

            if not text:
                continue

            new_chunks = self._split_with_page(
                text,
                page_number=page_num,
                base_index=idx,
                metadata={
                    "extractor": "pypdf",
                    "document_name": Path(file_path).name,
                },
            )
            idx    += len(new_chunks)
            chunks.extend(new_chunks)

            if page_num % _PROGRESS_EVERY == 0 or page_num == total_pages:
                elapsed = time.perf_counter() - t0
                logger.info(
                    f"[PDF/pypdf] {page_num}/{total_pages} pages "
                    f"→ {len(chunks)} chunks  ({elapsed:.1f}s)"
                )

        elapsed = time.perf_counter() - t0
        logger.info(
            f"[PDF/pypdf] Done: {total_pages} pages, "
            f"{len(chunks)} chunks, {skipped} skipped  ({elapsed:.1f}s)"
        )
        return chunks
