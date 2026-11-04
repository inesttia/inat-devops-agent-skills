resource "aws_kms_key" "ledger" {
  description         = "Payments ledger data key"
  enable_key_rotation = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_db_subnet_group" "ledger" {
  name       = "payments-ledger-${var.environment}"
  subnet_ids = var.db_subnet_ids
}

resource "aws_db_instance" "ledger" {
  identifier     = "payments-ledger-${var.environment}"
  engine         = "postgres"
  engine_version = "16.9"
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true
  kms_key_id        = aws_kms_key.ledger.arn

  # multi_az is deliberately not set: the provider default (single-AZ) applies.

  db_subnet_group_name   = aws_db_subnet_group.ledger.name
  vpc_security_group_ids = [aws_security_group.database.id]

  manage_master_user_password = true
  username                    = "ledger_admin"

  backup_retention_period = 7
  deletion_protection     = true
  skip_final_snapshot     = false
  final_snapshot_identifier = "payments-ledger-${var.environment}-final"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_dynamodb_table" "ledger_index" {
  name         = "payments-ledger-index-${var.environment}"
  billing_mode = "PROVISIONED"
  hash_key     = "pk"
  range_key    = "sk"

  read_capacity  = 50
  write_capacity = 25

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}
