"""Search eval: run evals/questions.jsonl through search_fiche and score it.

Answerable questions (non-empty `expected`): top-1 and top-3 accuracy, and MRR
over the top 10 (a hit at rank r scores 1/r). Any of the expected ids counts.
Reported overall and by `style`: "keywords" (what clients are told to send) vs
"sentence" (how people phrase it, sent as is).

Each question has a `split`: "dev" questions are the ones search settings are
tuned on; "test" questions are only looked at to report results (see
docs/decisions.md). Scores are given per split.

low_confidence: on no-match questions (`expected: []`), whether search flags
them (low_confidence, or no results). On answerable questions, a flag when the
rank-1 result is correct is a false alarm; a flag when it is wrong is a useful
warning.

Usage: uv run python -m evals.run [--no-save]
Writes evals/results/<date>-<search code commit>-q<question set hash>.md unless --no-save.
"""

from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

import main
from paperasse.store import MIN_CONFIDENT_MATCH

EVALS_DIR = Path(__file__).resolve().parent
QUESTIONS = EVALS_DIR / "questions.jsonl"
RESULTS_DIR = EVALS_DIR / "results"
DEPTH = 10  # results fetched per question, for MRR
SPLITS = ("dev", "test")


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_one(q: dict) -> dict:
    """Search one question. Returns ids, titles, rank of the first expected id, flags."""
    try:
        out = main.search_fiche(q["question"], limit=DEPTH)
        results, low = out["results"], out["low_confidence"]
    except ToolError:
        results, low = [], None  # no results at all
    ids = [r["id"] for r in results]
    rank = next((i for i, fid in enumerate(ids, 1) if fid in q["expected"]), None)
    return {
        **q,
        "ids": ids,
        "titles": [r["title"] for r in results],
        "matches": [r["match"] for r in results],
        "rank": rank,
        "low_confidence": low,
        "no_results": not results,
    }


def _flagged(r: dict) -> bool:
    return bool(r["no_results"] or r["low_confidence"])


def accuracy(ans: list[dict]) -> dict:
    n = len(ans)
    return {
        "n": n,
        "top1": sum(r["rank"] == 1 for r in ans),
        "top3": sum(r["rank"] is not None and r["rank"] <= 3 for r in ans),
        "mrr": sum(1 / r["rank"] for r in ans if r["rank"]) / n if n else 0.0,
    }


def score(runs: list[dict]) -> dict:
    """Scores over all runs, plus the same scores per split under "splits"."""
    out = _score(runs)
    out["splits"] = {sp: _score([r for r in runs if r.get("split") == sp]) for sp in SPLITS}
    return out


def _score(runs: list[dict]) -> dict:
    ans = [r for r in runs if r["expected"]]
    nomatch = [r for r in runs if not r["expected"]]
    right = [r for r in ans if r["rank"] == 1]
    wrong = [r for r in ans if r["rank"] != 1]
    return {
        "all": accuracy(ans),
        "keywords": accuracy([r for r in ans if r["style"] == "keywords"]),
        "sentence": accuracy([r for r in ans if r["style"] == "sentence"]),
        "freelance": accuracy([r for r in ans if r["category"] == "freelance"]),
        "nomatch": len(nomatch),
        "nomatch_flagged": sum(_flagged(r) for r in nomatch),
        "rank1_right": len(right),
        "false_alarms": sum(_flagged(r) for r in right),
        "rank1_wrong": len(wrong),
        "useful_warnings": sum(_flagged(r) for r in wrong),
    }


def check_labels(questions: list[dict]) -> list[str]:
    """Expected ids that are not in the database (labels gone stale after a feed update)."""
    store = main._store()
    return [f"{q['id']}: {fid}" for q in questions for fid in q["expected"] if store.get(fid) is None]


SEARCH_CODE = ["main.py", "paperasse/"]  # what the numbers depend on, besides the data


