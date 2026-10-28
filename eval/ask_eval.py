"""Step 12: measure the answers (calls the real API, ~67 small calls).
Outcomes, same idea as 7b:
  correct - right value, citing the right document; or "can't find" for an unanswerable question
  missed  - said "can't find" although the answer was in the documents: safe, unhelpful
  SILENT  - a wrong value, a missing/wrong citation, or an invented answer to an unanswerable question"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from eval.questions import build
from pipeline.ask import KeywordIndex, answer, load_corpus


def mentions(text: str, value: str) -> bool:
    """Does the answer contain the expected value, in any common format?"""
    t = text.lower().replace(",", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):                        # a date
        d = date.fromisoformat(value)
        forms = [value, d.strftime("%B %d %Y"), f"{d.strftime('%B')} {d.day} {d.year}", f"{d.day} {d.strftime('%B')} {d.year}"]
        return any(f.lower().replace(",", "") in t for f in forms)
    if re.fullmatch(r"\d+\.\d{2}", value):                               # an amount
        whole = value.split(".")[0]                                         # "950000" but not "1950000"
        return re.search(rf"(?<!\d){whole}(?!\d)", re.sub(r"\.00\b", "", t)) is not None
    v = value.lower().replace(",", "").replace("$", "")
    return v in t.replace("$", "") or (v.endswith("000000") and f"{v[:-6]} million" in t)


def main(limit: int | None = None) -> None:
    corpus = load_corpus()
    index = KeywordIndex(corpus)
    questions = build()[:limit] if limit else build()
    per_kind, problems = defaultdict(Counter), []

    for q in questions:
        result = answer(q["question"], index, corpus)
        if q["doc_id"] is None:
            outcome = "correct" if not result.found else "SILENT"
        elif not result.found:
            outcome = "missed"
        else:
            values = q["value"] if isinstance(q["value"], list) else [q["value"]]
            docs = q["doc_id"] if isinstance(q["doc_id"], list) else [q["doc_id"]]
            right = all(mentions(result.text, v) for v in values) and all(d in result.citations for d in docs)
            outcome = "correct" if right else "SILENT"
        per_kind[q["kind"]][outcome] += 1
        print(f"{outcome:<8} [{q['kind']}] {q['question'][:70]}")
        if outcome != "correct":
            problems.append({**q, "answer": result.text, "citations": result.citations, "retrieved": result.retrieved})
            print(f"         expected {q['value']} from {q['doc_id']}; got: {result.text[:90]} {result.citations}")

    totals = sum(per_kind.values(), Counter())
    print(f"\nTotal {sum(totals.values())}: correct {totals['correct']}, missed {totals['missed']}, SILENT {totals['SILENT']}")
    for kind, c in sorted(per_kind.items()):
        print(f"  {kind:<17} correct {c['correct']:>2}  missed {c['missed']:>2}  SILENT {c['SILENT']:>2}")
    Path("eval/results/ask.json").write_text(json.dumps({
        "questions": sum(totals.values()), "outcomes": dict(totals),
        "per_kind": {k: dict(v) for k, v in per_kind.items()}, "problems": problems}, indent=2))
    print("\nSaved -> eval/results/ask.json")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)