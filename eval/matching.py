"""Step 9: measure the investor matcher.
Part A: every real bank line in the 10 statements (answer keys say which document each line pays).
Part B: a hard set of name variants, including near-misses that must NOT match.
Same three outcomes as Step 7b: correct / flagged (sent to a human) / SILENT (wrong investor)."""
import json
import random
from collections import defaultdict
from pathlib import Path

from pipeline.match import match_investor, parse_line
from pipeline.validate import MasterData

KEYS = Path("data/generated/answer_keys")
RESULTS = Path("eval/results")
SUFFIXES = ["Pension Plan", "Family Office", "Endowment", "Foundation", "Insurance Co."]


def score(expected: str | None, got) -> str:
    if got.investor_id is None:
        return "correct" if expected is None else "flagged"
    return "correct" if got.investor_id == expected else "SILENT"


def real_lines(master: MasterData) -> list[dict]:
    """Bank lines from the statements, with the investor they really belong to."""
    cases = []
    for statement in sorted(KEYS.glob("BS-*.json")):
        key = json.loads(statement.read_text())
        for line in key["lines"]:
            parsed = parse_line(line["description"])
            expected = None
            if line["matches_doc"]:
                expected = json.loads((KEYS / f"{line['matches_doc']}.json").read_text())["investor_id"]
            cases.append({"group": "real:" + ("named" if expected else "noise"), "text": line["description"],
                          "fund_id": key["fund_id"], "expected": expected, "parsed": parsed})
    return cases


def typo(name: str, rng: random.Random) -> str:
    """One random keyboard slip in the longest word: a letter dropped, swapped or doubled."""
    words = name.split()
    i = max(range(len(words)), key=lambda w: len(words[w]))
    w = words[i]
    j = rng.randint(1, len(w) - 3)
    words[i] = rng.choice([w[:j] + w[j + 1:],                          # dropped
                           w[:j] + w[j + 1] + w[j] + w[j + 2:],        # swapped
                           w[:j] + w[j] + w[j:]])                      # doubled
    return " ".join(words)


def hard_variants(master: MasterData, seed: int, tag: str) -> list[dict]:
    """Name variants a real bank or person might write.
    "dev" variants were used while choosing the rules; "test" variants (another seed) only to confirm them."""
    rng = random.Random(seed)
    funds_of = defaultdict(list)
    for fund, inv in master.commitments:
        funds_of[inv].append(fund)
    cases = []
    for inv, name in sorted(master.legal_names.items()):
        fund = rng.choice(funds_of[inv])
        acronym = "".join(w[0] for w in name.replace(".", "").split()).upper()
        last = next((s for s in SUFFIXES if name.endswith(s)), None)
        variants = {
            "truncated": name.upper()[:rng.randint(12, 20)],
            "typo": typo(name, rng),
            "no_suffix": name[: -len(last)].strip() if last else name,
            "extra_words": rng.choice(["THE {} LTD", "{} INC", "ATTN {}", "{} - WIRE"]).format(name.upper()),
            "dotted_code": ".".join(acronym) + ".",
            "lowercase": name.lower(),
        }
        for group, text in variants.items():
            cases.append({"group": f"{tag}:{group}", "text": text, "fund_id": fund, "expected": inv})

        # Near-miss: same place name, different kind of investor that does NOT exist
        if last:
            other = rng.choice([s for s in SUFFIXES if s != last])
            fake = name[: -len(last)] + other
            if not master.investor_ids(fake):
                cases.append({"group": f"{tag}:near_miss", "text": fake, "fund_id": fund, "expected": None})

        # Real investor, wrong fund: they have no commitment there, so it must not be credited
        outside = [f for f in {f for f, _ in master.commitments} if f not in funds_of[inv]]
        if outside:
            cases.append({"group": f"{tag}:not_in_fund", "text": name, "fund_id": rng.choice(sorted(outside)),
                          "expected": None})

    for stranger in ["Northwind Capital Partners", "Bluepeak Holdings Ltd.", "Davis Group", "Smith & Co"]:
        cases.append({"group": f"{tag}:unknown", "text": stranger, "fund_id": "FND-001", "expected": None})
    return cases


def main() -> None:
    master = MasterData.load()
    per_group = defaultdict(lambda: defaultdict(int))
    problems = []

    cases = real_lines(master) + hard_variants(master, seed=11, tag="dev")
    cases += hard_variants(master, seed=23, tag="test")
    for case in cases:
        parsed = case.get("parsed")
        if parsed is not None and parsed.payer is None:            # noise line: nothing to match
            outcome, detail = ("correct", "ignored") if case["expected"] is None else ("flagged", "not parsed")
        else:
            text = parsed.payer if parsed is not None else case["text"]
            got = match_investor(text, master, case["fund_id"])
            outcome, detail = score(case["expected"], got), f"{got.method}: {got.reason}"
            if outcome != "correct":
                problems.append({**{k: case[k] for k in ("group", "text", "fund_id", "expected")},
                                 "got": got.investor_id, "outcome": outcome, "detail": detail})
        per_group[case["group"]][outcome] += 1

    totals = defaultdict(int)
    print(f"{'group':<20}{'correct':>8}{'flagged':>9}{'SILENT':>8}")
    for group, counts in sorted(per_group.items()):
        print(f"{group:<20}{counts['correct']:>8}{counts['flagged']:>9}{counts['SILENT']:>8}")
        for outcome, n in counts.items():
            totals[outcome] += n
    total = sum(totals.values())
    print(f"\nTotal: {totals['correct']}/{total} correct, {totals['flagged']} flagged, "
          f"{totals['SILENT']} SILENT")
    for p in [p for p in problems if p["outcome"] == "SILENT"] + [p for p in problems if p["outcome"] != "SILENT"][:8]:
        print(f"  {p['outcome']:<8} {p['group']:<17} {p['text']!r:<36} expected {p['expected']}, got {p['got']} ({p['detail']})")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "matching.json").write_text(json.dumps({
        "cases": total, "outcomes": dict(totals),
        "per_group": {g: dict(c) for g, c in per_group.items()}, "problems": problems}, indent=2))
    print(f"\nSaved -> {RESULTS / 'matching.json'}")


if __name__ == "__main__":
    main()