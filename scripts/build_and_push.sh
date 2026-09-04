#!/usr/bin/env bash
# Manual image build + push to ECR. CI/CD automates this in .github/workflows/cicd.yaml.
#
# Always builds for linux/amd64: the EKS node groups are x86_64, so an image built
# natively on an Apple Silicon workstation would fail with an exec format error.
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
PLATFORM="${PLATFORM:-linux/amd64}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
IMAGE="$REGISTRY/anomaly-mlops:$TAG"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

# --provenance=false keeps the push a plain image manifest rather than an OCI index,
# which older Kubernetes image pullers handle more predictably.
docker buildx build \
  --platform "$PLATFORM" \
  --provenance=false \
  -f src/serving/Dockerfile \
  -t "$IMAGE" \
  --push \
  .

echo "Pushed: $IMAGE"
