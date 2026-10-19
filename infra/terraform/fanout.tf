locals {
  # List order is shared deployment state, not an unordered set of endpoints.
  fanout_map = { for index in range(var.fanout_shards) : format("%02d", index) => index }
  fanout_acl = {
    gateway = "on ~owner-cap:* &owner:* -@all +ping +subscribe +unsubscribe +publish +eval +zremrangebyscore +zscore +zcard +zadd +expire +zrem"
    relay   = "on &owner:* -@all +ping +publish"
  }
  fanout_hosts = join(",", [for key in sort(keys(local.fanout_map)) : aws_elasticache_replication_group.fanout[key].primary_endpoint_address])
}
resource "aws_elasticache_subnet_group" "fanout" {
  name       = "${var.name}-fanout"
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]
}
resource "aws_elasticache_parameter_group" "fanout" {
  name   = "${var.name}-fanout"
  family = "valkey8"
  parameter {
    name  = "maxmemory-policy"
    value = "noeviction"
  }
}
resource "random_password" "fanout" {
  for_each = local.fanout_acl
  length   = 48
  special  = false
}
resource "aws_secretsmanager_secret" "fanout" {
  for_each                = local.fanout_acl
  name                    = "${var.name}/fanout-${each.key}"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 30
}
resource "aws_secretsmanager_secret_version" "fanout" {
  for_each      = local.fanout_acl
  secret_id     = aws_secretsmanager_secret.fanout[each.key].id
  secret_string = random_password.fanout[each.key].result
}
resource "aws_elasticache_user" "fanout" {
  for_each      = local.fanout_acl
  user_id       = "${var.name}-${each.key}"
  user_name     = each.key
  engine        = "valkey"
  access_string = each.value
  passwords     = [random_password.fanout[each.key].result]
}
resource "aws_elasticache_user_group" "fanout" {
  user_group_id = "${var.name}-fanout"
  engine        = "valkey"
  user_ids      = [for user in aws_elasticache_user.fanout : user.user_id]
}
resource "aws_elasticache_replication_group" "fanout" {
  for_each                    = local.fanout_map
  replication_group_id        = "${var.name}-fanout-${each.key}"
  description                 = "Owner-channel wake and lease shard ${each.key}; PostgreSQL owns durable state"
  engine                      = "valkey"
  engine_version              = "8.1"
  cluster_mode                = "disabled"
  node_type                   = var.fanout_node_type
  num_cache_clusters          = 2
  preferred_cache_cluster_azs = [var.availability_zones[each.value % 3], var.availability_zones[(each.value + 1) % 3]]
  automatic_failover_enabled  = true
  multi_az_enabled            = true
  at_rest_encryption_enabled  = true
  kms_key_id                  = aws_kms_key.main.arn
  transit_encryption_enabled  = true
  transit_encryption_mode     = "required"
  parameter_group_name        = aws_elasticache_parameter_group.fanout.name
  user_group_ids              = [aws_elasticache_user_group.fanout.id]
  subnet_group_name           = aws_elasticache_subnet_group.fanout.name
  security_group_ids          = [aws_security_group.fanout.id]
  port                        = 6379
  snapshot_retention_limit    = 0
  auto_minor_version_upgrade  = true
  maintenance_window          = "sun:06:00-sun:07:00"
}
resource "aws_security_group" "fanout" {
  name_prefix = "${var.name}-fanout-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_vpc_security_group_ingress_rule" "fanout" {
  for_each                     = toset(["gateway", "event-relay"])
  security_group_id            = aws_security_group.fanout.id
  referenced_security_group_id = aws_security_group.task[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}
resource "aws_vpc_security_group_egress_rule" "fanout" {
  for_each                     = toset(["gateway", "event-relay"])
  security_group_id            = aws_security_group.task[each.key].id
  referenced_security_group_id = aws_security_group.fanout.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}
resource "aws_vpc_security_group_ingress_rule" "fanout_replication" {
  security_group_id            = aws_security_group.fanout.id
  referenced_security_group_id = aws_security_group.fanout.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}
resource "aws_vpc_security_group_egress_rule" "fanout_replication" {
  security_group_id            = aws_security_group.fanout.id
  referenced_security_group_id = aws_security_group.fanout.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}
