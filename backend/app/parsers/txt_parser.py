from app.parsers.base import BaseParser, ParsedChunk


class TXTParser(BaseParser):
    def extract_chunks(self, file_path: str) -> list[ParsedChunk]:
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        text = ""
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    text = f.read()
                break
            except (UnicodeDecodeError, ValueError):
                continue

        if not text.strip():
            return []

        return self._split_with_page(text.strip(), page_number=1, base_index=0)
