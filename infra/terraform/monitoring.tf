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
  log_group_names = [for role in ["app", "relay", "worker"] : aws_cloudwatch_log_group.service[role].name]
  query_string    = "fields @timestamp, event, request_id, job_id, stage, status, error_code\n| filter ispresent(job_id)\n| sort @timestamp asc\n| limit 200"
}
