"""Count Part D from SQLite and price the measured harness calls.

Run after both arms: python -m eval.measure_03
Requires exactly two finished real-model runs per evaluation issue and arm.
Never executes tools, resets data, or replaces failed runs.
"""
from __future__ import annotations
from collections import Counter
import json
import sqlite3
import yaml
from harness import ROOT
from harness.backends import REAL_BACKENDS
from harness.formats import UNFINISHED, normalize_path, parse_triage_comment
from harness.ping import current_schemas, definitions_hash
from harness.pricing import PriceSheet
from harness.roles import role_of
from harness.switches import DEFAULTS

ARMS = {
    "harness": dict(flaky_writes=True, readback_fail=False, key_mode="derived", verify="on"),
    "control": dict(flaky_writes=True, readback_fail=False, key_mode="uuid", verify="off"),
}


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_runs(answers):
    arms = {arm: [] for arm in ARMS}
    for path in sorted((ROOT / "runs").glob("planned-*.jsonl")):
        if path.name.endswith(".calls.jsonl"):
            continue
        records = read_lines(path)
        if not records or records[0].get("type") != "run_start":
            continue
        start = records[0]
        if (start.get("lab") != "03" or start.get("way") != "planned"
                or start.get("backend") not in REAL_BACKENDS or start.get("issue") not in answers):
            continue
        switches = {**DEFAULTS, **start.get("switches", {})}
        for arm, wanted in ARMS.items():
            if switches != wanted:
                continue
            ends = [x for x in records if x["type"] == "end"]
            if records[-1]["type"] != "run_end" or not ends or ends[-1]["terminal_reason"] in UNFINISHED:
                raise ValueError(f"Unfinished measurement: {path.name}; resolve it before summarizing")
            calls = read_lines(path.with_name(path.stem + ".calls.jsonl")) if path.with_name(path.stem + ".calls.jsonl").exists() else []
            arms[arm].append(dict(start=start, records=records, calls=calls, end=ends[-1]))
    for arm, runs in arms.items():
        if Counter(r["start"]["issue"] for r in runs) != Counter({i: 2 for i in answers}):
            raise ValueError(f"{arm}: need exactly two finished runs per eval issue; found {len(runs)} runs")
        expected_sweeps = {1, 2} if arm == "harness" else {3, 4}
        if any({r["start"]["sweep"] for r in runs if r["start"]["issue"] == i} != expected_sweeps for i in answers):
            raise ValueError(f"{arm}: unexpected or repeated sweeps")
        if any(r["start"].get("critique") != "off" or r["start"].get("notes") != "off" for r in runs):
            raise ValueError("Both arms must keep critique and notes off")
    return arms


def count_run(db, run, answer):
    start = run["start"]; rid = start["run_id"]; issue = start["issue"]
    comments = [dict(x) for x in db.execute("SELECT * FROM comments WHERE run_id=? AND issue=? ORDER BY id", (rid, issue))]
    prs = [dict(x) for x in db.execute("SELECT * FROM prs WHERE run_id=? ORDER BY id", (rid,))]
    attempts = [dict(x) for x in db.execute("SELECT * FROM attempts WHERE run_id=? ORDER BY id", (rid,))]
    label, file = parse_triage_comment(comments[0]["body"]) if comments else (None, None)
    right = [p for p in prs if p["state"] == "open" and p["branch"] == f"repomind/issue-{issue}"]
    want = int(file not in (None, "none"))
    recorded = {(c["role"], c["key"]) for c in run["calls"] if c["outcome"] in ("ok", "timeout")}
    writes_recorded = all((role, row["key"]) in recorded for role, rows in (("comment", comments), ("open_pr", prs)) for row in rows)
    committed = [a for a in attempts if a["outcome"] == "timeout_after_commit"]
    timeout_records = {(c["role"], c["key"]) for c in run["calls"] if c["outcome"] == "timeout"}
    timeouts_recorded = all(("comment" if a["kind"] == "comment" else "open_pr", a["key"]) in timeout_records for a in committed)
    return dict(run_id=rid, issue=issue, sweep=start["sweep"], comments=len(comments), prs=len(prs),
                extra_comments=max(0, len(comments)-1), extra_prs=max(0, len(prs)-1),
                prs_correct=len(right) == want and len(prs) == len(right),
                committed_timeouts=len(committed), terminal_reason=run["end"]["terminal_reason"],
                end_detail=run["end"].get("detail"), label=label, file=file,
                triage_pass=len(comments) == 1 and label == answer["label"] and file == normalize_path(answer["file"]),
                all_writes_recorded=writes_recorded, all_committed_timeouts_recorded=timeouts_recorded)


