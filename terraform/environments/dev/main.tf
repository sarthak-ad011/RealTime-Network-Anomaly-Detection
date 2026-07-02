terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
    tls = { source = "hashicorp/tls", version = "~> 4.0" }
  }
  backend "s3" {
    bucket = "anomaly-mlops-tfstate"
    key    = "dev/terraform.tfstate"
    region = "ap-south-1"
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "network-anomaly-mlops", Environment = var.environment }
  }
}

module "s3" {
  source      = "../../modules/s3"
  environment = var.environment
}

module "ecr" {
  source = "../../modules/ecr"
}

module "iam" {
  source      = "../../modules/iam"
  environment = var.environment
  s3_bucket   = module.s3.artifacts_bucket_arn
}

module "eks" {
  source        = "../../modules/eks"
  environment   = var.environment
  cluster_name  = "anomaly-${var.environment}"
  region        = var.region
  node_role_arn = module.iam.eks_node_role_arn
}

module "rds" {
  source        = "../../modules/rds"
  environment   = var.environment
  db_password   = var.db_password
  vpc_id        = module.eks.vpc_id
  subnet_ids    = module.eks.private_subnet_ids
  allowed_sg_id = module.eks.cluster_sg_id
}

module "github_oidc" {
  source             = "../../modules/github_oidc"
  github_repo        = var.github_repo
  ecr_repository_arn = module.ecr.repository_arn
}

output "cluster_endpoint" { value = module.eks.cluster_endpoint }
output "ecr_repository_url" { value = module.ecr.repository_url }
output "github_actions_role_arn" { value = module.github_oidc.role_arn }
output "artifacts_bucket" { value = module.s3.artifacts_bucket_name }
output "mlflow_db_endpoint" {
  value     = module.rds.endpoint
  sensitive = true
}