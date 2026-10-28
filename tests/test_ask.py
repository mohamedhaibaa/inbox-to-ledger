"""Tests for Step 12: retrieval and the answer rules. A fake client stands in for Claude (free, offline)."""
from types import SimpleNamespace

from pipeline.ask import NOT_FOUND, HybridIndex, KeywordIndex, answer

CORPUS = {
    "CC-1": "Harbour Fund. Dear Lake Debra Pension Plan, capital call 1: please pay 500,000.00 by June 15, 2026.",
    "CC-2": "Harbour Fund. Dear Lake Debra Pension Plan, capital call 2: please pay 750,000.00 by Sept 1, 2026.",
    "OT-1": "Harbour Fund annual general meeting invitation: join us in Halifax on May 5, 2026.",
}


class FakeClient:
    def __init__(self, reply):
        self.messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input=reply)]))


class FixedIndex:
    def __init__(self, ids):
        self.ids = ids

    def search(self, question, k=4):
        return self.ids[:k]


def test_keyword_search_tells_call_1_from_call_2():
    """Single characters are kept as words, so the call number counts."""
    index = KeywordIndex(CORPUS)
    assert index.search("Lake Debra capital call 2 amount", 1) == ["CC-2"]
    assert index.search("Lake Debra capital call 1 amount", 1) == ["CC-1"]


def test_hybrid_rewards_documents_both_retrievers_rank_high():
    hybrid = HybridIndex(FixedIndex(["A", "B", "C"]), FixedIndex(["B", "C", "A"]))
    assert hybrid.search("anything", 1) == ["B"]


def test_answer_with_valid_citation_is_kept():
    reply = {"found": True, "answer": "Halifax, on May 5, 2026.", "citations": ["OT-1"]}
    result = answer("Where is the AGM?", KeywordIndex(CORPUS), CORPUS, client=FakeClient(reply))
    assert result.found and result.citations == ["OT-1"]


def test_not_found_is_reported_as_not_found():
    reply = {"found": False, "answer": "Not in the documents.", "citations": []}
    result = answer("Who is the CFO?", KeywordIndex(CORPUS), CORPUS, client=FakeClient(reply))
    assert not result.found and result.text == NOT_FOUND


def test_citing_a_document_it_was_never_given_is_rejected():
    """No valid citation, no answer: a claim that can't be traced to a retrieved source is dropped."""
    reply = {"found": True, "answer": "The fee is 2%.", "citations": ["XX-9"]}
    result = answer("What is the fee?", FixedIndex(["CC-1"]), CORPUS, client=FakeClient(reply))
    assert not result.found and result.text == NOT_FOUND and result.citations == []


def test_only_retrieved_documents_are_sent_to_the_model():
    sent = {}

    class SpyClient(FakeClient):
        def __init__(self):
            super().__init__({"found": False, "answer": NOT_FOUND, "citations": []})
            create = self.messages.create
            self.messages.create = lambda **kw: (sent.update(kw), create(**kw))[1]

    answer("AGM city?", FixedIndex(["OT-1"]), CORPUS, client=SpyClient())
    prompt = sent["messages"][0]["content"]
    assert 'doc_id="OT-1"' in prompt and "CC-1" not in prompt