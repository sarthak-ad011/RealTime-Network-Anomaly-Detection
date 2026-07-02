variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "environment" {
  type    = string
  default = "dev"
}
variable "db_password" {
  type      = string
  sensitive = true
}
variable "github_repo" {
  type        = string
  description = "owner/repo, e.g. nikhil/network-anomaly-mlops"
}