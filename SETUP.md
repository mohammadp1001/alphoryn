# Alphoryn — Setup Guide

End-to-end steps to go from zero to a running paper-trading session.

---

## Prerequisites

Install these tools before starting:

| Tool | Install | Check |
|------|---------|-------|
| gcloud CLI | https://cloud.google.com/sdk/docs/install | `gcloud version` |
| Terraform | https://developer.hashicorp.com/terraform/install | `terraform version` |
| Python 3.11+ | https://python.org | `python --version` |
| Docker (webhook only) | https://docs.docker.com/get-docker/ | `docker version` |

---

## Step 1 — Alpaca paper account

1. Go to **https://alpaca.markets** → Sign up (free).
2. In the dashboard, select **Paper Trading** (top-left toggle).
3. Navigate to **API Keys** → **Generate New Key**.
4. Copy the **Key** (`PK…`) and **Secret** — the secret is shown only once.
5. Keep these handy for Step 3.

> Alpaca paper trading is completely free and uses simulated fills. No real money is involved.

---

## Step 2 — GCP project prerequisites

### 2a. Log in to gcloud

```bash
gcloud auth login
```

### 2b. Find your billing account ID

```bash
gcloud billing accounts list
```

Output looks like:
```
ACCOUNT_ID            NAME                OPEN
XXXXXX-XXXXXX-XXXXXX  My Billing Account  True
```

Copy the `ACCOUNT_ID` — you need it in Step 3.

### 2c. (Optional) Find your org ID

Only needed if your account is inside a GCP organisation. Skip if using a personal billing account.

```bash
gcloud organizations list
```

---

## Step 3 — Configure Terraform variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
project_id         = "alphoryn-prod-1234"   # pick a unique name + 4 random digits
project_name       = "alphoryn"
billing_account_id = "XXXXXX-XXXXXX-XXXXXX" # from Step 2b
org_id             = ""                      # leave empty for personal accounts
region             = "us-central1"

alpaca_api_key    = "PK..."                  # from Step 1
alpaca_api_secret = "..."                    # from Step 1
```

> `terraform.tfvars` is git-ignored. Never commit it.

---

## Step 4 — Terraform apply

```bash
# Inside terraform/
terraform init
terraform plan    # review what will be created
terraform apply   # type 'yes' when prompted
```

This creates (in order):
1. GCP project linked to your billing account
2. Enables 6 APIs (Secret Manager, Cloud Run, Trace, Logging, Artifact Registry, IAM)
3. Creates the `alphoryn-agent` service account
4. Grants it 4 IAM roles (secretAccessor, cloudtrace.agent, logWriter, run.invoker)
5. Creates `alpaca-api-key` and `alpaca-api-secret` in Secret Manager
6. Creates an Artifact Registry Docker repo

Total time: ~3–5 minutes (API enablement is the slow part).

After apply, note the printed outputs:

```
project_id           = "alphoryn-prod-1234"
agent_sa_email       = "alphoryn-agent@alphoryn-prod-1234.iam.gserviceaccount.com"
artifact_registry_url = "us-central1-docker.pkg.dev/alphoryn-prod-1234/alphoryn"
```

---

## Step 5 — Local authentication (Application Default Credentials)

```bash
gcloud config set project <your-project-id>
gcloud auth application-default login
```

This opens a browser window. Sign in with the same Google account that owns the project. The credentials are stored in `~/.config/gcloud/application_default_credentials.json` — the agent reads them automatically via the Google client libraries.

---

## Step 6 — Install the agent

```bash
cd ..  # back to project root
pip install -e ".[dev]"
# or with uv:
# uv pip install -e ".[dev]"
```

---

## Step 7 — Run the agent

```bash
export GOOGLE_CLOUD_PROJECT=alphoryn-prod-1234  # your project ID

# First-time setup: initialises the SQLite DB at ~/.algotrade/algotrade.db
algotrade setup

