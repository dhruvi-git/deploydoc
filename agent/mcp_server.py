"""Expose DeployDoc's evidence tools as an MCP server (stdio).

Run:   pip install -r requirements-mcp.txt && python mcp_server.py
Then add it to any MCP client (e.g. Claude Desktop) - see docs/DEMO_AND_EVAL.md.
Uses the same environment variables as the agent.
"""
import functools

from mcp.server.fastmcp import FastMCP

from app import tools

mcp = FastMCP("deploydoc-evidence")


def _safe(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    return inner


for spec in tools.TOOLS:
    if spec["fn"]:
        mcp.add_tool(_safe(spec["fn"]), name=spec["name"], description=spec["description"])

if __name__ == "__main__":
    mcp.run()
