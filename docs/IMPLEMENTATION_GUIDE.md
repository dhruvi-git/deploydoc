# Implementation guide (console/GUI, baby steps)

Console menus change names now and then. If a label differs slightly, look for the closest match.
Do the parts **in order**. Keep a notepad open: you will collect values (marked **[SAVE]**) and use them later.

Naming used everywhere (please keep exactly): target service/app/function = `deploydoc-target`,
DynamoDB table = `deploydoc-incidents`, Artifact Registry repo = `deploydoc`.

---
## Part 0: Prepare (10 min)
1. Make sure you have accounts: GitHub, Google Cloud (billing enabled), AWS, Azure (subscription).
2. Make 3 random secrets (any long random text, 30+ chars, letters+digits). Use a password generator. **[SAVE]**
   - `WEBHOOK_TOKEN` (GitHub -> AWS Lambda)
   - `AGENT_TOKEN` (AWS Lambda -> agent)
   - `DASHBOARD_KEY` (dashboard -> agent)

## Part 1: GitHub repo (10 min)
1. github.com -> **New repository** -> name `deploydoc` -> **Public** (makes the container package easy) -> Create.
2. Unzip the project. Upload everything (the hidden `.github` folder too: on Mac press Cmd+Shift+. to see it).
   Easiest: in a terminal inside the unzipped folder:
   ```
   git init && git add . && git commit -m "DeployDoc" && git branch -M main
   git remote add origin https://github.com/<you>/deploydoc.git && git push -u origin main
   ```
3. Create a token for the agent: profile photo -> **Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens -> Generate new token**.
   - Repository access: *Only select repositories* -> `deploydoc`
   - Permissions: **Actions: Read-only**, **Contents: Read-only**, **Issues: Read and write**
   - Copy the token. **[SAVE] `GITHUB_TOKEN`**
4. Repo -> **Settings -> Secrets and variables -> Actions**. You will add entries here as you go (tabs: *Secrets* and *Variables*).
   Add now, as **Secrets**: `DEPLOYDOC_TOKEN` = your `WEBHOOK_TOKEN`.

## Part 2: GCP (Mumbai, asia-south1) (25 min)
1. console.cloud.google.com -> project picker -> **New project** -> name `deploydoc` -> Create. **[SAVE] Project ID** (not the name).
2. **APIs & Services -> Enable APIs**: enable *Cloud Run Admin API*, *Artifact Registry API*, *Vertex AI API*, *Cloud Logging API*, *Cloud Resource Manager API*, *IAM API*.
3. **Artifact Registry -> Create repository**: name `deploydoc`, format **Docker**, location **Region: asia-south1 (Mumbai)** -> Create.
4. **Cloud Storage -> Create bucket**: any unique name like `deploydoc-tfstate-<yourname>`, location type *Region* -> `asia-south1`, keep other defaults. **[SAVE] bucket name**
5. **IAM & Admin -> Service accounts -> Create**:
   - Name `deploydoc-ci`. Grant roles: **Cloud Run Admin**, **Service Account User**, **Artifact Registry Writer**, **Storage Object Admin**. Done.
   - Open it -> **Keys -> Add key -> Create new key -> JSON**. A file downloads. Open it, copy the whole content. **[SAVE] `GCP_SA_KEY`**
6. Create another service account `deploydoc-agent` with roles **Vertex AI User** and **Logs Viewer**. (No key needed.)
7. In GitHub (Settings -> Secrets and variables -> Actions):
   - Secret `GCP_SA_KEY` = the JSON text
   - Variables: `GCP_PROJECT_ID` = your project id, `TF_STATE_BUCKET` = your bucket name

## Part 3: AWS (Mumbai, ap-south-1) (35 min)
Top-right region selector -> **Asia Pacific (Mumbai) ap-south-1**. Stay there for everything. Note your **12-digit Account ID** (account menu). **[SAVE]**

**3a. DynamoDB table.** DynamoDB -> Create table -> name `deploydoc-incidents`, partition key `incident_id` (String) -> Customize settings -> capacity mode **On-demand** -> Create.

**3b. S3 bucket.** S3 -> Create bucket -> name e.g. `deploydoc-reports-<yourname>-<digits>` -> region Mumbai -> keep "Block all public access" ON -> Create. **[SAVE] bucket name**

**3c. Deploy target Lambda.**
1. Lambda -> Create function -> Author from scratch -> name `deploydoc-target`, runtime **Python 3.12** -> Create.
2. **Code** tab -> *Runtime settings* -> Edit -> Handler = `handler.handler` -> Save.
3. **Configuration -> Function URL -> Create function URL** -> Auth type **NONE** -> Save. Copy the URL. **[SAVE] `AWS_TARGET_URL`**
4. (Nothing else; GitHub Actions will upload the code.)

