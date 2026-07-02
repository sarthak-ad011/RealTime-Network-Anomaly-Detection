variable "cluster_name" { type = string }
variable "environment" { type = string }
variable "region" { type = string }
variable "node_role_arn" { type = string }

output "cluster_endpoint" { value = aws_eks_cluster.main.endpoint }
output "cluster_name" { value = aws_eks_cluster.main.name }
output "vpc_id" { value = aws_vpc.main.id }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "cluster_sg_id" { value = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id }