def aggregate(rows):
    return dict(runs=len(rows), comments_per_run_max=max((r["comments"] for r in rows), default=0),
                duplicate_comment_runs=sum(r["comments"] > 1 for r in rows),
                prs_correct_runs=sum(r["prs_correct"] for r in rows),
                committed_timeouts=sum(r["committed_timeouts"] for r in rows),
                escalated=sum(r["terminal_reason"] == "escalated" for r in rows),
                triage_passes=sum(r["triage_pass"] for r in rows))


def surface_cost(calls, counts, prices):
    totals = dict(before=0.0, after=0.0, all_five=0.0)
    for call in calls:
        price = prices.find(call["model"])
        if price is None:
            raise ValueError(f"Unpriced model {call['model']}")
        names = [n for n in call["tools"] if n != "submit_plan"]
        if len(names) > 1 and set(names) != set(counts["after"]["names"]):
            raise ValueError("Unmeasured multi-tool subset; measure it before pricing")
        for version in ("before", "after"):
            part = counts[version]
            tokens = part["all_five"] if len(names) > 1 else sum(part["alone"][counts["after"]["names"][name]] for name in names)
            if call.get("purpose") in ("plan", "revise"):
                tokens += part["list"]
            totals[version] += tokens * price.input / 1_000_000
        totals["all_five"] += counts["after"]["all_five"] * price.input / 1_000_000
    return totals


def evidence(runs):
    rejected = []
    offplan = []
    no_read = []
    empty = []
    for run in runs:
        rid = run["start"]["run_id"]
        rejected += [dict(run_id=rid, role=c.get("role"), outcome=c["outcome"], result=c.get("result"))
                     for c in run["calls"] if c["outcome"] in ("rejected", "error")]
        offplan += [dict(run_id=rid, **{k:v for k,v in c.items() if k not in ("run_id",)})
                    for c in run["records"] if c["type"] == "off_plan"]
        read_roles = {c.get("role") for c in run["calls"] if c["outcome"] == "ok"}
        if "read_issue" not in read_roles or "search" not in read_roles:
            no_read.append(dict(run_id=rid, successful_read_roles=sorted(x for x in read_roles if x), reason=run["end"]))
        for c in run["records"]:
            if c["type"] == "tool_call" and role_of(c.get("name")) == "search" and not c.get("is_error"):
                try:
                    result = json.loads(c.get("result_excerpt", ""))
                except ValueError:
                    continue
                if result.get("count") == 0:
                    empty.append(dict(run_id=rid, query=result.get("query"), query_valid=result.get("query_valid")))
    return dict(execution_errors=rejected, off_plan=offplan, missing_successful_reads=no_read, valid_empty_searches=empty)


