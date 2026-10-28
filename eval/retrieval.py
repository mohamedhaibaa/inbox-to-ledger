"""Step 12: measure retrieval alone (no LLM, free): is the right document in the top 1 / top 4?
    python -m eval.retrieval            keyword only
    python -m eval.retrieval all        keyword, embedding and hybrid (needs sentence-transformers)"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from eval.questions import build
from pipeline.ask import EmbeddingIndex, HybridIndex, KeywordIndex, load_corpus


def score(index, questions) -> dict[str, list[int]]:
    per_kind = defaultdict(lambda: [0, 0, 0])            # kind -> [hit@1, hit@4, total]
    for q in questions:
        if q["doc_id"] is None:
            continue
        found = index.search(q["question"], 4)
        wanted = q["doc_id"] if isinstance(q["doc_id"], list) else [q["doc_id"]]
        per_kind[q["kind"]][0] += found[0] in wanted
        per_kind[q["kind"]][1] += all(d in found for d in wanted)        # a conflict needs BOTH documents
        per_kind[q["kind"]][2] += 1
    return per_kind


def main(which: str = "keyword") -> None:
    corpus, questions = load_corpus(), build()
    indexes = {"keyword": KeywordIndex(corpus)}
    if which == "all":
        indexes["embedding"] = EmbeddingIndex(corpus)
        indexes["hybrid"] = HybridIndex(indexes["keyword"], indexes["embedding"])

    results = {}
    for name, index in indexes.items():
        per_kind = score(index, questions)
        total = [sum(v[i] for v in per_kind.values()) for i in range(3)]
        results[name] = {"hit@1": total[0], "hit@4": total[1], "questions": total[2],
                         "per_kind": {k: v for k, v in per_kind.items()}}
        print(f"\n{name}: right document first {total[0]}/{total[2]}, in top 4 {total[1]}/{total[2]}")
        for kind, (h1, h4, n) in sorted(per_kind.items()):
            print(f"  {kind:<17} top1 {h1:>2}/{n:<3} top4 {h4:>2}/{n}")
    Path("eval/results").mkdir(parents=True, exist_ok=True)
    Path("eval/results/retrieval.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "keyword")