variable "environment" { type = string }
variable "s3_bucket" { type = string }

resource "aws_iam_role" "eks_node" {
  name = "eks-node-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "node_worker" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  role       = aws_iam_role.eks_node.name
}
resource "aws_iam_role_policy_attachment" "node_cni" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  role       = aws_iam_role.eks_node.name
}
resource "aws_iam_role_policy_attachment" "node_registry" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  role       = aws_iam_role.eks_node.name
}

resource "aws_iam_role_policy" "node_s3" {
  name = "node-s3-access"
  role = aws_iam_role.eks_node.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [var.s3_bucket, "${var.s3_bucket}/*"]
    }]
  })
}

output "eks_node_role_arn" { value = aws_iam_role.eks_node.arn }
# ---------------------------------------------------------------------------
# IRSA role for the mlops workloads (inference, MLflow, drift, training pods).
# Trusted only by one Kubernetes service account, and scoped to the artifacts
# bucket — a far tighter grant than sharing the node role via IMDS.
# ---------------------------------------------------------------------------
variable "oidc_provider_arn" { type = string }
variable "oidc_provider_url" { type = string }
variable "service_accounts" {
  type = list(string)
  default = [
    # Inference, MLflow, and every drift/training pod.
    "system:serviceaccount:mlops:anomaly-sa",
    # Airflow's own pods. The scheduler runs the DAG's BranchPythonOperator, which
    # reads the drift marker from S3 directly rather than in a task pod, and the
    # worker pods run clear_marker the same way. EKS nodes here restrict the IMDS
    # hop limit, so a pod cannot borrow the node role's credentials — without these
    # entries those tasks fail with NoCredentialsError.
    "system:serviceaccount:airflow:airflow-scheduler",
    "system:serviceaccount:airflow:airflow-worker",
    "system:serviceaccount:airflow:airflow-webserver",
  ]
  description = "Principals allowed to assume the mlops IRSA role."
}

resource "aws_iam_role" "irsa_mlops" {
  name = "anomaly-mlops-irsa-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = var.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${var.oidc_provider_url}:aud" = "sts.amazonaws.com"
          "${var.oidc_provider_url}:sub" = var.service_accounts
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "irsa_s3" {
  name = "irsa-s3-access"
  role = aws_iam_role.irsa_mlops.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${var.s3_bucket}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = var.s3_bucket
      }
    ]
  })
}

output "irsa_role_arn" { value = aws_iam_role.irsa_mlops.arn }
