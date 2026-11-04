output "api_dns_name" {
  value = aws_lb.api.dns_name
}

output "ledger_db_endpoint" {
  value = aws_db_instance.ledger.address
}

output "nat_gateway_id" {
  value = var.enable_nat_gateway ? aws_nat_gateway.reconciler[0].id : null
}

output "alarm_names" {
  value = module.alarms.alarm_names
}
