resource "aws_elasticache_subnet_group" "session" {
  name       = "payments-session-${var.environment}"
  subnet_ids = var.db_subnet_ids
}

resource "aws_elasticache_replication_group" "session" {
  replication_group_id = "payments-session-${var.environment}"
  description          = "Session cache"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.cache_node_type

  num_cache_clusters         = 1 + var.cache_replicas
  automatic_failover_enabled = var.cache_replicas > 0
  multi_az_enabled           = var.cache_replicas > 0

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  subnet_group_name  = aws_elasticache_subnet_group.session.name
  security_group_ids = [aws_security_group.cache.id]
}
