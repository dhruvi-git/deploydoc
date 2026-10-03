"""Evidence-collection tools. Used directly by the agent AND exposed over MCP (mcp_server.py)."""
import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from . import config, store

GITHUB_API = "https://api.github.com"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
SUSPICIOUS = re.compile(
    r"##\[error\]|error|fail|denied|exception|traceback|invalid|not found|unauthorized|forbidden|exit code",
    re.I,
)


# ---------------------------------------------------------------- helpers
def trim_log(text: str, max_chars: int = 6000) -> str:
    """Keep lines around errors plus the tail of the log, so the LLM sees signal, not noise."""
    lines = [TIMESTAMP.sub("", ANSI.sub("", ln)) for ln in text.splitlines()]
    keep = set(range(max(0, len(lines) - 25), len(lines)))
    for i, ln in enumerate(lines):
        if SUSPICIOUS.search(ln):
            keep.update(range(max(0, i - 2), min(len(lines), i + 3)))
    out, prev = [], -2
    for i in sorted(keep):
        if i != prev + 1:
            out.append("...")
        out.append(lines[i])
        prev = i
    s = "\n".join(out)
    return s[-max_chars:] if len(s) > max_chars else s


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh(path: str, **kw) -> requests.Response:
    r = requests.get(f"{GITHUB_API}{path}", headers=_gh_headers(), timeout=30, **kw)
    r.raise_for_status()
    return r


def create_issue(repo: str, title: str, body: str) -> str:
    r = requests.post(f"{GITHUB_API}/repos/{repo}/issues", headers=_gh_headers(),
                      json={"title": title, "body": body}, timeout=30)
    r.raise_for_status()
    return r.json()["html_url"]


