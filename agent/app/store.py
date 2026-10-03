"""Read access to the incident table in DynamoDB (AWS)."""
import json
import re

import boto3

from . import config

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb", region_name=config.AWS_REGION).Table(config.DDB_TABLE)
    return _table


def _load(value, default):
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _hydrate(item: dict, full: bool = False) -> dict:
    diagnosis = _load(item.get("diagnosis"), {})
    keys = ("incident_id", "created_at", "completed_at", "status", "repo", "run_id", "run_url",
            "sha", "branch", "workflow", "actor", "duration_s", "model", "issue_url", "error")
    out = {k: item.get(k, "") for k in keys}
    out["summary"] = diagnosis.get("summary", "")
    out["category"] = diagnosis.get("category", "")
    out["confidence"] = diagnosis.get("confidence", "")
    out["affected_clouds"] = diagnosis.get("affected_clouds", [])
    if full:
        out["diagnosis"] = diagnosis
        out["trace"] = _load(item.get("trace"), [])
    return out


def list_incidents(limit: int = 30, full: bool = False) -> list:
    items, kwargs = [], {}
    while True:
        resp = table().scan(**kwargs)
        items += resp.get("Items", [])
        if "LastEvaluatedKey" not in resp or len(items) > 500:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    return [_hydrate(i, full) for i in items[:limit]]


def get_incident(incident_id: str):
    item = table().get_item(Key={"incident_id": incident_id}).get("Item")
    return _hydrate(item, full=True) if item else None


def similar(keywords: str, limit: int = 3) -> list:
    words = set(re.findall(r"[a-z0-9_]{4,}", keywords.lower()))
    scored = []
    for inc in list_incidents(50, full=True):
        d = inc.get("diagnosis") or {}
        if not d:
            continue
        text = " ".join([d.get("root_cause", ""), d.get("summary", ""), d.get("category", "")]).lower()
        score = sum(1 for w in words if w in text)
        if score:
            scored.append((score, inc))
    scored.sort(key=lambda x: -x[0])
    return [
        {"incident_id": i["incident_id"], "category": i["category"],
         "root_cause": i["diagnosis"].get("root_cause", ""),
         "fix_steps": i["diagnosis"].get("fix_steps", [])}
        for _, i in scored[:limit]
    ]
