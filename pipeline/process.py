"""Step 13a: the whole per-document pipeline in one function, so the SAME code runs on a laptop
and in AWS Lambda:  read -> (no text? flag) -> classify -> extract -> validate -> a result record.
    python -m pipeline.process data/generated/capital_calls/CC-0001.pdf"""
import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

from pipeline.read import read_pdf
from pipeline.validate import MasterData, validate

EXTRACTED = {"capital_call", "distribution"}          # types with a form (Step 6)


def plain(value):
    """Make a value safe for JSON / DynamoDB: dates -> 'YYYY-MM-DD', Decimal stays exact."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def process_document(path: str | Path, master: MasterData, classify=None, extract=None) -> dict:
    """Run one PDF through the pipeline. Never raises for a bad DOCUMENT (that becomes needs_review);
    it does raise for a broken SERVICE (e.g. the API is down), so the cloud can retry later."""
    if classify is None:
        from pipeline.classify import classify
    if extract is None:
        from pipeline.extract import extract

    path = Path(path)
    record = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "status": "needs_review", "errors": [], "warnings": []}

    read = read_pdf(path)
    record["pages"] = read.pages
    if read.needs_ocr:
        record["errors"].append("no text layer: scanned image, needs OCR")
        return record

    label = classify(read.text)
    record.update(doc_type=label.doc_type, confidence=plain(round(label.confidence, 3)),
                  low_confidence=not label.confident)
    if label.doc_type not in EXTRACTED:              # bank statements are reconciled in batch; others filed
        record["status"] = "filed"
        return record

    result = extract(read.text, label.doc_type)
    if result.error or result.data is None:
        record["errors"].append(f"extraction failed: {result.error}")
        return record
    record["fields"] = {k: plain(v) for k, v in result.data.model_dump().items()}

    check = validate(result.data, master)
    record.update(fund_id=check.fund_id, investor_id=check.investor_id,
                  errors=check.errors, warnings=check.warnings,
                  status="accepted" if check.passed else "needs_review")
    return record


if __name__ == "__main__":
    import json
    import sys

    record = process_document(sys.argv[1], MasterData.load())
    print(json.dumps(record, indent=2, default=str))