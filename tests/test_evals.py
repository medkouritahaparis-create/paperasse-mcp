import re

import pytest

import main
from evals.run import accuracy, load_questions, run_one, score


@pytest.fixture(scope="module")
def questions():
    return load_questions()


def test_question_set_is_well_formed(questions):
    assert len(questions) >= 50
    assert len({q["id"] for q in questions}) == len(questions)
    assert len({q["question"].lower() for q in questions}) == len(questions)
    for q in questions:
        assert q["question"].strip()
        assert q["style"] in ("keywords", "sentence")
        assert all(re.fullmatch(r"F\d+", fid) for fid in q["expected"])
    assert sum(1 for q in questions if not q["expected"]) >= 5  # no-match questions


def _run(rank, low=False, style="keywords", expected=("F1",)):
    return {"expected": list(expected), "rank": rank, "low_confidence": low, "no_results": False, "style": style}


def test_accuracy_counts_top1_top3_and_mrr():
    a = accuracy([_run(1), _run(2), _run(4), _run(None)])
    assert (a["n"], a["top1"], a["top3"]) == (4, 1, 2)
    assert a["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 4) / 4)


def test_score_separates_false_alarms_from_useful_warnings():
    s = score([
        _run(1, low=True),               # right but flagged: false alarm
        _run(1),                         # right, not flagged
        _run(3, low=True, style="sentence"),  # wrong at rank 1, flagged: useful warning
        _run(None, expected=(), low=True),    # no-match, flagged
        _run(None, expected=()),              # no-match, missed
    ])
    assert (s["false_alarms"], s["rank1_right"]) == (1, 2)
    assert (s["useful_warnings"], s["rank1_wrong"]) == (1, 1)
    assert (s["nomatch_flagged"], s["nomatch"]) == (1, 2)
    assert s["keywords"]["n"] == 2 and s["sentence"]["n"] == 1


def test_run_one_finds_rank_of_any_expected_id(monkeypatch, store):
    monkeypatch.setattr(main, "_store", lambda: store)
    r = run_one({"question": "aide logement étudiant", "expected": ["F404", "F1"], "style": "keywords"})
    assert r["rank"] == 1 and r["low_confidence"] is False
    r = run_one({"question": "zzzinconnu", "expected": [], "style": "keywords"})
    assert r["no_results"] is True and r["rank"] is None
