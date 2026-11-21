<#
.SYNOPSIS
  1-command Praxis deploy to Google Cloud Run in asia-south1 (Mumbai).

.DESCRIPTION
  Enables APIs, provisions Artifact Registry, Secret Manager secrets (from the local root .env),
  Firestore (asia-south1) and BigQuery dataset praxis_audit, builds both images with Cloud Build
  (no local Docker needed), deploys praxis-backend then praxis-frontend, wires CORS, and smoke-tests
  both live URLs. Secret values are never printed.

.EXAMPLE
  .\deploy.ps1                       # Firestore + BigQuery production deploy
  .\deploy.ps1 -SqliteMode           # fast fallback: in-container SQLite, single instance
  .\deploy.ps1 -DryRun               # print every step/command, change nothing
#>
[CmdletBinding()]
param(
    [string]$ProjectId = "praxis-velox-2026",
    [string]$Region = "asia-south1",
    [switch]$SqliteMode,
    [switch]$DryRun,
    [switch]$SkipSecrets
)

$ErrorActionPreference = "Continue"   # native gcloud stderr must not abort PS 5.1; we check exit codes explicitly
Set-StrictMode -Version 2.0
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Repo = "praxis"
$Tag = Get-Date -Format "yyyyMMdd-HHmmss"
$BackendImage = "$Region-docker.pkg.dev/$ProjectId/$Repo/praxis-backend:$Tag"
$FrontendImage = "$Region-docker.pkg.dev/$ProjectId/$Repo/praxis-frontend:$Tag"
$Secrets = @("GEMINI_API_KEY", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "PRAXIS_AGENT_TOKEN")

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    [ok] $Text" -ForegroundColor Green }

$script:MaskValues = @()
function Hide-Secrets([string]$Text) {
    foreach ($v in $script:MaskValues) { if ($v -and $v.Length -ge 4) { $Text = $Text.Replace($v, "***") } }
    return $Text
}

function Invoke-Gcloud {
    param([string[]]$Arguments, [switch]$AllowFail, [switch]$Capture)
    if ($DryRun) {
        Write-Host ("    [dry-run] gcloud " + (Hide-Secrets ($Arguments -join " "))) -ForegroundColor DarkGray
        if ($Capture) { return "" }
        return
    }
    if ($Capture) {
        $out = & gcloud @Arguments 2>$null
        if ($LASTEXITCODE -ne 0 -and -not $AllowFail) { throw (Hide-Secrets "gcloud $($Arguments -join ' ') failed ($LASTEXITCODE)") }
        return ($out | Out-String).Trim()
    }
    & gcloud @Arguments
    if ($LASTEXITCODE -ne 0 -and -not $AllowFail) { throw (Hide-Secrets "gcloud $($Arguments -join ' ') failed ($LASTEXITCODE)") }
}

function Test-Gcloud([string[]]$Arguments) {
    if ($DryRun) { return $false }
    & gcloud @Arguments *> $null
    return ($LASTEXITCODE -eq 0)
}

function Read-DotEnv([string]$Path) {
    $vars = @{}
    if (-not (Test-Path $Path)) { return $vars }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith("#") -or -not $t.Contains("=")) { continue }
        $i = $t.IndexOf("=")
        $vars[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim().Trim('"').Trim("'")
    }
    return $vars
}

