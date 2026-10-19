locals {
  role_vcpu               = { app = 1, worker = 1, relay = 0.5, gateway = 0.5, event-relay = 0.5 }
  rollout_tasks           = 2 * sum([for role, capacity in var.service_capacity : capacity.max])
  rollout_vcpu            = 2 * sum([for role, capacity in var.service_capacity : capacity.max * local.role_vcpu[role]])
  gateway_rollout_targets = 2 * var.service_capacity["gateway"].max
  alb_rollout_targets     = 2 * (var.service_capacity["gateway"].max + var.service_capacity["app"].max)
  proxy_rollout_clients   = 2 * (var.service_capacity["gateway"].max * var.gateway_db_workers + var.service_capacity["app"].max * 4 + var.service_capacity["worker"].max + var.service_capacity["relay"].max * 2 + var.service_capacity["event-relay"].max) + 4
}
resource "terraform_data" "capacity" {
  input = { task_ips = local.rollout_tasks, vcpu = local.rollout_vcpu, proxy_clients = local.proxy_rollout_clients }
  lifecycle {
    precondition {
      condition     = local.gateway_rollout_targets <= var.capacity_limits.target_group_targets && 2 * var.service_capacity["app"].max <= var.capacity_limits.target_group_targets && local.alb_rollout_targets <= var.capacity_limits.alb_targets
      error_message = "Configured max replicas plus 200% rollout exceed target budgets. Verify actual account quotas before apply."
    }
    precondition {
      condition     = local.rollout_vcpu <= var.capacity_limits.fargate_vcpu
      error_message = "Configured rollout exceeds the selected Fargate vCPU budget."
    }
    precondition {
      condition     = ceil(local.rollout_tasks / 2) + 128 <= 4091
      error_message = "Configured rollout and one-AZ-loss placement exceed private /20 addresses after reserved/service headroom."
    }
    precondition {
      condition     = local.proxy_rollout_clients <= var.capacity_limits.proxy_clients && var.app_db_connection_limit + var.stream_db_connection_limit + 32 <= var.capacity_limits.database_backends
      error_message = "Configured client or backend connection limits exceed the database budget and operational reserve."
    }
  }
}
resource "aws_appautoscaling_target" "service" {
  for_each           = local.services
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.main[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
  # Updating bounds to zero also stops an already scaled service when disabled.
  min_capacity = var.enable_services ? var.service_capacity[each.key].min : 0
  max_capacity = var.enable_services ? var.service_capacity[each.key].max : 0
  suspended_state {
    dynamic_scaling_in_suspended  = !var.enable_services
    dynamic_scaling_out_suspended = !var.enable_services
    scheduled_scaling_suspended   = !var.enable_services
  }
}
resource "aws_appautoscaling_policy" "connections" {
  for_each           = contains(local.services, "gateway") ? toset(["gateway"]) : toset([])
  name               = "${var.name}-stream-connections"
  resource_id        = aws_appautoscaling_target.service[each.key].resource_id
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
  policy_type        = "TargetTrackingScaling"
  target_tracking_scaling_policy_configuration {
    target_value       = var.gateway_connections * var.gateway_utilization
    scale_out_cooldown = 30
    scale_in_cooldown  = 900
    customized_metric_specification {
      namespace   = "ResumeMatch/Delivery"
      metric_name = "ConnectedStreams"
      statistic   = "Average"
      unit        = "Count"
      dimensions {
        name  = "ServiceName"
        value = "${var.name}-gateway"
      }
    }
  }
}
resource "aws_appautoscaling_policy" "utilization" {
  for_each           = { for pair in setproduct(setintersection(local.services, toset(["app", "worker", "gateway"])), toset(["cpu", "memory"])) : "${pair[0]}-${pair[1]}" => { role = pair[0], metric = pair[1] } }
  name               = "${var.name}-${each.key}"
  resource_id        = aws_appautoscaling_target.service[each.value.role].resource_id
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
  policy_type        = "TargetTrackingScaling"
  target_tracking_scaling_policy_configuration {
    target_value       = each.value.metric == "cpu" ? 65 : 70
    scale_out_cooldown = 30
    scale_in_cooldown  = 900
    predefined_metric_specification {
      predefined_metric_type = each.value.metric == "cpu" ? "ECSServiceAverageCPUUtilization" : "ECSServiceAverageMemoryUtilization"
    }
  }
}