def render(counts, surface, writes, rows, observations):
    rate = PriceSheet().find(counts["served_by"]).input
    savings = surface["cost_per_run_all_five"] - surface["cost_per_run_after"]
    lines = ["<!-- PART_D_MEASUREMENTS_START -->", "### Measured tool surface", "",
             "Provider prompt-token differences (cached input included); baseline is the same one-message request without tools. Single-tool counts each include the provider's tool preamble.", "",
             "| Surface | Starter tokens | Rewritten tokens |", "|---|---:|---:|"]
    for name in counts["before"]["alone"]:
        lines.append(f"| {name} alone | {counts['before']['alone'][name]} | {counts['after']['alone'][name]} |")
    lines += [f"| All five together | {surface['tokens_before']} | {surface['tokens_after']} |",
              f"| Planner/reviser text list | {surface['list_tokens_before']} | {surface['list_tokens_after']} |", "",
              f"Mean calls per harness run: {surface['calls_per_run']:.4f}. For each version, cost = sum over harness calls of (single-tool token difference, or all-five difference if all five were offered, plus the list difference on plan/revise calls) × that call's model input rate / 1,000,000 / 12. submit_plan is excluded. The counterfactual charges all five on every call, including planner/reviser calls, with no extra list.", "",
              f"Mean surface cost: starter ${surface['cost_per_run_before']:.8f}; rewritten ${surface['cost_per_run_after']:.8f}; all-five counterfactual ${surface['cost_per_run_all_five']:.8f}. At the recorded model's rate, the implied mean surface tokens are each cost × 1,000,000 / its input rate. Raw counts and call usage are saved in SURFACE_COUNTS_03.json and SURFACE_CALLS_03.jsonl.", "",
              f"Input rate: ${rate:.4f} per million tokens. Mean surface tokens: starter {surface['cost_per_run_before'] * 1_000_000 / rate:.2f}, rewritten {surface['cost_per_run_after'] * 1_000_000 / rate:.2f}, all-five {surface['cost_per_run_all_five'] * 1_000_000 / rate:.2f}. Offering only the needed tool saves ${savings:.8f} per mean run against the all-five counterfactual.", "",
              "The added descriptions buy explicit argument choices, result caps and empty-result meaning, plus two examples. This is a surface-only price, not the total task bill. Caching can discount dollars without reducing context occupancy.", "", "### Tracker results", "",
              "| Measure | Your harness | Control |", "|---|---|---|"]
    def distribution(arm, key):
        return ", ".join(f"{n}: {k} runs" for n,k in sorted(Counter(r[key] for r in rows[arm]).items()))
    lines += [f"| Comments per run | {distribution('harness','comments')} | {distribution('control','comments')} |",
              f"| PRs per run | {distribution('harness','prs')} | {distribution('control','prs')} |"]
    for label, key in [("Runs with correct PR count/branch", "prs_correct_runs"), ("Committed timeouts", "committed_timeouts"), ("Escalated runs", "escalated"), ("Grounded triage passes", "triage_passes")]:
        lines.append(f"| {label} | {writes['harness'][key]} | {writes['control'][key]} |")
    lines += ["", "Counts come from SQLite, grouped by run_id; terminal outcomes come from traces. Grounded success requires exactly one comment and a label/file matching the reference answer, so duplicate comments fail even if their text is correct. PART_D_DETAILS.json lists every run and verifies write keys and committed timeouts against the call records.", "", "### Prediction comparison", ""]
    for arm, predicted_extra, predicted_runs in [("harness", 0, 0), ("control", 6, 5)]:
        extra = sum(r["extra_comments"] for r in rows[arm]); duplicates = writes[arm]["duplicate_comment_runs"]
        pr_extra = sum(r["extra_prs"] for r in rows[arm])
        lines.append(f"- {arm}: predicted {predicted_extra} extra comments in {predicted_runs} duplicate-comment runs and 0 extra PRs; measured {extra}, {duplicates}, and {pr_extra}, respectively.")
        if extra != predicted_extra or duplicates != predicted_runs:
            lines.append("  The exact duplicate estimate missed: duplicates depend on which comment writes reached a committed timeout and how many attempts ran. Planning/triage stops can also prevent a write from reaching the fault gate. The per-run tracker counts above preserve those outcomes.")
        if pr_extra:
            lines.append("  The zero-duplicate-PR prediction missed and requires inspecting the branch/precheck failure in the affected runs before drawing a safety conclusion.")
    errors = observations["execution_errors"]
    by_role = dict(Counter(x["role"] for x in errors))
    lines += [f"- Predicted search would be most misused. Observed rejected/execution-error attempts by role: {by_role or 'none'}. This proxy cannot detect a valid but inappropriate query; with no such errors or tied counts, the prediction is not established.", "", "### Four shapes of misuse", "",
              f"1. Right tool, wrong arguments: the boundary and schema checks narrow this. Measured rejected/execution-error attempts: {len(errors)}. Evidence references: {', '.join(dict.fromkeys(x['run_id'] for x in errors)) or 'none observed; absence is not a measured improvement over the starter'}. Errors may also be transport/storage failures; inspect their saved repair messages before classifying each as model misuse.",
              f"2. Wrong tool, valid call: one-tool fill requests and the executor's allowed-tool check narrow selection. Measured off-plan events: {len(observations['off_plan'])}; references: {', '.join(dict.fromkeys(x['run_id'] for x in observations['off_plan'])) or 'none observed'}. Both experimental arms share this surface, so this is not a causal before/after comparison.",
              f"3. Correct call, misread result: structured counts, query_valid and truncation narrow ambiguity, but cannot ensure understanding. Observed valid empty searches: {len(observations['valid_empty_searches'])}. Harness grounded passes: {writes['harness']['triage_passes']}/12. A wrong final answer alone does not prove a result was misread; trace review is needed to distinguish it from a poor query or insufficient evidence.",
              f"4. No call at all remains possible: descriptions cannot force the model to seek missing evidence. Runs missing a successful issue read or search: {len(observations['missing_successful_reads'])}; references: {', '.join(x['run_id'] for x in observations['missing_successful_reads']) or 'none'}. These are audit candidates, not automatic proof of voluntary omission: rejected plans can stop before dispatch. Even when basic reads are present, an omitted necessary additional read requires tasks with known answers and expected evidence to detect. The assignment cites a 36% MCP-Atlas benchmark figure; this small experiment cannot validate that external percentage.", "", "<!-- PART_D_MEASUREMENTS_END -->"]
    return "\n".join(lines)


