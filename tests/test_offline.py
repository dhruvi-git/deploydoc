"""Offline sanity tests (no cloud accounts needed):  python tests/test_offline.py"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))
os.environ.update(GCP_PROJECT_ID="demo", AGENT_TOKEN="a", DASHBOARD_KEY="k")

from google.genai import types  # noqa: E402

from app import agent, tools  # noqa: E402


def test_trim_log():
    raw = "\n".join(["2026-01-01T00:00:00.000Z noise"] * 200 +
                    ["2026-01-01T00:00:01.000Z ##[error]Error: revision not ready", "tail"])
    out = tools.trim_log(raw, 2000)
    assert "revision not ready" in out and "T00:00" not in out and len(out) <= 2000


def test_agent_loop():
    script = [
        [types.Part(function_call=types.FunctionCall(name="github_get_failed_jobs", args={"repo": "o/r", "run_id": 1}))],
        [types.Part(function_call=types.FunctionCall(name="submit_diagnosis", args={
            "summary": "s", "root_cause": "r", "category": "missing_env_var", "confidence": 140,
            "affected_clouds": ["gcp", "mars"], "evidence": [{"source": "x", "excerpt": "y"}], "fix_steps": ["a"]}))],
    ]
    calls = iter(script)

    class FakeModels:
        def generate_content(self, **kw):
            parts = next(calls)
            return SimpleNamespace(candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))])

    agent._client = lambda: SimpleNamespace(models=FakeModels())
    tools.REGISTRY["github_get_failed_jobs"] = lambda repo, run_id: {"jobs": []}
    res = agent.investigate({"repo": "o/r", "run_id": 1, "sha": "abc"})
    d = res["diagnosis"]
    assert d["confidence"] == 100 and d["affected_clouds"] == ["gcp"] and len(res["trace"]) == 2


def test_tool_declarations_valid():
    cfg = agent._config()
    assert cfg.tools[0].function_declarations[0].name == "github_get_failed_jobs"
    assert agent._config(force_submit=True).tool_config is not None


def test_lambda():
    import importlib
    import boto3
    os.environ.update(TABLE_NAME="t", BUCKET_NAME="b", AGENT_URL="http://x", AGENT_TOKEN="a", WEBHOOK_TOKEN="w",
                      AWS_DEFAULT_REGION="ap-south-1", AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="y")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "aws", "lambda_ingest"))
    h = importlib.import_module("handler")
    assert h.handler({"headers": {"X-DeployDoc-Token": "bad"}, "body": "{}"}, None)["statusCode"] == 401
    puts, updates = [], []
    h.ddb = SimpleNamespace(put_item=lambda **k: puts.append(k), update_item=lambda **k: updates.append(k))
    h.s3 = SimpleNamespace(put_object=lambda **k: None)
    h._call_agent = lambda p: {"diagnosis": {"summary": "ok"}, "trace": [], "duration_s": 1.2, "model": "m", "issue_url": ""}
    ev = {"headers": {"x-deploydoc-token": "w"}, "body": json.dumps({"repo": "o/r", "run_id": 7, "sha": "s", "run_attempt": 2})}
    r = h.handler(ev, None)
    assert r["statusCode"] == 200 and puts[0]["Item"]["incident_id"] == "inc-7-2" and updates
    assert h.handler({"headers": {"x-deploydoc-token": "w"}, "body": "nope"}, None)["statusCode"] == 400


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
