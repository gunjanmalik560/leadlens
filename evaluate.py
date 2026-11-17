"""
LeadLens v2 - accuracy evaluation.

Runs every question in eval_questions.json through LeadLens and checks the
answer against the reference SQL ("execution accuracy").

    python evaluate.py              run all remaining questions
    python evaluate.py --limit 10   run at most 10 new questions this time
    python evaluate.py --report     just print the report from saved results

Results are saved after every question in results/<model>.json, so if the
free-tier daily limit is hit, run it again tomorrow and it continues.
"""
import argparse
import json
import sqlite3
import time
from math import floor, log10
from pathlib import Path

import pandas as pd

import core

HERE = Path(__file__).parent
QUESTIONS = json.loads((HERE / "eval_questions.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# How we decide if an answer is correct
# ---------------------------------------------------------------------------
def norm(v):
    """Make values comparable: 3 significant figures for numbers,
    lower-case trimmed text. 63.27 and 63.3 both become 63.3."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        if v == 0:
            return 0.0
        return round(float(v), -int(floor(log10(abs(v)))) + 2)
    return str(v).strip().lower()


def sort_key(v):
    return (v is None, type(v).__name__, v if v is not None else 0)


def results_match(gold: pd.DataFrame, pred: pd.DataFrame) -> bool:
    """Correct if the prediction has the same rows and contains every gold
    column. Column names, column order, row order and extra columns
    (e.g. showing the win rate next to the winner) are ignored."""
    if len(gold) != len(pred):
        return False
    g_cols = [[norm(v) for v in gold.iloc[:, i]] for i in range(gold.shape[1])]
    p_cols = [[norm(v) for v in pred.iloc[:, i]] for i in range(pred.shape[1])]

    # Match each gold column to an unused prediction column with the same values.
    used, mapping = set(), []
    for g in g_cols:
        g_sorted = sorted(g, key=sort_key)
        for j, p in enumerate(p_cols):
            if j not in used and sorted(p, key=sort_key) == g_sorted:
                used.add(j)
                mapping.append(j)
                break
        else:
            return False

    # Check the rows line up (not just each column on its own).
    g_rows = sorted(zip(*g_cols), key=lambda r: [sort_key(v) for v in r])
    p_rows = sorted(zip(*[p_cols[j] for j in mapping]),
                    key=lambda r: [sort_key(v) for v in r])
    return g_rows == p_rows


def run_gold(sql):
    con = sqlite3.connect(f"file:{core.DB_PATH}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(sql, con)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def report(results, model):
    done = [r for r in results.values() if r["status"] != "skipped"]
    lines = [f"# LeadLens v2 evaluation - {model}", ""]
    if not done:
        print("No results yet.")
        return
    correct = sum(r["status"] == "correct" for r in done)
    lines.append(f"**Execution accuracy: {correct}/{len(done)} "
                 f"({100 * correct / len(done):.0f}%)**"
                 + ("" if len(done) == len(QUESTIONS) else
                    f"  - {len(QUESTIONS) - len(done)} questions not run yet"))
    lines += ["", "| Difficulty | Correct | Total | Accuracy |", "|---|---|---|---|"]
    for lv in ("easy", "medium", "hard"):
        sub = [r for r in done if r["difficulty"] == lv]
        if sub:
            c = sum(r["status"] == "correct" for r in sub)
            lines.append(f"| {lv} | {c} | {len(sub)} | {100 * c / len(sub):.0f}% |")
    counts = {}
    for r in done:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines += ["", "Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
              "", "## Questions it got wrong", ""]
    for r in sorted(done, key=lambda r: r["id"]):
        if r["status"] != "correct":
            lines += [f"**Q{r['id']} ({r['difficulty']}, {r['status']}):** {r['question']}",
                      "", f"- LeadLens SQL: `{r.get('pred_sql') or '-'}`"]
            if r.get("error"):
                lines.append(f"- Error: {r['error'][:200]}")
            lines.append("")
    text = "\n".join(lines)
    (HERE / "eval_report.md").write_text(text, encoding="utf-8")
    print("\n" + text.split("## Questions it got wrong")[0])
    print("Full report (with every wrong answer) saved to eval_report.md")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="max new questions this run")
    ap.add_argument("--pause", type=float, default=5, help="seconds between API calls")
    ap.add_argument("--report", action="store_true", help="only print the report")
    ap.add_argument("--rerun-errors", action="store_true",
                    help="retry questions that previously failed with an API error")
    args = ap.parse_args()

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{core.MODEL}.json"
    results = {}
    if out_file.exists():
        results = {r["id"]: r for r in json.loads(out_file.read_text(encoding="utf-8"))}

    if args.report:
        report(results, core.MODEL)
        return

    todo = [q for q in QUESTIONS if q["id"] not in results
            or (args.rerun_errors and results[q["id"]]["status"] == "api_error")]
    if args.limit:
        todo = todo[:args.limit]
    print(f"Model: {core.MODEL} | already done: {len(results)} | running now: {len(todo)}")

    client = core.get_client() if todo else None
    for n, q in enumerate(todo, 1):
        rec = {"id": q["id"], "difficulty": q["difficulty"], "question": q["question"],
               "pred_sql": None, "status": None, "error": None}
        try:
            rec["pred_sql"] = core.generate_sql(q["question"], client)
            pred = core.run_sql(rec["pred_sql"])
            rec["status"] = "correct" if results_match(run_gold(q["sql"]), pred) else "wrong"
        except core.DailyQuotaExceeded as e:
            print(f"\nStopped: {e}\nProgress is saved - run evaluate.py again later.")
            break
        except ValueError as e:              # blocked by the safety check
            rec["status"], rec["error"] = "unsafe", str(e)
        except Exception as e:
            if rec["pred_sql"] is None:      # failed before getting SQL back
                rec["status"], rec["error"] = "api_error", str(e)
            else:                            # SQL was invalid
                rec["status"], rec["error"] = "sql_error", str(e)

        results[q["id"]] = rec
        out_file.write_text(json.dumps(sorted(results.values(), key=lambda r: r["id"]),
                                       indent=2), encoding="utf-8")
        mark = {"correct": "OK ", "wrong": "XX "}.get(rec["status"], "!! ")
        print(f"[{n}/{len(todo)}] {mark} Q{q['id']:>2} {q['difficulty']:<6} "
              f"{rec['status']}: {q['question'][:60]}")
        if n < len(todo):
            time.sleep(args.pause)            # stay under per-minute limits

    report(results, core.MODEL)


if __name__ == "__main__":
    main()
