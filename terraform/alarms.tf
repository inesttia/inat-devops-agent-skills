# Alarms come from a local module; the skill has to expand it to count them.
module "alarms" {
  source = "./modules/alarms"

  sns_topic_arn = aws_sns_topic.alerts.arn
  alarms = {
    reconciler-queue-depth = {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesVisible"
      dimensions  = { QueueName = aws_sqs_queue.reconciler.name }
      threshold   = 1000
    }
    ledger-db-cpu = {
      namespace   = "AWS/RDS"
      metric_name = "CPUUtilization"
      dimensions  = { DBInstanceIdentifier = aws_db_instance.ledger.identifier }
      threshold   = 80
    }
    api-5xx = {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_ELB_5XX_Count"
      dimensions  = { LoadBalancer = aws_lb.api.arn_suffix }
      threshold   = 50
    }
  }
}
