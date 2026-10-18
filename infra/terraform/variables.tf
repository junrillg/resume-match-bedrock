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
    condition     = can(cidrnetmask(var.vpc_cidr)) && try(tonumber(split("/", var.vpc_cidr)[1]) >= 16 && tonumber(split("/", var.vpc_cidr)[1]) <= 20, false)
    error_message = "Supply an IPv4 VPC CIDR between /16 and /20."
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
