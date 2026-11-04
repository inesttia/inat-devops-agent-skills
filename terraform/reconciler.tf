resource "aws_sqs_queue" "reconciler" {
  name                       = "payments-reconciler-${var.environment}"
  visibility_timeout_seconds = 360
  message_retention_seconds  = 345600
}

resource "aws_s3_bucket" "events_archive" {
  bucket = "payments-events-archive-${var.environment}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "events_archive" {
  bucket = aws_s3_bucket.events_archive.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket" "reports" {
  bucket = "payments-reconciler-reports-${var.environment}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.ledger.arn
    }
  }
}

resource "aws_iam_role" "reconciler" {
  name = "payments-reconciler-${var.environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "reconciler_basic" {
  role       = aws_iam_role.reconciler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "reconciler" {
  name              = "/aws/lambda/payments-reconciler-${var.environment}"
  retention_in_days = 30
}

resource "aws_lambda_function" "reconciler" {
  function_name = "payments-reconciler-${var.environment}"
  role          = aws_iam_role.reconciler.arn
  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "app.handler"
  memory_size   = 512
  timeout       = 60
  filename      = "${path.module}/reconciler.zip"

  environment {
    variables = {
      REPORTS_BUCKET = aws_s3_bucket.reports.bucket
      LEDGER_TABLE   = aws_dynamodb_table.ledger_index.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.reconciler]
}

resource "aws_lambda_event_source_mapping" "reconciler" {
  event_source_arn = aws_sqs_queue.reconciler.arn
  function_name    = aws_lambda_function.reconciler.arn
  batch_size       = 10
}

resource "aws_sns_topic" "alerts" {
  name = "payments-ledger-alerts-${var.environment}"
}