# ---------------------------------------------------------------- GitHub tools
def github_get_failed_jobs(repo: str, run_id: int) -> dict:
    jobs = _gh(f"/repos/{repo}/actions/runs/{int(run_id)}/jobs", params={"per_page": 50}).json()["jobs"]
    return {"jobs": [
        {"job_id": j["id"], "name": j["name"], "conclusion": j["conclusion"],
         "failed_steps": [s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"]}
        for j in jobs
    ]}


def github_get_job_logs(repo: str, job_id: int, max_chars: int = 6000) -> dict:
    r = _gh(f"/repos/{repo}/actions/jobs/{int(job_id)}/logs")
    return {"job_id": int(job_id), "log_excerpt": trim_log(r.text, int(max_chars))}


def github_get_commit_diff(repo: str, sha: str) -> dict:
    c = _gh(f"/repos/{repo}/commits/{sha}").json()
    return {
        "message": c["commit"]["message"],
        "author": c["commit"]["author"]["name"],
        "files": [{"file": f["filename"], "status": f["status"], "patch": (f.get("patch") or "")[:1500]}
                  for f in c.get("files", [])[:10]],
    }


# ---------------------------------------------------------------- AWS
def aws_get_cloudwatch_logs(minutes: int = 30, filter_pattern: str = "") -> dict:
    import boto3
    logs = boto3.client("logs", region_name=config.AWS_REGION)
    kwargs = {"logGroupName": config.AWS_LOG_GROUP,
              "startTime": int((time.time() - int(minutes) * 60) * 1000), "limit": 100}
    if filter_pattern:
        kwargs["filterPattern"] = filter_pattern
    try:
        events = logs.filter_log_events(**kwargs)["events"]
    except logs.exceptions.ResourceNotFoundException:
        return {"note": f"Log group {config.AWS_LOG_GROUP} does not exist yet (function never ran)."}
    return {"log_group": config.AWS_LOG_GROUP, "events": [
        {"time": datetime.fromtimestamp(e["timestamp"] / 1000, timezone.utc).isoformat(),
         "message": e["message"].strip()[:500]} for e in events[-40:]]}


# ---------------------------------------------------------------- Azure
_AZURE_TABLES = {
    "console": [("ContainerAppConsoleLogs_CL", "ContainerAppName_s", "Log_s"),
                ("ContainerAppConsoleLogs", "ContainerAppName", "Log")],
    "system": [("ContainerAppSystemLogs_CL", "ContainerAppName_s", "Log_s"),
               ("ContainerAppSystemLogs", "ContainerAppName", "Log")],
}


def azure_get_container_logs(minutes: int = 30, kind: str = "console") -> dict:
    from azure.identity import ClientSecretCredential
    from azure.monitor.query import LogsQueryClient

    cred = ClientSecretCredential(config.AZURE_TENANT_ID, config.AZURE_CLIENT_ID, config.AZURE_CLIENT_SECRET)
    client = LogsQueryClient(cred)
    errors = []
    for table, name_col, msg_col in _AZURE_TABLES.get(kind, _AZURE_TABLES["console"]):
        query = (f'{table} | where {name_col} == "{config.AZURE_APP_NAME}" '
                 f'| project TimeGenerated, Revision=column_ifexists("RevisionName_s", column_ifexists("RevisionName", "")), '
                 f'Message={msg_col} | order by TimeGenerated desc | take 40')
        try:
            resp = client.query_workspace(config.AZURE_LOG_WORKSPACE_ID, query,
                                          timespan=timedelta(minutes=int(minutes)))
            rows = resp.tables[0].rows if resp.tables else []
            return {"table": table, "rows": [
                {"time": str(r[0]), "revision": r[1], "message": str(r[2])[:500]} for r in rows]}
        except Exception as e:  # table may not exist under this name; try the next one
            errors.append(f"{table}: {str(e)[:150]}")
    return {"error": "No Container Apps log table could be queried", "details": errors}


# ---------------------------------------------------------------- GCP
def gcp_get_cloudrun_logs(minutes: int = 30, min_severity: str = "WARNING") -> dict:
    from google.cloud import logging as gcl

    client = gcl.Client(project=config.GCP_PROJECT)
    since = (datetime.now(timezone.utc) - timedelta(minutes=int(minutes))).strftime("%Y-%m-%dT%H:%M:%SZ")
    sev = min_severity.upper() if min_severity.upper() in ("DEFAULT", "INFO", "WARNING", "ERROR") else "WARNING"
    flt = (f'resource.type="cloud_run_revision" AND resource.labels.service_name="{config.GCP_TARGET_SERVICE}" '
           f'AND severity>={sev} AND timestamp>="{since}"')
    out = []
    for e in client.list_entries(filter_=flt, order_by=gcl.DESCENDING, max_results=40):
        payload = e.payload if isinstance(e.payload, str) else json.dumps(e.payload, default=str)
        out.append({"time": e.timestamp.isoformat() if e.timestamp else "",
                    "severity": e.severity, "message": payload[:500]})
    return {"service": config.GCP_TARGET_SERVICE, "entries": out}


# ---------------------------------------------------------------- memory
def find_similar_incidents(keywords: str) -> dict:
    return {"similar": store.similar(keywords)}


# ---------------------------------------------------------------- registry
def _s(desc): return {"type": "STRING", "description": desc}
def _i(desc): return {"type": "INTEGER", "description": desc}
def _obj(props, required): return {"type": "OBJECT", "properties": props, "required": required}


CATEGORIES = ["missing_env_var", "port_mismatch", "image_not_found", "auth_failure",
              "invalid_resource_config", "quota_or_limit", "code_error", "unknown"]

TOOLS = [
    {"name": "github_get_failed_jobs", "fn": github_get_failed_jobs,
     "description": "List every job of a GitHub Actions run with its conclusion and failed step names.",
     "parameters": _obj({"repo": _s("owner/name"), "run_id": _i("Workflow run id")}, ["repo", "run_id"])},
    {"name": "github_get_job_logs", "fn": github_get_job_logs,
     "description": "Get an error-focused excerpt of one CI job's log. Use for each failed job.",
     "parameters": _obj({"repo": _s("owner/name"), "job_id": _i("Job id from github_get_failed_jobs")},
                        ["repo", "job_id"])},
    {"name": "github_get_commit_diff", "fn": github_get_commit_diff,
     "description": "Get the commit message and changed files (patches) for the commit that was deployed.",
     "parameters": _obj({"repo": _s("owner/name"), "sha": _s("Commit sha")}, ["repo", "sha"])},
    {"name": "aws_get_cloudwatch_logs", "fn": aws_get_cloudwatch_logs,
     "description": "Recent CloudWatch logs of the AWS Lambda deployment target (region ap-south-1).",
     "parameters": _obj({"minutes": _i("Look-back window in minutes (default 30)"),
                         "filter_pattern": _s("Optional CloudWatch filter pattern, e.g. ERROR")}, [])},
    {"name": "azure_get_container_logs", "fn": azure_get_container_logs,
     "description": "Recent Azure Container Apps logs from Log Analytics. kind=console for app output, "
                    "kind=system for platform events (image pull, probe failures, revisions).",
     "parameters": _obj({"minutes": _i("Look-back window in minutes (default 30)"),
                         "kind": _s("console or system")}, [])},
    {"name": "gcp_get_cloudrun_logs", "fn": gcp_get_cloudrun_logs,
     "description": "Recent Cloud Logging entries for the GCP Cloud Run deployment target (WARNING and above by default).",
     "parameters": _obj({"minutes": _i("Look-back window in minutes (default 30)"),
                         "min_severity": _s("DEFAULT, INFO, WARNING or ERROR")}, [])},
    {"name": "find_similar_incidents", "fn": find_similar_incidents,
     "description": "Search past incidents (incident memory) by keywords from the error message.",
     "parameters": _obj({"keywords": _s("Key words of the suspected error")}, ["keywords"])},
    {"name": "submit_diagnosis", "fn": None,
     "description": "FINAL STEP. Submit the structured root-cause analysis. Call exactly once when done.",
     "parameters": _obj({
         "summary": _s("One sentence a human can read in 5 seconds"),
         "root_cause": _s("Precise root cause, naming the file/setting/resource"),
         "category": {"type": "STRING", "enum": CATEGORIES, "description": "Failure category"},
         "confidence": _i("0-100, based only on the strength of the evidence"),
         "affected_clouds": {"type": "ARRAY", "items": {"type": "STRING", "enum": ["aws", "azure", "gcp"]},
                             "description": "Clouds whose deployment failed"},
         "evidence": {"type": "ARRAY", "description": "Verbatim log lines that prove the root cause",
                      "items": _obj({"source": _s("e.g. github:deploy-gcp, gcp:cloud-logging, aws:cloudwatch, azure:log-analytics"),
                                     "excerpt": _s("Exact text copied from the tool output")},
                                    ["source", "excerpt"])},
         "fix_steps": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Concrete ordered steps"},
         "suggested_patch": _s("Minimal diff or config change that fixes it (may be empty)"),
         "blast_radius": _s("What is down / healthy right now, per cloud"),
     }, ["summary", "root_cause", "category", "confidence", "affected_clouds", "evidence", "fix_steps"])},
]

REGISTRY = {t["name"]: t["fn"] for t in TOOLS if t["fn"]}


def run_tool(name: str, args: dict) -> dict:
    fn = REGISTRY.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name}"}
    try:
        result = fn(**args)
    except Exception as e:  # tool errors are evidence too - hand them to the model
        return {"error": f"{type(e).__name__}: {str(e)[:400]}"}
    text = json.dumps(result, default=str)
    return result if len(text) <= 12000 else {"truncated": text[:12000]}
