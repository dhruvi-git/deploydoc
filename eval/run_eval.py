"""Run each failure scenario N times, wait for DeployDoc's diagnosis, and score it.

Needs env vars:  GITHUB_TOKEN (Actions: read+write on the repo), GITHUB_REPO (owner/name),
                 AGENT_URL (Cloud Run URL), DASHBOARD_KEY
Usage:           python eval/run_eval.py --runs 2
"""
import argparse
import csv
import datetime as dt
import os
import sys
import time

import requests

EXPECTED = {  # scenario -> (expected category, clouds that should be reported as failed)
    "missing_env":     ("missing_env_var",        {"aws", "azure", "gcp"}),
    "bad_port":        ("port_mismatch",          {"azure", "gcp"}),
    "bad_image_tag":   ("image_not_found",        {"azure", "gcp"}),
    "bad_credentials": ("auth_failure",           {"aws"}),
    "bad_resources":   ("invalid_resource_config", {"gcp"}),
}
REPO = os.environ.get("GITHUB_REPO", "")
GH = {"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
      "Accept": "application/vnd.github+json"}
AGENT = os.environ.get("AGENT_URL", "").rstrip("/")
KEY = {"X-API-Key": os.environ.get("DASHBOARD_KEY", "")}
WORKFLOW = "deploy.yml"


def dispatch(scenario):
    t0 = dt.datetime.now(dt.timezone.utc)
    r = requests.post(f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
                      headers=GH, json={"ref": "main", "inputs": {"scenario": scenario}}, timeout=30)
    r.raise_for_status()
    for _ in range(30):
        time.sleep(5)
        runs = requests.get(f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs",
                            headers=GH, params={"event": "workflow_dispatch", "per_page": 5}, timeout=30).json()
        for run in runs.get("workflow_runs", []):
            created = dt.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if created >= t0 - dt.timedelta(seconds=5):
                return run["id"]
    raise RuntimeError("Could not find the dispatched run")


def wait_run(run_id, timeout=30 * 60):
    end = time.time() + timeout
    while time.time() < end:
        run = requests.get(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}", headers=GH, timeout=30).json()
        if run["status"] == "completed":
            return run
        time.sleep(20)
    raise TimeoutError("Run did not finish")


def get_incident(run_id):
    for _ in range(12):
        r = requests.get(f"{AGENT}/api/incidents/inc-{run_id}-1", headers=KEY, timeout=30)
        if r.status_code == 200 and r.json().get("status") in ("done", "agent_error"):
            return r.json()
        time.sleep(10)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--scenarios", nargs="*", default=list(EXPECTED))
    args = ap.parse_args()
    if not (REPO and AGENT and GH["Authorization"] != "Bearer "):
        sys.exit("Set GITHUB_TOKEN, GITHUB_REPO, AGENT_URL and DASHBOARD_KEY first.")

    os.makedirs("results", exist_ok=True)
    rows = []
    for scenario in args.scenarios:
        exp_cat, exp_clouds = EXPECTED[scenario]
        for n in range(1, args.runs + 1):
            print(f"[{scenario} #{n}] dispatching...")
            run_id = dispatch(scenario)
            run = wait_run(run_id)
            inc = get_incident(run_id)
            d = (inc or {}).get("diagnosis") or {}
            row = {
                "scenario": scenario, "run": n, "run_id": run_id, "ci_conclusion": run["conclusion"],
                "diagnosed": bool(d), "category": d.get("category", ""), "expected_category": exp_cat,
                "category_ok": d.get("category") == exp_cat,
                "clouds": "+".join(sorted(d.get("affected_clouds", []))),
                "clouds_ok": set(d.get("affected_clouds", [])) == exp_clouds,
                "confidence": d.get("confidence", ""), "agent_seconds": (inc or {}).get("duration_s", ""),
                "tool_calls": len((inc or {}).get("trace", [])) - 1,
            }
            rows.append(row)
            print("   ->", {k: row[k] for k in ("category", "category_ok", "clouds", "clouds_ok", "agent_seconds")})
            # restore a healthy state so the next scenario starts clean
            wait_run(dispatch("none"))

    path = f"results/eval_{dt.datetime.now():%Y%m%d_%H%M}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    print(f"\nSaved {path}")
    print(f"Root-cause category accuracy : {sum(r['category_ok'] for r in rows)}/{n}")
    print(f"Affected-cloud accuracy      : {sum(r['clouds_ok'] for r in rows)}/{n}")
    secs = [float(r["agent_seconds"]) for r in rows if r["agent_seconds"] != ""]
    if secs:
        print(f"Mean agent time              : {sum(secs) / len(secs):.1f}s")


if __name__ == "__main__":
    main()