try {
    # ------------------------------------------------------------------ 0. preflight
    Write-Step "Preflight ($ProjectId / $Region$(if ($SqliteMode) { ' / SQLITE MODE' }))"
    if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { throw "gcloud CLI not found. Install https://cloud.google.com/sdk/docs/install" }
    $envVars = Read-DotEnv (Join-Path $Root ".env")
    # Optional treasury-reviewer passcode (RBAC on decide / reset / policy writes / evals run). Taken from the
    # process env (preferred, keeps it out of files) or .env; stored only in Secret Manager, never in the frontend.
    $reviewerToken = if ($env:PRAXIS_REVIEWER_TOKEN) { $env:PRAXIS_REVIEWER_TOKEN } else { $envVars["PRAXIS_REVIEWER_TOKEN"] }
    if ($reviewerToken) {
        $envVars["PRAXIS_REVIEWER_TOKEN"] = $reviewerToken
        $Secrets += "PRAXIS_REVIEWER_TOKEN"
    }
    $script:MaskValues = @($Secrets | ForEach-Object { $envVars[$_] } | Where-Object { $_ })
    foreach ($name in $Secrets) {
        if (-not $SkipSecrets -and -not $envVars[$name]) { throw "Root .env is missing $name (needed to seed Secret Manager)." }
    }
    $billing = Invoke-Gcloud -Arguments @("billing", "projects", "describe", $ProjectId, "--format=value(billingEnabled)") -Capture -AllowFail
    if ($DryRun) {
        Write-Host "    [dry-run] billing gate skipped" -ForegroundColor DarkGray
    } elseif ($billing -ne "True") {
        Write-Host "`nBilling is NOT enabled on $ProjectId - Cloud Run, Cloud Build and Firestore require it." -ForegroundColor Yellow
        Write-Host "Link a billing account, then re-run this script:" -ForegroundColor Yellow
        Write-Host "  gcloud billing accounts list" -ForegroundColor White
        Write-Host "  gcloud billing projects link $ProjectId --billing-account=XXXXXX-XXXXXX-XXXXXX" -ForegroundColor White
        exit 2
    }
    Invoke-Gcloud -Arguments @("config", "set", "project", $ProjectId, "--quiet")
    Write-Ok "billing enabled, project selected"

    # ------------------------------------------------------------------ 1. APIs
    Write-Step "Enabling required APIs"
    Invoke-Gcloud -Arguments @("services", "enable", "run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
        "secretmanager.googleapis.com", "firestore.googleapis.com", "bigquery.googleapis.com", "iam.googleapis.com", "--quiet")
    Write-Ok "APIs enabled"

    # ------------------------------------------------------------------ 2. identities
    Write-Step "Granting runtime / build roles to the default compute service account"
    $projectNumber = Invoke-Gcloud -Arguments @("projects", "describe", $ProjectId, "--format=value(projectNumber)") -Capture
    if ($DryRun) { $projectNumber = "000000000000" }
    $RuntimeSa = "$projectNumber-compute@developer.gserviceaccount.com"
    foreach ($role in @("roles/secretmanager.secretAccessor", "roles/datastore.user", "roles/bigquery.dataEditor", "roles/bigquery.jobUser",
                        "roles/artifactregistry.writer", "roles/logging.logWriter", "roles/storage.objectViewer")) {
        Invoke-Gcloud -Arguments @("projects", "add-iam-policy-binding", $ProjectId, "--member=serviceAccount:$RuntimeSa", "--role=$role",
            "--condition=None", "--quiet", "--no-user-output-enabled")
    }
    Write-Ok "roles granted to $RuntimeSa"

    # ------------------------------------------------------------------ 3. Artifact Registry
    Write-Step "Artifact Registry repo '$Repo' ($Region)"
    if (-not (Test-Gcloud @("artifacts", "repositories", "describe", $Repo, "--location=$Region"))) {
        Invoke-Gcloud -Arguments @("artifacts", "repositories", "create", $Repo, "--repository-format=docker", "--location=$Region",
            "--description=Praxis container images", "--quiet")
    }
    Write-Ok "repository ready"

    # ------------------------------------------------------------------ 4. Secret Manager (values never echoed)
    if (-not $SkipSecrets) {
        Write-Step "Seeding Secret Manager from root .env"
        foreach ($name in $Secrets) {
            if (-not (Test-Gcloud @("secrets", "describe", $name))) {
                Invoke-Gcloud -Arguments @("secrets", "create", $name, "--replication-policy=user-managed", "--locations=$Region", "--quiet")
            }
            if ($DryRun) {
                Write-Host "    [dry-run] add new version to secret $name ($($envVars[$name].Length) chars, value hidden)" -ForegroundColor DarkGray
                continue
            }
            $tmp = [System.IO.Path]::GetTempFileName()
            try {
                [System.IO.File]::WriteAllText($tmp, $envVars[$name])
                Invoke-Gcloud -Arguments @("secrets", "versions", "add", $name, "--data-file=$tmp", "--quiet", "--no-user-output-enabled")
            } finally {
                Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            }
            Write-Ok "$name -> new version"
        }
    }

    # ------------------------------------------------------------------ 5. Firestore + BigQuery
    if ($SqliteMode) {
        $storageBackend = "sqlite"; $auditBackend = "sqlite"; $maxInstances = "1"   # one ledger per instance => single instance
        Write-Step "SQLite fallback mode: skipping Firestore/BigQuery provisioning (max-instances=1)"
    } else {
        $storageBackend = "firestore"; $auditBackend = "bigquery"; $maxInstances = "1"   # idempotency single-flight is in-process
        Write-Step "Firestore (native, $Region) and BigQuery dataset praxis_audit"
        if (-not (Test-Gcloud @("firestore", "databases", "describe", "--database=(default)"))) {
            Invoke-Gcloud -Arguments @("firestore", "databases", "create", "--database=(default)", "--location=$Region", "--type=firestore-native", "--quiet")
        }
        if ($DryRun) {
            Write-Host "    [dry-run] bq --location=$Region mk -d ${ProjectId}:praxis_audit (if absent)" -ForegroundColor DarkGray
        } else {
            & bq --project_id=$ProjectId show praxis_audit *> $null
            if ($LASTEXITCODE -ne 0) {
                & bq --project_id=$ProjectId --location=$Region mk -d --description "Praxis immutable audit (POL-RBI-AUDIT-5Y)" praxis_audit
                if ($LASTEXITCODE -ne 0) { throw "bq mk praxis_audit failed" }
            }
        }
        Write-Ok "Firestore + BigQuery ready (table audit_decisions is auto-created by the backend)"
    }

    # ------------------------------------------------------------------ 6. backend
    Write-Step "Building praxis-backend with Cloud Build"
    Invoke-Gcloud -Arguments @("builds", "submit", $Root, "--config=cloudbuild.backend.yaml", "--substitutions=_IMAGE=$BackendImage", "--quiet")
    Write-Step "Deploying praxis-backend to Cloud Run ($Region)"
    $secretNames = @($Secrets)
    if (-not $reviewerToken -and (Test-Gcloud @("secrets", "describe", "PRAXIS_REVIEWER_TOKEN"))) {
        $secretNames += "PRAXIS_REVIEWER_TOKEN"   # keep an already-provisioned reviewer passcode mounted on redeploy
    }
    $secretMap = ($secretNames | ForEach-Object { "$_=$($_):latest" }) -join ","
    Write-Ok ("reviewer RBAC: " + $(if ($secretNames -contains "PRAXIS_REVIEWER_TOKEN") { "ON (PRAXIS_REVIEWER_TOKEN from Secret Manager)" } else { "OFF (no PRAXIS_REVIEWER_TOKEN)" }))
    Invoke-Gcloud -Arguments @("run", "deploy", "praxis-backend", "--image=$BackendImage", "--region=$Region", "--platform=managed",
        "--allow-unauthenticated", "--min-instances=1", "--max-instances=$maxInstances", "--cpu=1", "--memory=1Gi", "--port=8080",
        "--timeout=300", "--service-account=$RuntimeSa", "--set-secrets=$secretMap",
        "--set-env-vars=STORAGE_BACKEND=$storageBackend,AUDIT_BACKEND=$auditBackend,GCP_PROJECT_ID=$ProjectId,GCP_REGION=$Region",
        "--quiet")
    $BackendUrl = Invoke-Gcloud -Arguments @("run", "services", "describe", "praxis-backend", "--region=$Region", "--format=value(status.url)") -Capture
    if ($DryRun) { $BackendUrl = "https://praxis-backend-DRYRUN-el.a.run.app" }
    Write-Ok "backend live at $BackendUrl"

    # ------------------------------------------------------------------ 7. frontend
    Write-Step "Building praxis-frontend (NEXT_PUBLIC_API_URL=$BackendUrl)"
    $agentToken = $envVars["PRAXIS_AGENT_TOKEN"]
    Invoke-Gcloud -Arguments @("builds", "submit", $Root, "--config=cloudbuild.frontend.yaml",
        "--substitutions=_IMAGE=$FrontendImage,_API_URL=$BackendUrl,_AGENT_TOKEN=$agentToken", "--quiet")
    Write-Step "Deploying praxis-frontend to Cloud Run ($Region)"
    Invoke-Gcloud -Arguments @("run", "deploy", "praxis-frontend", "--image=$FrontendImage", "--region=$Region", "--platform=managed",
        "--allow-unauthenticated", "--min-instances=1", "--max-instances=3", "--cpu=1", "--memory=512Mi", "--port=8080", "--quiet")
    $FrontendUrl = Invoke-Gcloud -Arguments @("run", "services", "describe", "praxis-frontend", "--region=$Region", "--format=value(status.url)") -Capture
    if ($DryRun) { $FrontendUrl = "https://praxis-frontend-DRYRUN-el.a.run.app" }
    Write-Ok "frontend live at $FrontendUrl"

    # ------------------------------------------------------------------ 8. CORS
    Write-Step "Allowing $FrontendUrl in backend CORS"
    Invoke-Gcloud -Arguments @("run", "services", "update", "praxis-backend", "--region=$Region",
        "--update-env-vars=^##^ALLOWED_ORIGINS=$FrontendUrl,http://localhost:3000", "--quiet")
    Write-Ok "ALLOWED_ORIGINS updated"

    # ------------------------------------------------------------------ 9. smoke test
    Write-Step "Post-deploy smoke test"
    if ($DryRun) {
        Write-Host "    [dry-run] Invoke-RestMethod $BackendUrl/health ; Invoke-WebRequest $FrontendUrl/ and /console" -ForegroundColor DarkGray
    } else {
        $health = Invoke-RestMethod -Uri "$BackendUrl/health" -TimeoutSec 60
        if ($health.status -ne "ok") { throw "Backend /health did not return status=ok" }
        Write-Ok ("backend /health ok - storage={0}, audit={1}, region={2}, razorpay_configured={3}" -f `
            $health.storage_backend, $health.audit_backend, $health.gcp_region, $health.razorpay_configured)
        foreach ($path in @("/", "/console")) {
            $resp = Invoke-WebRequest -Uri "$FrontendUrl$path" -UseBasicParsing -TimeoutSec 60
            if ($resp.StatusCode -ne 200) { throw "Frontend $path returned $($resp.StatusCode)" }
            Write-Ok "frontend $path -> 200"
        }
    }

    Write-Host "`nPraxis is live in $Region (Mumbai):" -ForegroundColor Green
    Write-Host "  Console : $FrontendUrl/console"
    Write-Host "  Landing : $FrontendUrl"
    Write-Host "  API     : $BackendUrl/health"
    exit 0
} catch {
    Write-Host "`nDEPLOY FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