def main():
    counts = json.loads((ROOT / "reports/SURFACE_COUNTS_03.json").read_text())
    if counts["definitions_hash"] != definitions_hash(current_schemas()):
        raise ValueError("Definitions changed since counting; do not mix versions")
    answers = {int(k):v for k,v in yaml.safe_load((ROOT / "fixtures/answers.yaml").read_text())["eval"].items()}
    arms = load_runs(answers)
    db = sqlite3.connect(f"file:{ROOT / 'tracker/tracker.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = {arm: [count_run(db, run, answers[run["start"]["issue"]]) for run in runs] for arm,runs in arms.items()}
    db.close()
    writes = {arm: aggregate(rs) for arm,rs in rows.items()}
    all_rows = [x for rs in rows.values() for x in rs]
    if not all(x["all_writes_recorded"] and x["all_committed_timeouts_recorded"] for x in all_rows):
        raise ValueError("Tracker write/timeout is missing its matching call record")
    if len({r["start"]["settings"] for runs in arms.values() for r in runs}) != 1:
        raise ValueError("Settings changed between the experiment arms")
    if any(r["start"]["model"] != counts["model"] for runs in arms.values() for r in runs):
        raise ValueError("Model changed between the experiment arms")
    calls = [c for r in arms["harness"] for c in r["records"] if c["type"] == "model_call"]
    if any(c["model"] != counts["served_by"] for c in calls):
        raise ValueError("Measured model differs from token-count model")
    costs = surface_cost(calls, counts, PriceSheet())
    surface = dict(tokens_before=counts["before"]["all_five"], tokens_after=counts["after"]["all_five"],
                   list_tokens_before=counts["before"]["list"], list_tokens_after=counts["after"]["list"],
                   calls_per_run=len(calls)/12, cost_per_run_before=costs["before"]/12,
                   cost_per_run_after=costs["after"]/12, cost_per_run_all_five=costs["all_five"]/12)
    observations = evidence([r for runs in arms.values() for r in runs])
    detail = dict(runs=rows, evidence=observations, surface=surface, writes=writes)
    (ROOT / "reports/PART_D_DETAILS.json").write_text(json.dumps(detail, indent=2) + "\n")
    path = ROOT / "reports/LAB_03.json"; report = json.loads(path.read_text())
    report.update(surface=surface, writes=writes); path.write_text(json.dumps(report, indent=2) + "\n")
    path = ROOT / "reports/LAB_03.md"; report = path.read_text()
    first = report.index("## Part D · Measure"); last = report.index("## AI assistance", first)
    followup = report.find("## Transparent follow-up experiment", first, last)
    preserved = report[followup:last] if followup >= 0 else ""
    report = report[:first] + "## Part D · Measure\n\n" + render(counts, surface, writes, rows, observations) + "\n\n" + preserved + report[last:]
    report = report.replace("Part D and final review remain pending.", "Codex also implemented Part D token-difference pricing and database-based counting, drafted pre-evaluation predictions, and generated the measured report. I ran the live experiments; final interpretation is reviewed together.")
    path.write_text(report)
    print(json.dumps(dict(surface=surface, writes=writes), indent=2))

if __name__ == "__main__":
    main()
