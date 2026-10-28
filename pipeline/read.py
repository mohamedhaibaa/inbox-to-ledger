"""Step 4: turn a PDF into plain text the rest of the pipeline can use."""
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


@dataclass
class ReadResult:
    path: str
    text: str
    pages: int
    needs_ocr: bool


def read_pdf(path: str | Path) -> ReadResult:
    """Extract text from every page, keeping column spacing (important for bank statements)."""
    path = Path(path)
    page_texts = []
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            raw = page.extract_text(layout=True) or ""
            lines = [line.rstrip() for line in raw.splitlines()]
            page_texts.append(textwrap.dedent("\n".join(lines)).strip("\n"))
    text = "\n\n".join(t for t in page_texts if t.strip())
    return ReadResult(path=str(path), text=text, pages=pages, needs_ocr=not text.strip())


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "data" / "generated"
    out = root / "text"
    out.mkdir(exist_ok=True)
    count = needs_ocr = 0
    for pdf_path in sorted(root.glob("*/*.pdf")):
        result = read_pdf(pdf_path)
        (out / f"{pdf_path.stem}.txt").write_text(result.text)
        count += 1
        needs_ocr += result.needs_ocr
    print(f"Read {count} PDFs -> {out} ({needs_ocr} need OCR)")