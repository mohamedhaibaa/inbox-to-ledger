"""Step 12: build a question set with known answers, from the answer keys and the documents' own text.
Each question names the document that holds the answer, and the value the answer must contain.
"Unanswerable" questions have no document: the right answer is "I can't find that".
"Conflict" questions have two documents that disagree: the right answer gives both values and cites both."""
import json
import random
import re
from collections import Counter
from pathlib import Path

KEYS = Path("data/generated/answer_keys")
TEXT = Path("data/generated/text")
ORDINAL = {1: "first", 2: "second", 3: "third", 4: "fourth"}


def build(seed: int = 12) -> list[dict]:
    rng = random.Random(seed)
    keys = {p.stem: json.loads(p.read_text()) for p in sorted(KEYS.glob("*.json"))}
    investors = {r.split(",")[0]: r.split(",") for r in Path("data/master/investors.csv").read_text().splitlines()[1:]}
    qs = []

    calls = [k for k in keys.values() if k["doc_type"] == "capital_call"]
    for k in rng.sample(calls, 15):
        code = investors[k["investor_id"]][3]
        qs.append({"kind": "call_exact", "doc_id": k["doc_id"], "value": k["amount"],
                   "question": f"How much does {k['investor_name']} owe for capital call {k['call_number']} "
                               f"of {k['fund_name']}?"})
        qs.append({"kind": "call_paraphrase", "doc_id": k["doc_id"], "value": k["due_date"],
                   "question": f"By what date does {code} have to send money for its "
                               f"{ORDINAL[k['call_number']]} drawdown in {k['fund_name'].rsplit(' ', 1)[0]}?"})

    dists = [k for k in keys.values() if k["doc_type"] == "distribution"]
    pairs = Counter((k["fund_name"], k["investor_name"]) for k in dists)
    for k in rng.sample([k for k in dists if pairs[(k["fund_name"], k["investor_name"])] == 1], 10):
        qs.append({"kind": "distribution", "doc_id": k["doc_id"], "value": k["payment_date"],
                   "question": f"On what date will {k['fund_name']} pay out to {k['investor_name']}?"})

    quarterly = {}                                      # (fund, quarter) -> [(doc_id, pct)]
    for doc_id, k in keys.items():                      # facts that only exist as prose
        if k.get("doc_type") != "other":
            continue
        text = " ".join((TEXT / f"{doc_id}.txt").read_text().split())
        fund = text.split(" Annual General")[0].split(" Q")[0]
        if k["subtype"] == "agm":
            city = re.search(r"general meeting on .+? \d{4} at (.+?)\.", text)[1]
            qs.append({"kind": "prose_agm", "doc_id": doc_id, "value": city,
                       "question": f"In which city will {fund} hold its annual general meeting?"})
        elif k["subtype"] == "quarterly":
            pct = re.search(r"represents (\d+)% of total commitments", text)[1] + "%"
            qtr = re.search(r"(Q\d) 2026 Quarterly Report", text)[1]
            quarterly.setdefault((fund, qtr), []).append((doc_id, pct))
        elif k["subtype"] == "marketing":
            name = re.search(r"Introducing the (.+? Opportunities Fund)", text)[1]
            minimum = re.search(r"Minimum commitment: (\$[\d,]+)", text)[1]
            qs.append({"kind": "prose_marketing", "doc_id": doc_id, "value": minimum,
                       "question": f"What is the minimum commitment to invest in the {name}?"})

    for (fund, qtr), reports in quarterly.items():
        question = f"According to its {qtr} 2026 report, what share of commitments has {fund} called?"
        if len(reports) == 1:
            qs.append({"kind": "prose_quarterly", "doc_id": reports[0][0], "value": reports[0][1], "question": question})
        else:                                           # two reports for the same quarter that disagree
            qs.append({"kind": "conflict", "doc_id": [d for d, _ in reports], "value": [v for _, v in reports],
                       "question": question})

    funds = sorted({k["fund_name"] for k in calls})
    for fund in rng.sample(funds, 5):
        for q in [f"What management fee percentage does {fund} charge?",
                  f"Who is the chief financial officer of {fund}?"]:
            qs.append({"kind": "unanswerable", "doc_id": None, "value": None, "question": q})
    return qs


if __name__ == "__main__":
    questions = build()
    Path("eval/questions.json").write_text(json.dumps(questions, indent=2))
    print(Counter(q["kind"] for q in questions))
    for q in questions[:3] + questions[-3:]:
        print(f"  [{q['kind']}] {q['question']}  -> {q['doc_id']}: {q['value']}")