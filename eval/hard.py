"""Step 7b: run the WHOLE pipeline (read -> classify -> extract -> validate) on the hard set.
Three outcomes per document:
  correct  - right answer (data extracted correctly, or a bad document flagged)
  flagged  - a good document sent to a human: safe, costs a person a minute
  SILENT   - wrong data accepted, or a bad document let through: the only dangerous outcome
Calls the real API."""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from eval.extraction import FIELDS, same
from pipeline import extract as extract_module
from pipeline.classify import CONFIDENCE_THRESHOLD, classify
from pipeline.read import read_pdf
from pipeline.validate import MasterData, validate

HARD = Path("data/generated/hard")
KEYS = Path("data/generated/hard_keys")
RESULTS = Path("eval/results")


def run_one(path: Path, master: MasterData, seen: set, recorded: set, extract=None) -> dict:
    """Push one PDF through the pipeline. Returns what happened, without looking at the answer key."""
    extract = extract or extract_module.extract

    digest = hashlib.sha256(path.read_bytes()).hexdigest()       # same bytes = same file
    if digest in seen:
        return {"flagged": "duplicate file"}
    seen.add(digest)

    read = read_pdf(path)
    if read.needs_ocr:
        return {"flagged": "no text layer (needs OCR)"}

    label = classify(read.text)
    out = {"doc_type": label.doc_type, "confidence": round(label.confidence, 2),
           "low_confidence": not label.confident}

    result = extract(read.text, label.doc_type)
    if result.error or result.data is None:
        return {**out, "flagged": f"extraction failed: {result.error}"}
    out["data"] = result.data

    check = validate(result.data, master, recorded)
    if not check.passed:
        return {**out, "flagged": "; ".join(check.errors)}
    if result.data.call_number is not None:
        recorded.add((check.fund_id, check.investor_id, result.data.call_number))
    return out


def main(extract=None) -> None:
    master = MasterData.load()
    seen, recorded = set(), set()
    per_challenge = defaultdict(lambda: defaultdict(int))   # challenge -> outcome -> count
    low_conf, problems = 0, []

    for key_file in sorted(KEYS.glob("*.json")):
        key = json.loads(key_file.read_text())
        got = run_one(HARD / f"{key['doc_id']}.pdf", master, seen, recorded, extract)
        low_conf += got.get("low_confidence", False)

        if key["expect"] == "flag":
            outcome = "correct" if "flagged" in got else "SILENT"
            why = got.get("flagged") or "let through, should have been flagged"
        elif "flagged" in got:
            outcome, why = "flagged", got["flagged"]
        else:
            wrong = [f for f in FIELDS["capital_call"]
                     if not same(f, getattr(got["data"], f, None), key[f])]
            outcome = "SILENT" if wrong else "correct"
            why = ("; ".join(f"{f}: expected {key[f]!r}, got {str(getattr(got['data'], f, None))!r}"
                                    for f in wrong) if wrong else "all fields correct")

        per_challenge[key["challenge"]][outcome] += 1
        print(f"{key['doc_id']} {key['challenge']:<17} {outcome:<8} {why[:110]}")
        if outcome != "correct":
            problems.append({"doc_id": key["doc_id"], "challenge": key["challenge"],
                             "outcome": outcome, "detail": why})

    totals = defaultdict(int)
    for counts in per_challenge.values():
        for outcome, n in counts.items():
            totals[outcome] += n
    total = sum(totals.values())
    print(f"\nCorrect:            {totals['correct']}/{total}")
    print(f"Flagged for human:  {totals['flagged']}/{total}  (safe, just slower)")
    print(f"SILENT errors:      {totals['SILENT']}/{total}  (the number that must be 0)")
    print(f"Classifier below {CONFIDENCE_THRESHOLD:.0%} confidence: {low_conf}")
    print("\nPer challenge (correct / flagged / SILENT):")
    for name, c in sorted(per_challenge.items()):
        print(f"  {name:<18} {c['correct']} / {c['flagged']} / {c['SILENT']}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "hard.json").write_text(json.dumps({
        "model": extract_module.MODEL, "documents": total, "outcomes": dict(totals),
        "low_confidence": low_conf, "per_challenge": {n: dict(c) for n, c in per_challenge.items()},
        "problems": problems}, indent=2))
    print(f"\nSaved -> {RESULTS / 'hard.json'}")


if __name__ == "__main__":
    main()