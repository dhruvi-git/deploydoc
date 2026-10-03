"""AWS Lambda (Function URL): receives the failure webhook from GitHub Actions,
records the incident (DynamoDB + S3), calls the agent on GCP, stores the diagnosis."""
import base64
import hmac
import json
import os
import urllib.request
from datetime import datetime, timezone

import boto3

TABLE = os.environ["TABLE_NAME"]
BUCKET = os.environ["BUCKET_NAME"]
AGENT_URL = os.environ["AGENT_URL"].rstrip("/")
AGENT_TOKEN = os.environ["AGENT_TOKEN"]
WEBHOOK_TOKEN = os.environ["WEBHOOK_TOKEN"]

ddb = boto3.resource("dynamodb").Table(TABLE)
s3 = boto3.client("s3")


def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _call_agent(payload):
    req = urllib.request.Request(
        f"{AGENT_URL}/investigate", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-DeployDoc-Token": AGENT_TOKEN})
    with urllib.request.urlopen(req, timeout=165) as r:
        return json.loads(r.read())


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not hmac.compare_digest(headers.get("x-deploydoc-token", ""), WEBHOOK_TOKEN):
        return _resp(401, {"error": "unauthorized"})

    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    try:
        payload = json.loads(body)
        run_id, repo, sha = int(payload["run_id"]), payload["repo"], payload["sha"]
    except (ValueError, KeyError, TypeError):
        return _resp(400, {"error": "payload needs repo, run_id, sha"})

    incident_id = f"inc-{run_id}-{int(payload.get('run_attempt', 1))}"
    payload["incident_id"] = incident_id
    payload.pop("run_attempt", None)

    ddb.put_item(Item={
        "incident_id": incident_id, "created_at": _now(), "status": "investigating",
        "repo": repo, "run_id": str(run_id), "sha": sha,
        "run_url": payload.get("run_url", ""), "branch": payload.get("branch", ""),
        "workflow": payload.get("workflow", ""), "actor": payload.get("actor", ""),
    })
    s3.put_object(Bucket=BUCKET, Key=f"incidents/{incident_id}/payload.json", Body=json.dumps(payload).encode())

    try:
        result = _call_agent(payload)
    except Exception as e:
        ddb.update_item(Key={"incident_id": incident_id},
                        UpdateExpression="SET #s=:s, #e=:e, completed_at=:c",
                        ExpressionAttributeNames={"#s": "status", "#e": "error"},
                        ExpressionAttributeValues={":s": "agent_error", ":e": str(e)[:500], ":c": _now()})
        return _resp(502, {"incident_id": incident_id, "error": str(e)[:300]})

    ddb.update_item(
        Key={"incident_id": incident_id},
        UpdateExpression="SET #s=:s, diagnosis=:d, #t=:t, duration_s=:du, model=:m, issue_url=:i, completed_at=:c",
        ExpressionAttributeNames={"#s": "status", "#t": "trace"},
        ExpressionAttributeValues={
            ":s": "done", ":d": json.dumps(result["diagnosis"]), ":t": json.dumps(result.get("trace", [])),
            ":du": str(result.get("duration_s", "")), ":m": result.get("model", ""),
            ":i": result.get("issue_url", ""), ":c": _now()})
    s3.put_object(Bucket=BUCKET, Key=f"incidents/{incident_id}/report.json", Body=json.dumps(result).encode())
    return _resp(200, {"incident_id": incident_id, "status": "done", "summary": result["diagnosis"]["summary"]})