**3d. Ingest Lambda.**
1. Create function -> name `deploydoc-ingest`, Python 3.12 -> Create.
2. Code tab: open `lambda_function.py`, delete all, paste the content of `aws/lambda_ingest/handler.py`. Rename the file to `handler.py` (right-click -> Rename) and set the Handler to `handler.handler` (Runtime settings -> Edit). Click **Deploy**.
3. **Configuration -> General configuration -> Edit**: Timeout **3 min 0 sec**, Memory 256 MB -> Save.
4. **Configuration -> Environment variables -> Edit**, add:
   `TABLE_NAME` = `deploydoc-incidents`, `BUCKET_NAME` = your bucket, `WEBHOOK_TOKEN`, `AGENT_TOKEN`, and `AGENT_URL` = `https://placeholder` (you will fix it in Part 6).
5. **Configuration -> Permissions** -> click the role name -> **Add permissions -> Create inline policy -> JSON**, paste (replace `ACCOUNT_ID` and `YOUR_BUCKET`):
   ```json
   {"Version":"2012-10-17","Statement":[
     {"Effect":"Allow","Action":["dynamodb:PutItem","dynamodb:UpdateItem"],
      "Resource":"arn:aws:dynamodb:ap-south-1:ACCOUNT_ID:table/deploydoc-incidents"},
     {"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::YOUR_BUCKET/*"}]}
   ```
   Name it `deploydoc-ingest-policy` -> Create.
6. **Configuration -> Function URL -> Create** -> Auth type **NONE** -> Save. **[SAVE] `INGEST_URL`** (the token header protects it).

**3e. Two IAM users.** IAM -> Users -> Create user (no console access):
- `deploydoc-ci`: Attach policies directly -> Create policy -> JSON:
  ```json
  {"Version":"2012-10-17","Statement":[{"Effect":"Allow",
   "Action":["lambda:UpdateFunctionCode","lambda:UpdateFunctionConfiguration","lambda:GetFunction","lambda:GetFunctionConfiguration"],
   "Resource":"arn:aws:lambda:ap-south-1:ACCOUNT_ID:function:deploydoc-target"}]}
  ```
  Then user -> **Security credentials -> Create access key -> Other**. **[SAVE] `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`**
- `deploydoc-agent-reader`: policy:
  ```json
  {"Version":"2012-10-17","Statement":[
   {"Effect":"Allow","Action":["logs:FilterLogEvents","logs:DescribeLogStreams","logs:GetLogEvents"],
    "Resource":"arn:aws:logs:ap-south-1:ACCOUNT_ID:log-group:/aws/lambda/deploydoc-target:*"},
   {"Effect":"Allow","Action":["dynamodb:Scan","dynamodb:GetItem"],
    "Resource":"arn:aws:dynamodb:ap-south-1:ACCOUNT_ID:table/deploydoc-incidents"}]}
  ```
  Create an access key too. **[SAVE] as `AGENT_AWS_KEY_ID` / `AGENT_AWS_SECRET`**

**3f. GitHub.** Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (the *ci* user). Variables: `AWS_TARGET_URL`, `DEPLOYDOC_WEBHOOK_URL` = `INGEST_URL`.

## Part 4: Azure (Central India) (35 min)
portal.azure.com.
1. **Resource groups -> Create**: name `deploydoc-rg`, region **Central India**. **[SAVE]**
2. **Log Analytics workspaces -> Create**: same group, name `deploydoc-logs`, region Central India. After creation open it -> **Overview** -> copy **Workspace ID** (a GUID). **[SAVE] `AZURE_LOG_WORKSPACE_ID`**
3. **Container Apps -> Create**:
   - Resource group `deploydoc-rg`, name **`deploydoc-target`**, region Central India.
   - Container Apps environment -> *Create new* -> Monitoring tab -> Logs destination **Azure Log Analytics**, pick `deploydoc-logs` -> Create.
   - Container tab: tick **Use quickstart image**.
   - Ingress tab: Enable, **Accepting traffic from anywhere**, Target port **80** (CI changes it to 8080). Create.
4. **App registrations -> New registration**: name `deploydoc-sp` -> Register. Copy **Application (client) ID** and **Directory (tenant) ID**. **[SAVE]**
   Then **Certificates & secrets -> New client secret** -> copy the **Value** immediately. **[SAVE] `AZURE_CLIENT_SECRET`**
5. Resource group `deploydoc-rg` -> **Access control (IAM) -> Add -> Add role assignment** -> role **Contributor** -> Members -> select `deploydoc-sp` -> Review + assign. Repeat with role **Log Analytics Reader** (if the agent later gets 403 on Azure queries, this is why).
6. **Subscriptions** -> copy **Subscription ID**.
7. Build `AZURE_CREDENTIALS` (one JSON, save as a GitHub secret):
   ```json
   {"clientId":"<client id>","clientSecret":"<secret value>","subscriptionId":"<sub id>","tenantId":"<tenant id>"}
   ```
