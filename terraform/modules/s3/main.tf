variable "environment" { type = string }

resource "aws_s3_bucket" "artifacts" {
  bucket = "anomaly-mlops-artifacts-${var.environment}"

  # This stack is deliberately torn down between demo sessions, and the bucket is
  # never empty when that happens: every prediction writes one object, so a single
  # afternoon of load leaves >100k of them, plus a version and a delete marker each
  # because versioning is on below. Without this, `terraform destroy` fails on
  # BucketNotEmpty partway through and leaves a half-destroyed stack still billing —
  # the EKS control plane and NAT gateway being the expensive parts.
  #
  # The tradeoff is real: destroy now deletes the MLflow artifacts and the prediction
  # log with the bucket. That is the intended posture here (Git and the local
  # checkpoints/ are the durable copies), but it would be the wrong default for an
  # environment holding anything irreplaceable.
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {} # applies the rule to all objects in the bucket
    noncurrent_version_expiration { noncurrent_days = 90 }
  }
}

output "artifacts_bucket_name" { value = aws_s3_bucket.artifacts.bucket }
output "artifacts_bucket_arn" { value = aws_s3_bucket.artifacts.arn }