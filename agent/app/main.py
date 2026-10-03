import hmac

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent, config, reports, store, tools

app = FastAPI(title="DeployDoc Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _require(given, expected):
    if not expected or not hmac.compare_digest(given or "", expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


class Incident(BaseModel):
    repo: str
    run_id: int
    sha: str
    branch: str = ""
    run_url: str = ""
    workflow: str = ""
    actor: str = ""
    incident_id: str = ""


@app.get("/")
def root():
    return {"service": "deploydoc-agent", "model": config.GEMINI_MODEL, "status": "ok"}


@app.post("/investigate")
def investigate(inc: Incident, x_deploydoc_token: str | None = Header(default=None)):
    _require(x_deploydoc_token, config.AGENT_TOKEN)
    result = agent.investigate(inc.model_dump())
    result["issue_url"] = ""
    if config.CREATE_GITHUB_ISSUE and config.GITHUB_TOKEN:
        try:
            d = result["diagnosis"]
            result["issue_url"] = tools.create_issue(
                inc.repo, f"[DeployDoc] {d['summary'][:120]}", reports.render_markdown(inc.model_dump(), d))
        except Exception as e:
            result["issue_error"] = str(e)[:300]
    return result


@app.get("/api/incidents")
def incidents(x_api_key: str | None = Header(default=None)):
    _require(x_api_key, config.DASHBOARD_KEY)
    return {"incidents": store.list_incidents(30)}


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: str, x_api_key: str | None = Header(default=None)):
    _require(x_api_key, config.DASHBOARD_KEY)
    item = store.get_incident(incident_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return item
