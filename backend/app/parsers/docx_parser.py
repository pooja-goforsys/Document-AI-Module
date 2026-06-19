from docx import Document as DocxDoc
from docx.oxml.ns import qn
from app.parsers.base import BaseParser, ParsedChunk


class DOCXParser(BaseParser):
    def extract_chunks(self, file_path: str) -> list[ParsedChunk]:
        doc = DocxDoc(file_path)
        chunks: list[ParsedChunk] = []
        idx = 0
        page_size = 20  # paragraphs per approximated "page"

        P_TAG = qn("w:p")
        T_TAG = qn("w:tbl")
        paragraphs_iter = iter(doc.paragraphs)
        tables_iter = iter(doc.tables)

        para_buffer: list[str] = []
        block_start_para = 0      # absolute para index where buffer began
        para_count_total = 0      # paragraphs seen so far (incl. empty skips)

        def flush_paragraph_block() -> None:
            nonlocal idx, para_buffer
            if not para_buffer:
                return
            block = "\n".join(para_buffer)
            para_buffer = []
            if not block.strip():
                return
            page_num = (block_start_para // page_size) + 1
            new_chunks = self._split_with_page(
                block, page_number=page_num, base_index=idx
            )
            idx += len(new_chunks)
            chunks.extend(new_chunks)

        # Walk the body in document order so tables inherit a page number
        # derived from the surrounding paragraphs rather than 0.
        for child in doc.element.body.iterchildren():
            if child.tag == P_TAG:
                p = next(paragraphs_iter, None)
                if p is None:
                    continue
                text = p.text.strip()
                if not text:
                    continue
                if not para_buffer:
                    block_start_para = para_count_total
                para_buffer.append(text)
                para_count_total += 1
                if len(para_buffer) >= page_size:
                    flush_paragraph_block()
            elif child.tag == T_TAG:
                t = next(tables_iter, None)
                if t is None:
                    continue
                flush_paragraph_block()
                rows_text: list[str] = []
                for row in t.rows:
                    row_text = " | ".join(
                        cell.text.strip() for cell in row.cells if cell.text.strip()
                    )
                    if row_text:
                        rows_text.append(row_text)
                if not rows_text:
                    continue
                table_text = "\n".join(rows_text)
                # Tables inherit the page of the most recently flushed
                # paragraph block (or page 1 if the document opens with a table).
                table_page = max(1, (para_count_total // page_size) + 1)
                new_chunks = self._split_with_page(
                    table_text, page_number=table_page, base_index=idx
                )
                idx += len(new_chunks)
                chunks.extend(new_chunks)

        flush_paragraph_block()
        return chunks
