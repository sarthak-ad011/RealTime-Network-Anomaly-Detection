resource "aws_ecr_repository" "anomaly" {
  name = "anomaly-mlops"
  # Same reason as the artifacts bucket: CI pushes an image per commit, so the
  # repository is never empty at destroy time and the delete fails without this.
  force_delete         = true
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

resource "aws_ecr_lifecycle_policy" "anomaly" {
  repository = aws_ecr_repository.anomaly.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 20 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

output "repository_url" { value = aws_ecr_repository.anomaly.repository_url }
output "repository_arn" { value = aws_ecr_repository.anomaly.arn }