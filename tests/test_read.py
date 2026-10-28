"""Tests for Step 4: reading PDFs."""
from reportlab.pdfgen import canvas

from pipeline.read import read_pdf


def make_pdf(path, lines, font="Helvetica"):
    c = canvas.Canvas(str(path))
    c.setFont(font, 10)
    y = 750
    for line in lines:
        c.drawString(60, y, line)
        y -= 16
    c.save()


def test_reads_text_from_pdf(tmp_path):
    """A normal PDF must come back as readable text, not drawing instructions."""
    pdf = tmp_path / "call.pdf"
    make_pdf(pdf, ["CAPITAL CALL NOTICE #3", "Amount of this call: $250,000.00"])
    result = read_pdf(pdf)
    assert "CAPITAL CALL NOTICE #3" in result.text
    assert "$250,000.00" in result.text
    assert result.needs_ocr is False


def test_blank_pdf_is_flagged_for_ocr(tmp_path):
    """A PDF with no text layer (like a scan) must be flagged, not silently returned empty."""
    pdf = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(pdf))
    c.showPage()
    c.save()
    assert read_pdf(pdf).needs_ocr is True


def test_statement_columns_keep_their_spacing(tmp_path):
    """Money in and money out must stay in separate columns, or reconciliation can't tell them apart."""
    pdf = tmp_path / "statement.pdf"
    make_pdf(pdf, [f"{'Date':<8}{'Description':<44}{'In':>16}{'Out':>16}",
                   f"{'Feb 01':<8}{'AUDIT FEES':<44}{'':>16}{'9,295.00':>16}"], font="Courier")
    lines = read_pdf(pdf).text.splitlines()
    header = next(line for line in lines if "Description" in line)
    fee = next(line for line in lines if "AUDIT FEES" in line)
    assert fee.index("9,295.00") > header.index("In")   # sits under Out, not In