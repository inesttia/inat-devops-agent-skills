# NAT gateway for the reconciler, created only when the toggle is on.
resource "aws_eip" "reconciler_nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"
  tags   = { Name = "payments-reconciler-nat-${var.environment}" }
}

resource "aws_nat_gateway" "reconciler" {
  count         = var.enable_nat_gateway ? 1 : 0
  allocation_id = aws_eip.reconciler_nat[0].id
  subnet_id     = var.public_subnet_ids[0]
  tags          = { Name = "payments-reconciler-nat-${var.environment}" }
}

resource "aws_security_group" "alb" {
  name        = "payments-alb-${var.environment}"
  description = "Public API load balancer"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "worker" {
  name        = "payments-worker-${var.environment}"
  description = "Ledger workers"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "database" {
  name        = "payments-db-${var.environment}"
  description = "Ledger database"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }
}

resource "aws_security_group" "cache" {
  name        = "payments-cache-${var.environment}"
  description = "Session cache"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }
}
