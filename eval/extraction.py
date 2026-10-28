"""Measure extraction accuracy on the held-out test documents (calls the real API)."""
import json
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from pipeline import extract as extract_module

GEN = Path("data/generated")
RESULTS = Path("eval/results")
FIELDS = {
    "capital_call": ["fund_name", "investor_name", "call_number", "amount", "due_date", "reference"],
    "distribution": ["fund_name", "investor_name", "amount", "payment_date", "distribution_type"],
}


def expected(key: dict, field: str):
    """The correct value from the answer key. Investor = the name as printed on the page."""
    if field == "investor_name":
        return key.get("investor_name_shown", key["investor_name"])
    return key[field]


def same(field: str, got, want) -> bool:
    if got is None:
        return False
    if field == "amount":
        return Decimal(str(got)) == Decimal(want)          # exact to the cent
    if isinstance(got, date):
        return got.isoformat() == want
    return str(got).strip().lower() == str(want).strip().lower()   # ignore capitals/spaces


def main(limit: int | None = None) -> None:
    test_ids = json.loads((GEN / "split.json").read_text())["test"]
    ids = [i for i in test_ids if i[:2] in ("CC", "DN")][:limit]

    per_field = defaultdict(lambda: [0, 0])     # field -> [correct, total]
    per_layout = defaultdict(lambda: [0, 0])    # layout -> [fully correct docs, docs]
    failures = []

    for doc_id in ids:
        key = json.loads((GEN / "answer_keys" / f"{doc_id}.json").read_text())
        text = (GEN / "text" / f"{doc_id}.txt").read_text()
        result = extract_module.extract(text, key["doc_type"])

        doc_ok = True
        for field in FIELDS[key["doc_type"]]:
            got = getattr(result.data, field, None) if result.data else None
            ok = same(field, got, expected(key, field))
            per_field[field][0] += ok
            per_field[field][1] += 1
            if not ok:
                doc_ok = False
                failures.append({"doc_id": doc_id, "field": field,
                                 "expected": expected(key, field),
                                 "got": None if got is None else str(got),
                                 "error": result.error})
        per_layout[key["layout"]][0] += doc_ok
        per_layout[key["layout"]][1] += 1
        print(f"{doc_id}: {'all fields correct' if doc_ok else 'MISMATCH'}")

    fields_ok = sum(c for c, _ in per_field.values())
    fields_all = sum(t for _, t in per_field.values())
    docs_ok = sum(c for c, _ in per_layout.values())
    print(f"\nDocuments fully correct: {docs_ok}/{len(ids)} ({docs_ok / len(ids):.1%})")
    print(f"Field-level accuracy:    {fields_ok}/{fields_all} ({fields_ok / fields_all:.1%})\n")
    print("Per field:")
    for field, (c, t) in per_field.items():
        print(f"  {field:<18} {c}/{t}  {c / t:.0%}")
    print("Per layout (documents fully correct):")
    for layout, (c, t) in sorted(per_layout.items()):
        print(f"  {layout:<18} {c}/{t}  {c / t:.0%}")
    if failures:
        print(f"\n{len(failures)} wrong field(s), first few:")
        for f in failures[:10]:
            print(f"  {f['doc_id']} {f['field']}: expected {f['expected']!r}, got {f['got']!r}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "extraction.json").write_text(json.dumps({
        "model": extract_module.MODEL, "documents": len(ids), "documents_fully_correct": docs_ok,
        "field_accuracy": round(fields_ok / fields_all, 4),
        "per_field": {f: {"correct": c, "total": t} for f, (c, t) in per_field.items()},
        "per_layout": {l: {"correct": c, "total": t} for l, (c, t) in per_layout.items()},
        "failures": failures}, indent=2))
    print(f"\nSaved -> {RESULTS / 'extraction.json'}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)