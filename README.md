# DeployDoc: a multi-cloud AI agent that investigates failed deployments

**Problem.** One commit is deployed to AWS, Azure and GCP. When it fails, the cause is scattered across the CI log
and three different log systems. DeployDoc collects that evidence itself, correlates it, and tells you the root cause,
the exact log lines that prove it, and a concrete fix.

```
git push -> GitHub Actions: build image -> deploy to GCP (Terraform) + Azure + AWS -> smoke test each
                  | any job fails
                  v
        notify job -> AWS Lambda (ingest) -> DynamoDB + S3
                              |
                              v
              GCP Cloud Run: agent (Gemini on Vertex AI, tool-calling loop)
                 tools: GitHub logs/diff | CloudWatch | Azure Log Analytics | Cloud Logging | past incidents
                              |
              diagnosis -> DynamoDB, GitHub issue, dashboard (Azure Static Web Apps)
```

| Cloud | Region | Services used |
|---|---|---|
| AWS | ap-south-1 (Mumbai) | Lambda (ingest + deploy target), DynamoDB, S3, CloudWatch |
| Azure | Central India | Container Apps (deploy target), Log Analytics, Static Web Apps |
| GCP | asia-south1 (Mumbai) | Cloud Run (agent + deploy target), Vertex AI (Gemini), Cloud Logging, Artifact Registry, Cloud Storage (Terraform state) |

Also: Python/FastAPI, Docker, GitHub Actions, **Terraform** (provisions the GCP deploy target), **MCP** (`agent/mcp_server.py` exposes the same evidence tools to any MCP client).

## Repo map
| Path | What it is |
|---|---|
| `agent/` | The AI agent (FastAPI) + `mcp_server.py` |
| `aws/lambda_ingest/` | Webhook receiver, stores incidents, calls the agent |
| `sample-app/` | The service being deployed (container + Lambda version) |
| `infra/terraform/` | Cloud Run target, deployed by CI |
| `.github/workflows/` | `deploy.yml` (3-cloud deploy + failure injection + notify), `build-agent.yml` |
| `dashboard/` | Static incident dashboard |
| `eval/run_eval.py` | Runs every failure scenario and scores the agent |
| `docs/` | **Start with `docs/IMPLEMENTATION_GUIDE.md`**, then `docs/DEMO_AND_EVAL.md` |

## Failure scenarios (run from Actions -> deploy-target -> Run workflow)
`missing_env` (all 3 clouds) · `bad_port` (GCP, Azure) · `bad_image_tag` (GCP, Azure) · `bad_credentials` (AWS) · `bad_resources` (GCP)

The agent is never told which scenario ran.

## Honest limits
- Built and unit-tested offline (agent loop, tools, Lambda, API). The cloud wiring is verified by following the guide, so expect to fix a typo or two in console settings.
- The agent reads evidence and *suggests* fixes. It does not change your infrastructure.
- Secrets are plain env vars in Cloud Run for speed. For production use Secret Manager.
