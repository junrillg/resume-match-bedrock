variable "name" {
  type    = string
  default = "resume-match"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}[a-z0-9]$", var.name))
    error_message = "Use 4–21 lowercase letters, digits and interior hyphens."
  }
}
variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Supply the explicitly selected twelve-digit AWS account ID."
  }
}
variable "region" {
  type = string
  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.region)) && !startswith(var.region, "cn-")
    error_message = "Select a commercial AWS region; this root uses the aws partition."
  }
}
variable "availability_zones" {
  type = list(string)
  validation {
    condition     = length(var.availability_zones) == 3 && length(toset(var.availability_zones)) == 3 && alltrue([for az in var.availability_zones : can(regex("^${var.region}[a-z]$", az))])
    error_message = "Supply three distinct standard availability zones in the selected region."
  }
}
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && try(tonumber(split("/", var.vpc_cidr)[1]) >= 16 && tonumber(split("/", var.vpc_cidr)[1]) <= 18, false)
    error_message = "Supply an IPv4 VPC CIDR between /16 and /18 for three private /20s and public /24s."
  }
}
variable "public_zone_id" {
  type = string
  validation {
    condition     = can(regex("^Z[A-Z0-9]+$", var.public_zone_id))
    error_message = "Supply an existing, delegated public Route 53 hosted zone ID."
  }
}
variable "hostname" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]+\\.[a-z]{2,}$", var.hostname)) && !strcontains(var.hostname, "..")
    error_message = "Supply the public application DNS hostname inside that hosted zone."
  }
}
variable "postgres_engine_version" {
  type = string
  validation {
    condition     = can(regex("^17\\.[0-9]+$", var.postgres_engine_version))
    error_message = "Select an actually offered PostgreSQL 17 minor version in the deployment region."
  }
}
variable "database_instance_class" {
  type    = string
  default = "db.m7g.large"
  validation {
    condition     = can(regex("^db\\.[a-z0-9]+\\.[a-z0-9]+$", var.database_instance_class))
    error_message = "Supply a supported RDS instance class."
  }
}
variable "mq_instance_type" {
  type    = string
  default = "mq.m7g.large"
  validation {
    condition     = can(regex("^mq\\.m7g\\.(large|xlarge|[248]xlarge|1[26]xlarge)$", var.mq_instance_type))
    error_message = "RabbitMQ 4.3 requires a supported mq.m7g instance size."
  }
}
variable "bedrock_model_id" {
  type = string
  validation {
    condition     = length(trimspace(var.bedrock_model_id)) > 0
    error_message = "Supply the model or inference-profile ID supported in your chosen region."
  }
}
variable "bedrock_resource_arns" {
  type = set(string)
  validation {
    condition     = length(var.bedrock_resource_arns) > 0 && alltrue([for arn in var.bedrock_resource_arns : can(regex("^arn:aws:bedrock:[a-z0-9-]+:([0-9]{12})?:(foundation-model|inference-profile|application-inference-profile)/[^*?]+$", arn))])
    error_message = "Supply exact permitted model/profile ARNs, including backing models where required; wildcards are prohibited."
  }
}
variable "image_digests" {
  type    = object({ api = string, web = string })
  default = null
  validation {
    condition     = var.image_digests == null ? true : alltrue([for digest in values(var.image_digests) : can(regex("^sha256:[a-f0-9]{64}$", digest)) && !can(regex("^sha256:0{64}$", digest))])
    error_message = "After publishing both images, supply their actual immutable sha256 digests."
  }
}
variable "enable_services" {
  type    = bool
  default = false
  validation {
    condition     = !var.enable_services || var.image_digests != null
    error_message = "Publish images and successfully bootstrap/migrate before enabling normal services."
  }
}
variable "bootstrap_completed" {
  type    = bool
  default = false
  validation {
    condition     = !var.enable_services || var.bootstrap_completed
    error_message = "Confirm the one-off bootstrap task exited successfully before enabling services."
  }
}
variable "reviewer_username" {
  type    = string
  default = "reviewer"
  validation {
    condition     = can(regex("^[a-zA-Z0-9_.@+-]{1,150}$", var.reviewer_username))
    error_message = "Choose a valid initial reviewer username."
  }
}
variable "deletion_protection" {
  type    = bool
  default = true
}
variable "final_snapshot_identifier" {
  type    = string
  default = null
  validation {
    condition     = var.final_snapshot_identifier == null ? true : can(regex("^[a-zA-Z][a-zA-Z0-9-]{0,253}[a-zA-Z0-9]$", var.final_snapshot_identifier)) && !strcontains(var.final_snapshot_identifier, "--")
    error_message = "Supply an unused RDS snapshot identifier with no trailing or repeated hyphens."
  }
}
variable "alarm_action_arns" {
  type    = list(string)
  default = []
  validation {
    condition     = alltrue([for arn in var.alarm_action_arns : startswith(arn, "arn:aws:sns:")])
    error_message = "Optional alarm destinations must be existing authorized SNS topic ARNs."
  }
}

variable "document_retention_days" {
  description = "Project policy for originals and derived application data; lifecycle is a delayed backstop, not the access-control clock."
  type        = number
  default     = 90
  validation {
    condition     = var.document_retention_days >= 1 && var.document_retention_days <= 3650 && floor(var.document_retention_days) == var.document_retention_days
    error_message = "Choose an integer retention of 1–3650 days, matching application policy."
  }
}