# Start a paper-trading session
algotrade run --strategy MOMENTUM --mode SEMI_AUTO --loss-limit 500
```

`SEMI_AUTO` mode always prompts for confirmation before placing an order. You have 60 seconds to type `confirm` or `skip` at the prompt.

---

## Rotating Alpaca credentials

Terraform uses `lifecycle { ignore_changes = [secret_data] }` so it won't overwrite secrets after the first apply. To rotate:

```bash
# Add a new version — Alpaca old keys remain valid until you disable them
gcloud secrets versions add alpaca-api-key    --data-file=- <<< "PK_NEW_KEY"
gcloud secrets versions add alpaca-api-secret --data-file=- <<< "NEW_SECRET"

# Optionally disable the old version
gcloud secrets versions disable alpaca-api-key    --version=1
gcloud secrets versions disable alpaca-api-secret --version=1
```

---

## Webhook — Alpaca outcome resolution (optional)

The webhook resolves trade outcomes in SQLite when Alpaca sends fill/cancel events, so you don't have to wait for the next session's polling pass.

### Build and push the Docker image

```bash
# Authenticate Docker to Artifact Registry (one-time)
gcloud auth configure-docker us-central1-docker.pkg.dev

IMAGE=us-central1-docker.pkg.dev/<project-id>/alphoryn/webhook:latest

docker build -t $IMAGE ./webhook
docker push  $IMAGE
```

### Create a webhook signing secret

```bash
# Generate a random secret and store it in Secret Manager
python -c "import secrets; print(secrets.token_hex(32))" | \
  gcloud secrets create alpaca-webhook-secret --data-file=-
```

Grant the agent SA access to it:
```bash
gcloud secrets add-iam-policy-binding alpaca-webhook-secret \
  --member="serviceAccount:alphoryn-agent@<project-id>.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Deploy to Cloud Run

```bash
gcloud run deploy alphoryn-webhook \
  --image $IMAGE \
  --region us-central1 \
  --service-account alphoryn-agent@<project-id>.iam.gserviceaccount.com \
  --set-secrets ALPACA_WEBHOOK_SECRET=alpaca-webhook-secret:latest \
  --no-allow-unauthenticated \
  --allow-unauthenticated   # remove this line — use --no-allow-unauthenticated
```

Actually use:
```bash
gcloud run deploy alphoryn-webhook \
  --image $IMAGE \
  --region us-central1 \
  --service-account alphoryn-agent@<project-id>.iam.gserviceaccount.com \
  --set-secrets ALPACA_WEBHOOK_SECRET=alpaca-webhook-secret:latest \
  --no-allow-unauthenticated
```

Get the webhook URL:
```bash
gcloud run services describe alphoryn-webhook \
  --region us-central1 \
  --format="value(status.url)"
```

### Register with Alpaca

In the Alpaca dashboard → **Events** → **Webhook** → add `<cloud-run-url>/webhook/alpaca`.

Alpaca will HMAC-sign every event with your `alpaca-webhook-secret`.

---

## CI/CD — GitHub Actions

The existing `.github/workflows/ci.yml` runs lint, type-check, and tests on every push. To add automated Terraform apply on merge to main, you need Workload Identity Federation:

```bash
# Create a Workload Identity Pool for GitHub Actions
gcloud iam workload-identity-pools create "github-actions" \
  --location="global" \
  --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc "github" \
  --location="global" \
  --workload-identity-pool="github-actions" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository"

# Bind the pool to the agent SA
gcloud iam service-accounts add-iam-policy-binding \
  alphoryn-agent@<project-id>.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/<project-number>/locations/global/workloadIdentityPools/github-actions/attribute.repository/mohammadp1001/alphoryn"
```

Add these secrets to GitHub repository settings:
- `GCP_PROJECT_ID` = your project ID
- `GCP_WORKLOAD_IDENTITY_PROVIDER` = the provider resource name from above

---

## Teardown

To destroy all GCP resources:

```bash
cd terraform
terraform destroy
```

> This deletes the GCP project and everything in it, including all secret versions. This is irreversible.