def _git_commit() -> str:
    """Last commit of the search code, flagged if that code has uncommitted changes."""
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=EVALS_DIR.parent).stdout.strip()

    try:
        sha = git("log", "-1", "--format=%h", "--", *SEARCH_CODE)
        dirty = git("status", "--porcelain", "--", *SEARCH_CODE)
        return sha + (" + uncommitted changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def questions_hash(path: Path = QUESTIONS) -> str:
    """Short hash of the question set, so reports on different sets never overwrite each other."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:6]


def _data_snapshot() -> str:
    conn = main._store().conn
    count, latest = conn.execute("SELECT count(*), max(updated_at) FROM fiches").fetchone()
    return f"{count} fiches, latest fiche update {latest}"


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "n/a"


def report(runs: list[dict], s: dict) -> str:
    lines = [
        f"# Search eval — {dt.date.today().isoformat()}",
        "",
        f"- Search code (`main.py`, `paperasse/`): `{_git_commit()}`",
        f"- Data: {_data_snapshot()}",
        f"- Questions: {len(runs)} ({s['all']['n']} answerable, {s['nomatch']} with no good match), "
        f"set `{questions_hash()}`: "
        + ", ".join(f"{sp} {s['splits'][sp]['all']['n']} answerable" for sp in SPLITS)
        + f"; low_confidence threshold {MIN_CONFIDENT_MATCH}",
        "",
        "## Ranking",
        "",
        "\"Keywords\" is what clients are told to send (\"APL étudiant\"); \"sentence\" is a question "
        "as people phrase it, sent as is (\"Comment avoir un garant gratuit pour louer ?\"). "
        "\"Freelance\" overlaps both. Settings are tuned on dev; test is only reported.",
        "",
        f"| Split | Questions | n | Top-1 | Top-3 | MRR@{DEPTH} |",
        "|---|---|---|---|---|---|",
    ]
    for split_label, sc in (("dev", s["splits"]["dev"]), ("**test**", s["splits"]["test"]), ("all", s)):
        for label, key in (("Keywords", "keywords"), ("Sentence", "sentence"),
                           ("Freelance", "freelance"), ("**All**", "all")):
            a = sc[key]
            lines.append(f"| {split_label} | {label} | {a['n']} | {_pct(a['top1'], a['n'])} | "
                         f"{_pct(a['top3'], a['n'])} | {a['mrr']:.2f} |")
    flagged = lambda num, den: " | ".join(_pct(s["splits"][sp][num], s["splits"][sp][den]) for sp in SPLITS)
    lines += [
        "",
        "## low_confidence",
        "",
        "| Situation | Flagged (dev) | Flagged (test) |",
        "|---|---|---|",
        f"| No good match exists (off-topic, English): should be flagged | {flagged('nomatch_flagged', 'nomatch')} |",
        f"| Rank-1 result is wrong: flag is a useful warning | {flagged('useful_warnings', 'rank1_wrong')} |",
        f"| Rank-1 result is right: flag is a false alarm | {flagged('false_alarms', 'rank1_right')} |",
        "",
        "## By category",
        "",
        "| Category | Answerable | Top-1 | Top-3 |",
        "|---|---|---|---|",
    ]
    by_cat = collections.defaultdict(list)
    for r in runs:
        if r["expected"]:
            by_cat[r["category"]].append(r)
    for cat, rs in sorted(by_cat.items()):
        t1 = sum(r["rank"] == 1 for r in rs)
        t3 = sum(r["rank"] is not None and r["rank"] <= 3 for r in rs)
        lines.append(f"| {cat} | {len(rs)} | {t1} | {t3} |")

    lines += ["", "## Misses (correct fiche not at rank 1)", "",
              "| Id | Split | Question | Style | Expected | Rank | Top result | Flagged |",
              "|---|---|---|---|---|---|---|---|"]
    for r in runs:
        if r["expected"] and r["rank"] != 1:
            top = f"{r['ids'][0]} {r['titles'][0]}" if r["ids"] else "(none)"
            lines.append(f"| {r['id']} | {r['split']} | {r['question']} | {r['style']} | {', '.join(r['expected'])} | "
                         f"{r['rank'] or f'>{DEPTH}'} | {top} | {'yes' if _flagged(r) else 'no'} |")

    lines += ["", "## No-match questions", "", "| Id | Question | Category | Flagged | Top result (match) |", "|---|---|---|---|---|"]
    for r in runs:
        if not r["expected"]:
            top = f"{r['ids'][0]} {r['titles'][0]} ({r['matches'][0]})" if r["ids"] else "(no results)"
            flag = "no results" if r["no_results"] else ("yes" if r["low_confidence"] else "**no**")
            lines.append(f"| {r['id']} | {r['question']} | {r['category']} | {flag} | {top} |")

    lines += ["", "## False alarms (rank 1 is right, but flagged low_confidence)", ""]
    alarms = [r for r in runs if r["rank"] == 1 and _flagged(r)]
    lines += [f"- {r['id']} {r['question']} ({r['style']}, top match {r['matches'][0]})" for r in alarms] or ["- none"]
    return "\n".join(lines) + "\n"


def main_cli() -> None:
    questions = load_questions()
    stale = check_labels(questions)
    if stale:
        sys.exit("Expected fiche ids missing from the database (feed changed?): " + ", ".join(stale))
    runs = [run_one(q) for q in questions]
    s = score(runs)
    text = report(runs, s)
    print(text)
    if "--no-save" not in sys.argv:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        # One file per search-code version, so a later run never overwrites a baseline.
        commit = _git_commit().split()[0]
        suffix = "-uncommitted" if "uncommitted" in _git_commit() else ""
        out = RESULTS_DIR / f"{dt.date.today().isoformat()}-{commit}{suffix}-q{questions_hash()}.md"
        out.write_text(text, encoding="utf-8")
        print(f"Saved {out.relative_to(EVALS_DIR.parent)}")


if __name__ == "__main__":
    main_cli()
