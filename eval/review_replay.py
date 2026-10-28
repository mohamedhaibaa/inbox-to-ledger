"""Step 11: run the morning job every day for two months on a fresh queue, and check the rules hold.
A pretend reconciler resolves one item on June 10 to check the system never reopens a person's decision."""
from datetime import date, timedelta
from pathlib import Path

from pipeline.daily import run
from pipeline.review import ReviewQueue

TEST_DB = Path("eval/results/replay.db")


def main(start: date = date(2026, 6, 1), end: date = date(2026, 7, 31)) -> None:
    TEST_DB.unlink(missing_ok=True)
    queue = ReviewQueue(TEST_DB)
    problems, human_resolved = [], None

    day = start
    while day <= end:
        counts = run(day, queue)
        open_now = queue.open_items()
        if day == date(2026, 6, 10):                             # a person deals with the top item
            top = open_now[0]
            queue.resolve(top.id, "Called the investor; wire confirmed for next week", by="mohamed")
            human_resolved = top.id
        if counts["new"] or counts["closed"]:
            print(f"{day}: open {len(queue.open_items()):>2}  (+{counts['new']} new, -{counts['closed']} closed)")
        # Rule 1: the open queue is exactly today's problems, minus what a person resolved
        expected_open = counts["breaks"] + counts["due_soon"] - (1 if human_resolved else 0)
        if len(queue.open_items()) != expected_open:
            problems.append(f"{day}: {len(queue.open_items())} open, expected {expected_open}")
        day += timedelta(days=1)

    history = queue.history()
    keys = [h[0] for h in history]
    if len(keys) != len(set(keys)):                              # Rule 2: never a duplicate
        problems.append("duplicate keys in the queue")
    human = [h for h in history if h[3] == "mohamed"]
    if len(human) != 1 or human[0][2] != "resolved":            # Rule 3: a person's decision stands
        problems.append("the human decision was changed or lost")

    by = {"system": sum(h[3] == "system" for h in history), "person": len(human),
          "open": sum(h[2] == "open" for h in history)}
    print(f"\n{len(history)} items ever created: {by['open']} still open, {by['system']} closed by the system "
          f"(problem went away), {by['person']} resolved by a person")
    print("Rules checked every day: queue = today's problems, no duplicates, human decisions never reopened")
    print("All rules held" if not problems else "PROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()