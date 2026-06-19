import openpyxl
from app.parsers.base import BaseParser, ParsedChunk


class XLSXParser(BaseParser):
    def extract_chunks(self, file_path: str) -> list[ParsedChunk]:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        chunks: list[ParsedChunk] = []
        idx = 0

        for sheet_num, sheet in enumerate(wb.worksheets, start=1):
            rows_text: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip()]
                if cells:
                    rows_text.append(" | ".join(cells))

            if not rows_text:
                continue

            block = f"[Sheet: {sheet.title}]\n" + "\n".join(rows_text)
            new_chunks = self._split_with_page(block, page_number=sheet_num, base_index=idx)
            idx += len(new_chunks)
            chunks.extend(new_chunks)

         
        wb.close()
        return chunks
