variable "cluster_name" { type = string }
variable "environment" { type = string }
variable "region" { type = string }
variable "node_role_arn" { type = string }

variable "cluster_version" {
  type        = string
  default     = "1.33"
  description = "EKS control plane version. Must be in standard support — an out-of-support version incurs extended-support charges (~$0.60/hr) on top of the base $0.10/hr."
}

# The platform (kube-prometheus-stack, Argo CD, Argo Rollouts, Airflow, MLflow and
# the inference replicas) requests roughly 9-10Gi of memory. t3.small nodes offer
# ~1.5Gi allocatable and cap at 11 pods each, which cannot host it.
variable "general_instance_types" {
  type    = list(string)
  default = ["t3.large"]
}
variable "general_desired_size" {
  type    = number
  default = 3
}
variable "general_max_size" {
  type    = number
  default = 5
}
variable "general_min_size" {
  type    = number
  default = 2
}

variable "spot_instance_types" {
  type    = list(string)
  default = ["t3.medium"]
}

output "cluster_endpoint" { value = aws_eks_cluster.main.endpoint }
output "cluster_name" { value = aws_eks_cluster.main.name }
output "vpc_id" { value = aws_vpc.main.id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "cluster_sg_id" { value = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id }
