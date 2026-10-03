import json
import os

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError("Missing required environment variable DATABASE_URL")


def handler(event, context):
    return {"statusCode": 200, "headers": {"content-type": "application/json"},
            "body": json.dumps({"status": "ok", "version": os.environ.get("APP_VERSION", "dev")})}
