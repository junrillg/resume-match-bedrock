resource "aws_cloudwatch_log_metric_filter" "failures" {
  for_each       = toset(["app", "relay", "worker"])
  name           = "${var.name}-${each.key}-job-failures"
  log_group_name = aws_cloudwatch_log_group.service[each.key].name
  pattern        = "{ ($.event = \"job.failed\") || ($.event = \"job.publish_failed\") }"
  metric_transformation {
    name          = "Failures-${each.key}"
    namespace     = var.name
    value         = "1"
    default_value = "0"
  }
}
resource "aws_cloudwatch_metric_alarm" "failures" {
  for_each            = toset(["app", "relay", "worker"])
  alarm_name          = "${var.name}-${each.key}-failures"
  alarm_description   = "Inspect correlated lifecycle logs; never retry admission with a new key to clear an alarm."
  namespace           = var.name
  metric_name         = "Failures-${each.key}"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_metric_alarm" "unhealthy" {
  alarm_name          = "${var.name}-unhealthy-targets"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.app.arn_suffix }
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${var.name}-database-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 21474836480
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "missing"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_metric_alarm" "broker_backlog" {
  alarm_name          = "${var.name}-broker-backlog"
  namespace           = "AWS/AmazonMQ"
  metric_name         = "MessageReadyCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 100
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"
  dimensions          = { Broker = aws_mq_broker.main.broker_name }
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_query_definition" "journey" {
  name            = "${var.name}/request-journey"
  log_group_names = [for role in ["app", "relay", "worker", "gateway", "event-relay"] : aws_cloudwatch_log_group.service[role].name]
  query_string    = "fields @timestamp, event, request_id, job_id, stage, status, error_code\n| filter ispresent(job_id)\n| sort @timestamp asc\n| limit 200"
}

resource "aws_cloudwatch_log_metric_filter" "delivery_age" {
  name           = "${var.name}-delivery-age"
  log_group_name = aws_cloudwatch_log_group.service["event-relay"].name
  pattern        = "{ ($.event = \"delivery.snapshot\") && ($.oldest_pending_ms = *) }"
  metric_transformation {
    name      = "OldestDeliveryMs"
    namespace = "${var.name}/Delivery"
    value     = "$.oldest_pending_ms"
    unit      = "Milliseconds"
  }
}
resource "aws_cloudwatch_metric_alarm" "delivery_age" {
  actions_enabled     = var.enable_services
  alarm_name          = "${var.name}-delivery-age"
  namespace           = "${var.name}/Delivery"
  metric_name         = "OldestDeliveryMs"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 30000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_metric_alarm" "stream_health" {
  actions_enabled     = var.enable_services
  alarm_name          = "${var.name}-unhealthy-stream-targets"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"
  dimensions          = { LoadBalancer = aws_lb.main.arn_suffix, TargetGroup = aws_lb_target_group.gateway.arn_suffix }
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_metric_alarm" "stream_metrics_missing" {
  actions_enabled     = var.enable_services
  alarm_name          = "${var.name}-stream-metrics-missing"
  namespace           = "ResumeMatch/Delivery"
  metric_name         = "ConnectedStreams"
  statistic           = "SampleCount"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  dimensions          = { ServiceName = "${var.name}-gateway" }
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_log_metric_filter" "stream_db_pending" {
  name           = "${var.name}-stream-db-pending"
  log_group_name = aws_cloudwatch_log_group.service["gateway"].name
  pattern        = "{ ($.event = \"stream.snapshot\") && ($.db_pending = *) }"
  metric_transformation {
    name      = "StreamDbPending"
    namespace = "${var.name}/Delivery"
    value     = "$.db_pending"
    unit      = "Count"
  }
}
resource "aws_cloudwatch_metric_alarm" "stream_db_pending" {
  actions_enabled     = var.enable_services
  alarm_name          = "${var.name}-stream-db-saturation"
  namespace           = "${var.name}/Delivery"
  metric_name         = "StreamDbPending"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 64
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"
  alarm_actions       = var.alarm_action_arns
}
locals {
  fanout_node_metrics = { for pair in setproduct(keys(local.fanout_map), range(2), ["memory", "evictions", "lag"]) : "${pair[0]}-${pair[1]}-${pair[2]}" => { shard = pair[0], node = pair[1], kind = pair[2] } }
  fanout_metric_specs = {
    memory    = { metric = "DatabaseMemoryUsagePercentage", threshold = 80, statistic = "Maximum" }
    evictions = { metric = "Evictions", threshold = 0, statistic = "Sum" }
    lag       = { metric = "ReplicationLag", threshold = 1, statistic = "Maximum" }
  }
}
resource "aws_cloudwatch_metric_alarm" "fanout" {
  actions_enabled     = var.enable_services
  for_each            = local.fanout_node_metrics
  alarm_name          = "${var.name}-fanout-${each.key}"
  namespace           = "AWS/ElastiCache"
  metric_name         = local.fanout_metric_specs[each.value.kind].metric
  statistic           = local.fanout_metric_specs[each.value.kind].statistic
  period              = 60
  evaluation_periods  = 2
  threshold           = local.fanout_metric_specs[each.value.kind].threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "missing"
  dimensions          = { CacheClusterId = sort(tolist(aws_elasticache_replication_group.fanout[each.value.shard].member_clusters))[each.value.node], CacheNodeId = "0001" }
  alarm_actions       = var.alarm_action_arns
}
resource "aws_cloudwatch_metric_alarm" "proxy" {
  actions_enabled = var.enable_services
  for_each = {
    borrow = { metric = "DatabaseConnectionsBorrowLatency", threshold = 1000000 }
    pinned = { metric = "DatabaseConnectionsCurrentlySessionPinned", threshold = 0 }
  }
  alarm_name          = "${var.name}-proxy-${each.key}"
  namespace           = "AWS/RDS"
  metric_name         = each.value.metric
  statistic           = each.key == "borrow" ? "Average" : "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "missing"
  dimensions          = { ProxyName = aws_db_proxy.main.name }
  alarm_actions       = var.alarm_action_arns
}

resource "aws_cloudwatch_log_metric_filter" "admission_queue_age" {
  name           = "${var.name}-admission-queue-age"
  log_group_name = aws_cloudwatch_log_group.service["relay"].name
  pattern        = "{ ($.event = \"admission.snapshot\") && ($.oldest_queue_age_ms = *) }"
  metric_transformation {
    name      = "OldestQueueMs"
    namespace = "${var.name}/Delivery"
    value     = "$.oldest_queue_age_ms"
    unit      = "Milliseconds"
  }
}
resource "aws_cloudwatch_metric_alarm" "admission_queue_age" {
  alarm_name          = "${var.name}-admission-queue-age"
  actions_enabled     = var.enable_services
  namespace           = "${var.name}/Delivery"
  metric_name         = "OldestQueueMs"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = var.queue_age_limit_seconds * 1000
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = var.alarm_action_arns
}
