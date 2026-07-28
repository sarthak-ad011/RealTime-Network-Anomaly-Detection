set -euo pipefail
REGION="${AWS_REGION:-ap-south-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$REGISTRY"
IMAGE="$REGISTRY/anomaly-mlops:$TAG"
docker build -f src/serving/Dockerfile -t "$IMAGE" .
docker push "$IMAGE"
echo "Pushed: $IMAGE"