8. GitHub Secret `AZURE_CREDENTIALS`; Variables `AZURE_RESOURCE_GROUP` = `deploydoc-rg`, `AZURE_CONTAINER_APP` = `deploydoc-target`.
9. Dashboard host: **Static Web Apps -> Create** -> plan **Free**, resource group `deploydoc-rg`, name `deploydoc-dashboard`, deployment: **GitHub** -> sign in, choose repo `deploydoc`, branch `main`. Build presets **Custom**; App location `/dashboard`; API location empty; Output location empty. Create.
   Azure adds a workflow file to your repo; run `git pull` later. Your site URL appears on the resource overview. **[SAVE]**

## Part 5: Build and deploy the agent on GCP (20 min)
1. GitHub -> Actions -> **build-agent** -> Run workflow. Wait for green. (This pushes `agent:latest` to Artifact Registry.)
2. GCP **Cloud Run -> Create service -> Deploy one revision from an existing container image** -> *Select* -> Artifact Registry -> `deploydoc` -> `agent` -> `latest`.
3. Service name `deploydoc-agent`, region **asia-south1**, **Allow unauthenticated invocations**.
4. Expand **Container(s), Volumes, Networking, Security**:
   - Container: memory 512 MiB, request timeout **300** s, max instances 2.
   - Security tab: Service account = `deploydoc-agent`.
   - Variables & secrets -> add these environment variables:

| Name | Value |
|---|---|
| `GITHUB_TOKEN` | fine-grained token from Part 1 |
| `GCP_PROJECT_ID` | your project id |
| `VERTEX_LOCATION` | `global` |
| `GEMINI_MODEL` | `gemini-3.5-flash` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | the **agent-reader** keys |
| `AWS_REGION` | `ap-south-1` |
| `AWS_LOG_GROUP` | `/aws/lambda/deploydoc-target` |
| `DDB_TABLE` | `deploydoc-incidents` |
| `AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` | from Part 4 |
| `AZURE_LOG_WORKSPACE_ID` | from Part 4 |
| `AZURE_APP_NAME` | `deploydoc-target` |
| `AGENT_TOKEN` | same as in the ingest Lambda |
| `DASHBOARD_KEY` | your dashboard key |

5. Create. Copy the service URL. **[SAVE] `AGENT_URL`**. Open it in a browser: you should see `{"service":"deploydoc-agent",...}`.
6. If you later get a model 404, open Vertex AI -> Model Garden, find a current Gemini Flash model id and change `GEMINI_MODEL` (Edit & deploy new revision). Model names get retired over time (`gemini-2.5-flash` retires 16 Oct 2026).

## Part 6: Connect everything (5 min)
1. AWS Lambda `deploydoc-ingest` -> Environment variables -> set `AGENT_URL` to the Cloud Run URL (no trailing slash).
2. Double-check GitHub **Variables**: `GCP_PROJECT_ID`, `TF_STATE_BUCKET`, `AZURE_RESOURCE_GROUP`, `AZURE_CONTAINER_APP`, `AWS_TARGET_URL`, `DEPLOYDOC_WEBHOOK_URL`.
   **Secrets**: `GCP_SA_KEY`, `AZURE_CREDENTIALS`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DEPLOYDOC_TOKEN`.

## Part 7: First healthy deploy (15 min)
1. Actions -> **deploy-target** -> Run workflow -> scenario `none`.
2. Expect **deploy-azure to fail** the first time: the GHCR image is private. Fix: GitHub profile -> **Packages** -> `deploydoc-target` -> Package settings -> *Change visibility* -> **Public**. (Also lets the agent diagnose a real failure: try it!)
3. Re-run failed jobs. All green means: Cloud Run, Azure Container App and Lambda all answer `/health` with the new version.
   If it fails and DeployDoc diagnoses it, great: that is the product working.

## Part 8: Dashboard (2 min)
Open the Static Web Apps URL -> **Connection** -> paste Agent URL and Dashboard key -> Save.

## Part 9: Cleanup / cost
Everything scales to zero or is free-tier sized, but delete after grading: Cloud Run services, Artifact Registry repo, bucket, project;
Lambda, DynamoDB, S3, IAM users; the Azure resource group `deploydoc-rg` (deletes it all). Revoke the GitHub token.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| `notify` step prints `unauthorized` | `DEPLOYDOC_TOKEN` secret differs from Lambda `WEBHOOK_TOKEN` |
| Lambda returns 502 `agent` error | `AGENT_URL` wrong, or `AGENT_TOKEN` differs |
| Agent 500 with Vertex error | Vertex AI API not enabled, SA role missing, or model retired (change `GEMINI_MODEL`) |
| Terraform: bucket not found | `TF_STATE_BUCKET` variable wrong |
| Terraform 403 on IAM member | Add `Cloud Run Admin` to `deploydoc-ci` |
| Azure tools return error | Log table not created yet (run the app once) or SP lacks reader role |
| Dashboard "Wrong dashboard key" | Key differs from the Cloud Run `DASHBOARD_KEY` |
