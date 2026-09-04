variable "cluster_name" { type = string }
variable "environment" { type = string }
variable "region" { type = string }
variable "node_role_arn" { type = string }

variable "cluster_version" {
  type        = string
  default     = "1.33"
  description = "EKS control plane version. Must be in standard support — an out-of-support version incurs extended-support charges (~$0.60/hr) on top of the base $0.10/hr."
}

# The platform (kube-prometheus-stack, Argo CD, Argo Rollouts, MLflow and the
# inference replicas) requests roughly 9-10Gi of memory, so t3.small nodes
# (~1.5Gi allocatable, 11 pods each) cannot host it.
#
# This account is on the AWS Free Plan, which rejects any instance type that is not
# free-tier-eligible ("InvalidParameterCombination - The specified instance type is
# not eligible for Free Tier"). Of the permitted types, m7i-flex.large is the only
# one with 8Gi of memory, so 2 of them give ~14.4Gi allocatable. Check the current
# allow-list with:
#   aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true
variable "general_instance_types" {
  type    = list(string)
  default = ["m7i-flex.large"]
}
variable "general_desired_size" {
  type    = number
  default = 2
}
variable "general_max_size" {
  type    = number
  default = 4
}
variable "general_min_size" {
  type    = number
  default = 2
}

# Scaled to zero by default: the group carries a spot=true:NoSchedule taint that
# nothing in k8s/ tolerates, so running nodes here would cost money and host nothing.
# Raise desired_size when a batch workload that tolerates the taint is added.
variable "spot_instance_types" {
  type    = list(string)
  default = ["t3.small"]
}
variable "spot_desired_size" {
  type    = number
  default = 0
}

output "cluster_endpoint" { value = aws_eks_cluster.main.endpoint }
output "cluster_name" { value = aws_eks_cluster.main.name }
output "vpc_id" { value = aws_vpc.main.id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "cluster_sg_id" { value = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id }
