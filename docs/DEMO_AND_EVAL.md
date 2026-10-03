# Demo script and evaluation

## 5-minute live demo
1. Show the dashboard (empty) and the healthy deploy: all three clouds green.
2. Actions -> deploy-target -> Run workflow -> **missing_env**. While it runs, explain: the same missing variable breaks all three clouds, in three different log systems.
3. When `notify` finishes (about 3-6 min), refresh the dashboard. Walk through: summary -> evidence quotes -> fix -> *How the agent investigated* (it chose which clouds to inspect).
4. Open the auto-created GitHub issue.
5. Run **bad_credentials**: only AWS fails. Point out the agent says GCP and Azure are healthy and does not blame them.
6. Run **none** to restore.

## Run the evaluation
```
export GITHUB_TOKEN=<token with Actions read/write>  GITHUB_REPO=<you>/deploydoc
export AGENT_URL=<cloud run url>  DASHBOARD_KEY=<key>
pip install requests
python eval/run_eval.py --runs 2
```
(PowerShell: `$env:GITHUB_TOKEN="..."` etc.) Each run takes ~10 min of CI; 5 scenarios x 2 runs is ~2 hours. Start with `--scenarios missing_env bad_credentials --runs 1`.

Metrics printed and saved to `results/*.csv`: root-cause category accuracy, affected-cloud accuracy, agent time, tool calls.
For your report, time one manual investigation of the same failure and compare.

## Use the tools from an MCP client (e.g. Claude Desktop)
```
cd agent && pip install -r requirements-mcp.txt
```
Add to the client's MCP config (set the same env vars as the agent):
```json
{"mcpServers":{"deploydoc":{"command":"python","args":["mcp_server.py"],"cwd":"<path>/agent",
  "env":{"GITHUB_TOKEN":"...","GCP_PROJECT_ID":"...","AWS_ACCESS_KEY_ID":"...","AWS_SECRET_ACCESS_KEY":"..."}}}}
```
Then ask: "Why did run 123 of my repo fail?" and the client can call the same evidence tools.

## Local offline test
`python tests/test_offline.py` runs the agent loop, tools and Lambda against fakes.
