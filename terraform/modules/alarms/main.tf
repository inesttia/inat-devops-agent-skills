variable "sns_topic_arn" {
  type = string
}

variable "alarms" {
  type = map(object({
    namespace   = string
    metric_name = string
    dimensions  = map(string)
    threshold   = number
  }))
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each = var.alarms

  alarm_name          = "payments-${each.key}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric_name
  dimensions          = each.value.dimensions
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [var.sns_topic_arn]
}

output "alarm_names" {
  value = [for a in aws_cloudwatch_metric_alarm.this : a.alarm_name]
}
