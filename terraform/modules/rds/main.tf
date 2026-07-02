variable "environment" { type = string }
variable "db_password" {
  type      = string
  sensitive = true
}
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "allowed_sg_id" { type = string }

resource "aws_db_subnet_group" "mlflow" {
  name       = "mlflow-${var.environment}"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "mlflow_db" {
  name   = "mlflow-db-${var.environment}"
  vpc_id = var.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.allowed_sg_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "mlflow" {
  identifier             = "mlflow-${var.environment}"
  engine                 = "postgres"
  engine_version         = "16.3"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  storage_encrypted      = true
  db_name                = "mlflow"
  username               = "mlflow"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.mlflow.name
  vpc_security_group_ids = [aws_security_group.mlflow_db.id]
  skip_final_snapshot    = true
  publicly_accessible    = false
}

output "endpoint" { value = aws_db_instance.mlflow.endpoint }