variable "service_capacity" {
  description = "Small initial min/max replicas on the same event path; planning limits, not measured capacity."
  type        = map(object({ min = number, max = number }))
  default = {
    app         = { min = 2, max = 12 }
    worker      = { min = 2, max = 12 }
    relay       = { min = 1, max = 1 }
    gateway     = { min = 3, max = 12 }
    event-relay = { min = 1, max = 1 }
  }
  validation {
    condition     = toset(keys(var.service_capacity)) == toset(["app", "worker", "relay", "gateway", "event-relay"]) && alltrue([for item in values(var.service_capacity) : item.min >= 1 && item.max >= item.min && item.max <= 5000 && floor(item.min) == item.min && floor(item.max) == item.max])
    error_message = "Provide all five service roles with integer min/max replicas, 1 <= min <= max <= 5000."
  }
}
variable "gateway_connections" {
  type    = number
  default = 2000
  validation {
    condition     = var.gateway_connections >= 1 && var.gateway_connections <= 10000 && floor(var.gateway_connections) == var.gateway_connections
    error_message = "Set a finite tested per-process stream ceiling between 1 and 10000."
  }
}
variable "gateway_utilization" {
  type    = number
  default = 0.7
  validation {
    condition     = var.gateway_utilization >= 0.1 && var.gateway_utilization <= 0.8
    error_message = "Reserve connection headroom with target utilization between 0.1 and 0.8."
  }
}
variable "gateway_db_workers" {
  type    = number
  default = 4
  validation {
    condition     = var.gateway_db_workers >= 1 && var.gateway_db_workers <= 16 && floor(var.gateway_db_workers) == var.gateway_db_workers
    error_message = "Bound each gateway database executor/pool to 1–16 workers."
  }
}
variable "fanout_shards" {
  description = "Stable modulo map size. Changing requires coordinated publication pause and gateway drain."
  type        = number
  default     = 2
  validation {
    condition     = var.fanout_shards >= 2 && var.fanout_shards <= 16 && floor(var.fanout_shards) == var.fanout_shards
    error_message = "Select 2–16 independent fan-out groups; never change the map during a rolling deployment."
  }
}
variable "fanout_node_type" {
  type    = string
  default = "cache.m7g.large"
  validation {
    condition     = can(regex("^cache\\.[a-z0-9]+\\.[a-z0-9]+$", var.fanout_node_type))
    error_message = "Choose a Valkey-supported node type available in the selected region."
  }
}
variable "capacity_limits" {
  description = "Operator-reviewed configured ceilings; future account quota checks remain required before apply."
  type        = object({ alb_targets = number, target_group_targets = number, fargate_vcpu = number, proxy_clients = number, database_backends = number })
  default     = { alb_targets = 1000, target_group_targets = 1000, fargate_vcpu = 64, proxy_clients = 512, database_backends = 256 }
  validation {
    condition     = alltrue([for limit in values(var.capacity_limits) : limit > 0 && floor(limit) == limit])
    error_message = "All configured resource-budget ceilings must be positive integers; these do not verify account quotas."
  }
}
variable "app_db_connection_limit" {
  type    = number
  default = 128
  validation {
    condition     = var.app_db_connection_limit >= 8 && floor(var.app_db_connection_limit) == var.app_db_connection_limit
    error_message = "Set an integer application backend connection limit of at least 8."
  }
}
variable "stream_db_connection_limit" {
  type    = number
  default = 64
  validation {
    condition     = var.stream_db_connection_limit >= 4 && floor(var.stream_db_connection_limit) == var.stream_db_connection_limit
    error_message = "Set an integer stream backend connection limit of at least 4."
  }
}
variable "admission_rate_per_second" {
  description = "Small-profile logical-admission bound; raise only with worker/provider supply. Peak100/s is a separate planning input."
  type        = number
  default     = 2
  validation {
    condition     = var.admission_rate_per_second >= 1 && var.admission_rate_per_second <= 100 && floor(var.admission_rate_per_second) == var.admission_rate_per_second
    error_message = "Choose an integer admission rate of 1–100/s within the configured supply envelope."
  }
}
variable "queue_age_limit_seconds" {
  description = "Explicit proposed queue-wait budget, not a confirmed completion SLO."
  type        = number
  default     = 60
  validation {
    condition     = var.queue_age_limit_seconds >= 1 && var.queue_age_limit_seconds <= 300 && floor(var.queue_age_limit_seconds) == var.queue_age_limit_seconds
    error_message = "Choose a finite 1–300 second queue-age gate below the job deadline."
  }
}

variable "admission_max_active" {
  description = "Finite accepted-work bound for this deployment, independently of connected users."
  type        = number
  default     = 32
  validation {
    condition     = var.admission_max_active >= 1 && var.admission_max_active <= 100000 && floor(var.admission_max_active) == var.admission_max_active
    error_message = "Set a finite active-work bound of 1–100000 jobs within worker/provider supply."
  }
}
variable "owner_active_job_limit" {
  type    = number
  default = 2
  validation {
    condition     = var.owner_active_job_limit >= 1 && var.owner_active_job_limit <= var.admission_max_active && floor(var.owner_active_job_limit) == var.owner_active_job_limit
    error_message = "Owner concurrency must be an integer between 1 and the deployment active-work bound."
  }
}
variable "admission_health_max_age_seconds" {
  type    = number
  default = 15
  validation {
    condition     = var.admission_health_max_age_seconds >= 3 && var.admission_health_max_age_seconds <= 60 && floor(var.admission_health_max_age_seconds) == var.admission_health_max_age_seconds
    error_message = "Admission requires a finite 3–60 second relay-health freshness budget."
  }
}
