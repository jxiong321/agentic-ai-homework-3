"""Measure provider prompt-token differences: python -m eval.price_surface."""
from __future__ import annotations
import json
import subprocess
from datetime import datetime, timezone
from agent.plan import _tool_list
from harness import ROOT
from harness.backends import make_backend
from harness.client import ModelClient
from harness.ping import current_schemas, definitions_hash
from harness.pricing import PriceSheet
from harness.settings import load_settings
from tools import MODULES, SENT

STARTER = "ed6b2e9cba6a548af2c144a767dd7cc6f704866d"
MESSAGE = "Do not call any tool. Answer with the word ok."
SYSTEM = "You are a token-count measurement."


def surfaces():
    before = []
    for module in MODULES:
        raw = json.loads(subprocess.check_output(
            ["git", "show", f"{STARTER}:tools/{module}.json"], cwd=ROOT, text=True))
        before.append({k: raw[k] for k in SENT if k in raw})
    return {"before": before, "after": current_schemas()}


def main():
    target = ROOT / "reports/SURFACE_COUNTS_03.json"
    if target.exists():
        raise SystemExit("Counts already exist; preserve them or move them before explicitly remeasuring.")
    settings = load_settings(ROOT / "settings.yaml")
    client = ModelClient(make_backend(settings.provider, settings), PriceSheet(),
                         session_ceiling=settings.session_token_ceiling)
    definitions = surfaces()
    measurements = []

    def call(label, schemas=None, text=MESSAGE):
        reply = client.create(system=SYSTEM, messages=[{"role": "user", "content": text}], tools=schemas)
        row = {"label": label, "model": reply.model, "usage": reply.usage.as_dict(),
               "cost_usd": reply.cost_usd, "tools": reply.offered}
        measurements.append(row)
        # Save each paid call immediately, including partial measurements if interrupted.
        with (ROOT / "reports/SURFACE_CALLS_03.jsonl").open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"{label}: {reply.usage.prompt_tokens} prompt tokens", flush=True)
        return reply.usage.prompt_tokens

    baseline = call("baseline")
    out = {"at": datetime.now(timezone.utc).isoformat(), "starter_commit": STARTER,
           "model": settings.model, "baseline": baseline,
           "definitions_hash": definitions_hash(definitions["after"]),
           "method": "Same system and one user message; subtract baseline prompt_tokens, including cached tokens. List appended after two newlines."}
    for version, schemas in definitions.items():
        alone = {module: call(f"{version}/{module}", [schema]) - baseline
                 for module, schema in zip(MODULES, schemas)}
        out[version] = {"all_five": call(f"{version}/all_five", schemas) - baseline,
                        "alone": alone,
                        "list": call(f"{version}/list", text=MESSAGE + "\n\n" + _tool_list(schemas)) - baseline,
                        "names": {s["name"]: m for m, s in zip(MODULES, schemas)}}
    if len({m["model"] for m in measurements}) != 1:
        raise RuntimeError("Provider changed models during measurement; counts are not comparable")
    if any(n < 0 for v in ("before", "after") for n in [out[v]["all_five"], out[v]["list"], *out[v]["alone"].values()]):
        raise RuntimeError("Negative token difference; inspect raw measurements")
    out["served_by"] = measurements[0]["model"]
    out["totals"] = client.totals()
    target.write_text(json.dumps(out, indent=2) + "\n")
    print(f"Saved {target}")

if __name__ == "__main__":
    main()
