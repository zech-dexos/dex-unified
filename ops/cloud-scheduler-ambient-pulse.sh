#!/usr/bin/env bash
set -euo pipefail

# Create/update the Cloud Scheduler trigger for Dex's durable ambient pulse.
# Cloud Scheduler may fire more often than cognition should occur; Firestore's
# claim_ambient_tick() remains the final atomic cadence gate.
#
# Required env:
#   PROJECT_ID       GCP project
#   REGION           Cloud Scheduler region
#   SERVICE_URL      Cloud Run service URL
#   PULSE_SECRET     Same secret configured on Cloud Run
#
# Optional:
#   JOB_NAME         defaults to dex-ambient-pulse
#   SCHEDULE         defaults to every minute
#   TIME_ZONE        defaults to UTC

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE_URL="${SERVICE_URL:?set SERVICE_URL}"
PULSE_SECRET="${PULSE_SECRET:?set PULSE_SECRET}"
JOB_NAME="${JOB_NAME:-dex-ambient-pulse}"
SCHEDULE="${SCHEDULE:-* * * * *}"
TIME_ZONE="${TIME_ZONE:-UTC}"

gcloud scheduler jobs describe "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" >/dev/null 2>&1 && EXISTS=1 || EXISTS=0

ARGS=(
  --project="$PROJECT_ID"
  --location="$REGION"
  --schedule="$SCHEDULE"
  --time-zone="$TIME_ZONE"
  --uri="${SERVICE_URL%/}/ambient-pulse"
  --http-method=POST
  --headers="X-Pulse-Secret=$PULSE_SECRET"
)

if [[ "$EXISTS" -eq 1 ]]; then
  gcloud scheduler jobs update http "$JOB_NAME" "${ARGS[@]}"
else
  gcloud scheduler jobs create http "$JOB_NAME" "${ARGS[@]}"
fi

echo "Ambient pulse scheduler configured: $JOB_NAME"
