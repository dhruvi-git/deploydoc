"""The investigation loop: Gemini (Vertex AI) decides which evidence tools to call, then submits a diagnosis."""
import json
import time

from google import genai
from google.genai import types

from . import config, tools

SYSTEM_PROMPT = """You are DeployDoc, an SRE agent that investigates failed CI/CD deployments.

The service `deploydoc-target` is deployed by ONE GitHub Actions workflow to three clouds:
- GCP Cloud Run (managed by Terraform)  -> job `deploy-gcp`   -> logs in Cloud Logging
- Azure Container Apps (az CLI)          -> job `deploy-azure` -> logs in Log Analytics
- AWS Lambda (zip upload)                -> job `deploy-aws`   -> logs in CloudWatch
A final `notify` job calls you when any job failed. After each deploy, a smoke test checks that /health reports the new version.

Method:
1. Call github_get_failed_jobs, then github_get_job_logs for EVERY failed job.
2. If the CI log is not conclusive, read that cloud's runtime logs (and only that cloud's, unless another also failed).
3. Call github_get_commit_diff if a code or config change may be responsible.
4. Call find_similar_incidents once with keywords from the error.
5. Call submit_diagnosis.

Rules:
- Use evidence only. Quote log lines verbatim in `evidence`. Never invent log lines.
- If several clouds failed, decide whether they share one root cause or have different ones.
- If only one cloud failed, say the others are healthy and do not blame them.
- A tool returning an error or no data is a finding, not a reason to guess.
- Do not repeat a tool call with the same arguments. Use at most 8 tool calls.
- Confidence must reflect the evidence: below 60 when you are inferring.
- Fix steps must be concrete (name the file, setting or secret). Prefer the smallest possible change."""


def _client():
    return genai.Client(vertexai=True, project=config.GCP_PROJECT, location=config.VERTEX_LOCATION)


def _config(force_submit: bool = False):
    kwargs = dict(
        system_instruction=SYSTEM_PROMPT,
        tools=[{"function_declarations": [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in tools.TOOLS]}],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    if force_submit:
        kwargs["tool_config"] = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
            mode="ANY", allowed_function_names=["submit_diagnosis"]))
    return types.GenerateContentConfig(**kwargs)


def _user_prompt(incident: dict) -> str:
    keep = {k: incident.get(k) for k in ("repo", "run_id", "run_url", "sha", "branch", "workflow", "actor")}
    return "A deployment failed. Investigate and diagnose.\n" + json.dumps(keep, indent=2)


def _cloud_of(tool: str) -> str:
    for prefix in ("github", "aws", "azure", "gcp"):
        if tool.startswith(prefix):
            return prefix
    return "memory" if tool.startswith("find_") else "agent"


def normalise(d: dict) -> dict:
    try:
        conf = max(0, min(100, int(d.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0
    cat = d.get("category") if d.get("category") in tools.CATEGORIES else "unknown"
    return {
        "summary": str(d.get("summary", "")),
        "root_cause": str(d.get("root_cause", "")),
        "category": cat,
        "confidence": conf,
        "affected_clouds": [c for c in (d.get("affected_clouds") or []) if c in ("aws", "azure", "gcp")],
        "evidence": [{"source": str(e.get("source", "")), "excerpt": str(e.get("excerpt", ""))[:600]}
                     for e in (d.get("evidence") or []) if isinstance(e, dict)],
        "fix_steps": [str(s) for s in (d.get("fix_steps") or [])],
        "suggested_patch": str(d.get("suggested_patch", "")),
        "blast_radius": str(d.get("blast_radius", "")),
    }


def investigate(incident: dict) -> dict:
    started = time.time()
    client = _client()
    contents = [types.Content(role="user", parts=[types.Part(text=_user_prompt(incident))])]
    trace, diagnosis = [], None

    for step in range(1, config.MAX_STEPS + 1):
        last = step == config.MAX_STEPS
        if last:
            contents.append(types.Content(role="user", parts=[types.Part(
                text="Out of budget. Call submit_diagnosis now with your best evidence-based answer.")]))
        resp = client.models.generate_content(model=config.GEMINI_MODEL, contents=contents,
                                              config=_config(force_submit=last))
        cand = resp.candidates[0] if resp.candidates else None
        if not cand or not cand.content or not cand.content.parts:
            raise RuntimeError(f"Model returned no content (finish_reason={getattr(cand, 'finish_reason', None)})")
        contents.append(cand.content)  # keep as-is: preserves Gemini thought signatures

        calls = [p.function_call for p in cand.content.parts if p.function_call]
        if not calls:
            contents.append(types.Content(role="user", parts=[types.Part(
                text="Continue: call an evidence tool, or call submit_diagnosis if you are done.")]))
            continue

        responses = []
        for fc in calls:
            args = dict(fc.args or {})
            if fc.name == "submit_diagnosis":
                diagnosis = normalise(args)
                trace.append({"step": step, "tool": fc.name, "cloud": "agent", "args": {}, "result_preview": "diagnosis submitted"})
                break
            result = tools.run_tool(fc.name, args)
            trace.append({"step": step, "tool": fc.name, "cloud": _cloud_of(fc.name), "args": args,
                          "result_preview": json.dumps(result, default=str)[:400]})
            responses.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
        if diagnosis:
            break
        contents.append(types.Content(role="user", parts=responses))

    if diagnosis is None:
        raise RuntimeError("Agent finished without submitting a diagnosis")
    return {"diagnosis": diagnosis, "trace": trace, "model": config.GEMINI_MODEL,
            "duration_s": round(time.time() - started, 1)}
