"""Step 9: work out WHO a bank line is from (or paid to).
Bank lines are short and messy: a code ("TF"), a truncated name ("CASSANDRATON PENSION P"), or noise.
Three tries, cheapest and safest first: exact alias -> fuzzy name -> give up and ask a human."""
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, utils

from pipeline.validate import MasterData

FUZZY_MIN = 90   # the distinctive part of the name must score at least this (0-100)...
FUZZY_GAP = 8    # ...and beat the runner-up by this much, or it's ambiguous

# What KIND of investor a name describes. Many investors share these words, so they can't
# identify anyone, but two different kinds can never be the same investor.
KINDS = {"pension": "Pension Plan", "family office": "Family Office", "endowment": "Endowment",
         "foundation": "Foundation", "insurance": "Insurance Co."}


def split_name(legal_name: str) -> tuple[str, str | None]:
    """'Lake Chad Foundation' -> ('Lake Chad', 'Foundation'): the distinctive part and the kind."""
    for kind in KINDS.values():
        if legal_name.endswith(kind):
            return legal_name[: -len(kind)].strip(), kind
    return legal_name, None


def kinds_named(text: str) -> set[str]:
    """Kinds written out in full in the text. A cut-off word like 'PENS' names no kind."""
    lowered = f" {utils.default_process(text)} "
    return {kind for word, kind in KINDS.items() if f" {word} " in lowered}


LINE = re.compile(r"^WIRE (?P<direction>IN|OUT)\s+(?P<payer>.+?)\s+"
                  r"(?:(?:CAP )?CALL (?P<call>\d+)|(?P<dist>DISTRIBUTION))$")


@dataclass
class BankLine:
    kind: str                    # "capital_call", "distribution" or "unrelated"
    payer: str | None = None     # the text that should identify the investor
    call_number: int | None = None


def parse_line(description: str) -> BankLine:
    """Split a bank description into what it is and who it names."""
    found = LINE.match(" ".join(description.split()))      # collapse double spaces first
    if not found:
        return BankLine("unrelated")
    if found["dist"]:
        return BankLine("distribution", found["payer"])
    if found["direction"] == "IN":
        return BankLine("capital_call", found["payer"], int(found["call"]))
    return BankLine("unrelated")


@dataclass
class Match:
    investor_id: str | None
    method: str                  # "alias", "fuzzy" or "none"
    score: float = 0.0
    candidates: list[str] = field(default_factory=list)   # who it could be, when not sure
    reason: str = ""

    @property
    def ambiguous(self) -> bool:
        return self.investor_id is None and len(self.candidates) > 1


def match_investor(text: str, master: MasterData, fund_id: str | None = None) -> Match:
    """Find the investor named by `text`. If fund_id is given, only that fund's investors are considered."""
    allowed = master.investors_in(fund_id) if fund_id else set(master.legal_names)
    cleaned = re.sub(r"[^\w\s]", "", text).strip()        # "N.J.I.C." -> "NJIC"

    # 1. Exact alias: bank code, short name or legal name
    ids = (master.investor_ids(text) | master.investor_ids(cleaned)) & allowed
    if len(ids) == 1:
        return Match(ids.pop(), "alias", 100.0, reason="exact alias")
    if len(ids) > 1:
        return Match(None, "alias", 100.0, sorted(ids), "alias shared by several investors")

    # 2. Fuzzy name: compare only the distinctive part ("Lake Chad"), and rule out a different kind
    stated = kinds_named(text)
    scored = []
    for inv in allowed:
        place, kind = split_name(master.legal_names[inv])
        if stated and kind not in stated:
            continue                                  # text says "Insurance", this one is a Foundation
        score = fuzz.partial_ratio(utils.default_process(place), utils.default_process(text))
        scored.append((score, inv))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < FUZZY_MIN:
        best = f"best was {master.legal_names[scored[0][1]]!r} at {scored[0][0]:.0f}" if scored else "no candidates"
        return Match(None, "none", scored[0][0] if scored else 0.0, reason=f"no confident match ({best})")
    (best_score, best_id), runner_up = scored[0], scored[1] if len(scored) > 1 else None
    if runner_up and best_score - runner_up[0] < FUZZY_GAP:
        return Match(None, "fuzzy", best_score, [best_id, runner_up[1]],
                     f"too close: {best_score:.0f} vs {runner_up[0]:.0f}")
    return Match(best_id, "fuzzy", best_score, reason=f"fuzzy {best_score:.0f}")


if __name__ == "__main__":
    master = MasterData.load()
    for line in ["WIRE IN  TF CAP CALL 1", "WIRE IN  CASSANDRATON PENSION P CALL 1",
                 "WIRE OUT LDPP DISTRIBUTION", "WIRE OUT INVESTMENT DAVIS GROUP", "WIRE IN  JE CAP CALL 2"]:
        parsed = parse_line(line)
        result = match_investor(parsed.payer, master) if parsed.payer else None
        print(f"{line:<42} {parsed.kind:<13} -> {result}")
    print("JE with fund context:", match_investor("JE", master, "FND-002"))