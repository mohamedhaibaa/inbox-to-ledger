"""Tests for Step 11: the review queue. Each test uses its own throwaway database file."""
from decimal import Decimal

import pytest

from pipeline.review import ReviewQueue, priority


@pytest.fixture
def queue(tmp_path):
    return ReviewQueue(tmp_path / "review.db")


def test_same_problem_twice_is_stored_once(queue):
    assert queue.add("unpaid:CC-1", "unpaid", "nothing received") is True
    assert queue.add("unpaid:CC-1", "unpaid", "nothing received") is False
    assert len(queue.open_items()) == 1


def test_highest_priority_first(queue):
    queue.add("due_soon:CC-1", "due_soon", "due in 3 days", amount=Decimal("900000"))
    queue.add("unpaid:CC-2", "unpaid", "nothing received", amount=Decimal("100000"))
    queue.add("partial:CC-3", "partial", "short", amount=Decimal("500000"))
    assert [i.kind for i in queue.open_items()] == ["unpaid", "partial", "due_soon"]


def test_amount_breaks_ties_but_never_outranks_kind():
    assert priority("partial", Decimal("900000")) > priority("partial", Decimal("100000"))
    assert priority("unpaid", Decimal("1")) > priority("partial", Decimal("50000000"))
    assert priority("extraction", Decimal("1")) > priority("late", Decimal("50000000"))


def test_resolving_needs_a_note(queue):
    queue.add("unpaid:CC-1", "unpaid", "nothing received")
    item = queue.open_items()[0]
    with pytest.raises(ValueError):
        queue.resolve(item.id, "   ", by="mohamed")


def test_a_person_s_decision_is_never_reopened(queue):
    queue.add("unpaid:CC-1", "unpaid", "nothing received")
    queue.resolve(queue.open_items()[0].id, "investor confirmed wire", by="mohamed")
    queue.add("unpaid:CC-1", "unpaid", "nothing received")          # tomorrow's run finds it again
    assert queue.open_items() == []


def test_problems_that_went_away_are_closed_by_the_system(queue):
    queue.add("due_soon:CC-1", "due_soon", "due in 2 days")
    queue.add("unpaid:CC-2", "unpaid", "nothing received")
    closed = queue.close_missing({"unpaid:CC-2"}, "2026-07-01")      # CC-1 got paid
    assert closed == 1
    assert [i.doc_id for i in queue.open_items()] == [None] and queue.open_items()[0].kind == "unpaid"
    assert ("due_soon:CC-1", "due_soon", "resolved", "system", "no longer present in the 2026-07-01 run") \
        in queue.history()


def test_system_never_touches_what_a_person_resolved(queue):
    queue.add("partial:CC-1", "partial", "short")
    queue.resolve(queue.open_items()[0].id, "agreed: rest comes next month", by="mohamed")
    queue.close_missing(set(), "2026-07-01")
    assert queue.history()[0][3:] == ("mohamed", "agreed: rest comes next month")