"""All configuration comes from environment variables (set in the Cloud Run console)."""
import os


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


# --- GitHub ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
CREATE_GITHUB_ISSUE = _bool("CREATE_GITHUB_ISSUE", True)

# --- GCP / Gemini on Vertex AI ---
GCP_PROJECT = os.getenv("GCP_PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
# Newer Gemini models are not served from every region; "global" is the safe default.
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
MAX_STEPS = int(os.getenv("MAX_STEPS", "12"))
GCP_TARGET_SERVICE = os.getenv("GCP_TARGET_SERVICE", "deploydoc-target")

# --- AWS (Mumbai) ---
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
AWS_LOG_GROUP = os.getenv("AWS_LOG_GROUP", "/aws/lambda/deploydoc-target")
DDB_TABLE = os.getenv("DDB_TABLE", "deploydoc-incidents")

# --- Azure (Central India) ---
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_LOG_WORKSPACE_ID = os.getenv("AZURE_LOG_WORKSPACE_ID", "")
AZURE_APP_NAME = os.getenv("AZURE_APP_NAME", "deploydoc-target")

# --- API auth ---
AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")      # shared with the AWS ingest Lambda
DASHBOARD_KEY = os.getenv("DASHBOARD_KEY", "")  # typed into the dashboard
