mock_provider "aws" {
  override_during = plan
  mock_resource "aws_elasticache_replication_group" {
    defaults = { primary_endpoint_address = "fanout.example.invalid", member_clusters = ["fanout-001", "fanout-002"] }
  }
  mock_resource "aws_db_proxy" {
    defaults = { endpoint = "proxy.example.invalid" }
  }
  mock_resource "aws_vpc" {
    defaults = { id = "vpc-0123456789abcdef0" }
  }
  mock_resource "aws_subnet" {
    defaults = { id = "subnet-0123456789abcdef0" }
  }
  mock_resource "aws_route_table" {
    defaults = { route = [] }
  }
  mock_resource "aws_security_group" {
    defaults = { id = "sg-0123456789abcdef0" }
  }
  mock_resource "aws_vpc_endpoint" {
    defaults = { id = "vpce-0123456789abcdef0", prefix_list_id = "pl-01234567" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-1:111122223333:key/12345678-1234-1234-1234-123456789012", key_id = "12345678-1234-1234-1234-123456789012" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::111122223333:role/mock-role" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { id = "resume-match-originals-111122223333-us-east-1", arn = "arn:aws:s3:::resume-match-originals-111122223333-us-east-1" }
  }
  mock_resource "aws_guardduty_malware_protection_plan" {
    defaults = { arn = "arn:aws:guardduty:us-east-1:111122223333:malware-protection-plan/1234567890abcdef", status = "ACTIVE" }
  }
  mock_resource "aws_db_instance" {
    defaults = { address = "db.example.invalid", master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:master-AbCdEf", secret_status = "active", kms_key_id = "12345678-1234-1234-1234-123456789012" }] }
  }
  mock_resource "aws_mq_broker" {
    defaults = { instances = [{ console_url = "https://broker.example.invalid", endpoints = ["amqps://broker.example.invalid:5671"], ip_address = "10.42.10.20" }] }
  }
  mock_resource "aws_acm_certificate" {
    defaults = { arn = "arn:aws:acm:us-east-1:111122223333:certificate/12345678-1234-1234-1234-123456789012", domain_validation_options = [{ domain_name = "resume.example.com", resource_record_name = "_validation.resume.example.com", resource_record_type = "CNAME", resource_record_value = "_validation.acm-validations.aws" }] }
  }
  mock_resource "aws_acm_certificate_validation" {
    defaults = { certificate_arn = "arn:aws:acm:us-east-1:111122223333:certificate/12345678-1234-1234-1234-123456789012" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/resume-match/1234567890123456" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:111122223333:targetgroup/resume-match/1234567890123456" }
  }
  mock_resource "aws_ecr_repository" {
    defaults = { arn = "arn:aws:ecr:us-east-1:111122223333:repository/resume-match/api", repository_url = "111122223333.dkr.ecr.us-east-1.amazonaws.com/resume-match/api" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:111122223333:log-group:/ecs/resume-match/mock" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:app-AbCdEf" }
  }
  mock_resource "aws_ecs_task_definition" {
    defaults = { arn = "arn:aws:ecs:us-east-1:111122223333:task-definition/resume-match:1" }
  }
}
mock_provider "random" {
  override_during = plan
  mock_resource "random_password" {
    defaults = { result = "synthetic-test-password-not-a-real-credential-123456789" }
  }
}
override_resource {
  target          = aws_subnet.private["us-east-1a"]
  override_during = plan
  values          = { id = "subnet-00000000000000001" }
}
override_resource {
  target          = aws_subnet.private["us-east-1b"]
  override_during = plan
  values          = { id = "subnet-00000000000000002" }
}
override_resource {
  target          = aws_subnet.private["us-east-1c"]
  override_during = plan
  values          = { id = "subnet-00000000000000003" }
}
override_resource {
  target          = aws_iam_role.task["app"]
  override_during = plan
  values          = { id = "resume-match-app-task", arn = "arn:aws:iam::111122223333:role/resume-match-app-task" }
}
override_resource {
  target          = aws_iam_role.task["relay"]
  override_during = plan
  values          = { id = "resume-match-relay-task", arn = "arn:aws:iam::111122223333:role/resume-match-relay-task" }
}
override_resource {
  target          = aws_iam_role.task["worker"]
  override_during = plan
  values          = { id = "resume-match-worker-task", arn = "arn:aws:iam::111122223333:role/resume-match-worker-task" }
}
override_resource {
  target          = aws_iam_role.task["bootstrap"]
  override_during = plan
  values          = { id = "resume-match-bootstrap-task", arn = "arn:aws:iam::111122223333:role/resume-match-bootstrap-task" }
}
override_resource {
  target          = aws_iam_role.document_scan
  override_during = plan
  values          = { id = "resume-match-document-scan", arn = "arn:aws:iam::111122223333:role/resume-match-document-scan" }
}
variables {
  account_id              = "111122223333"
  region                  = "us-east-1"
  availability_zones      = ["us-east-1a", "us-east-1b", "us-east-1c"]
  public_zone_id          = "Z0123456789EXAMPLE"
  hostname                = "resume.example.com"
  postgres_engine_version = "17.11"
  bedrock_model_id        = "example.model-v1:0"
  bedrock_resource_arns   = ["arn:aws:bedrock:us-east-1::foundation-model/example.model-v1:0"]
}
run "foundation_without_images" {
  command = plan
  assert {
    condition     = length(aws_ecs_task_definition.service) == 0 && length(aws_ecs_service.main) == 0
    error_message = "Foundation must not start tasks or reference placeholder image digests."
  }
  assert {
    condition     = length(aws_subnet.private) == 3 && length(aws_route_table.private.route) == 0 && aws_vpc_endpoint.s3_layers.vpc_endpoint_type == "Gateway" && length(aws_vpc_endpoint.service) == 4
    error_message = "Private tasks need three AZs, no default internet route, four startup endpoints and ECR layer access."
  }
  assert {
    condition     = aws_db_instance.main.multi_az && !aws_db_instance.main.publicly_accessible && aws_db_instance.main.manage_master_user_password && aws_db_instance.main.storage_encrypted && aws_db_instance.main.backup_retention_period >= 7 && !aws_db_instance.main.skip_final_snapshot
    error_message = "Database must be private, encrypted, managed-master and recoverable."
  }
  assert {
    condition     = aws_mq_broker.main.deployment_mode == "CLUSTER_MULTI_AZ" && aws_mq_broker.main.engine_version == "4.3" && !aws_mq_broker.main.publicly_accessible && length(aws_mq_broker.main.subnet_ids) == 3
    error_message = "RabbitMQ quorum topology requires the selected private three-AZ cluster."
  }
  assert {
    condition     = aws_lb_listener.https.protocol == "HTTPS" && aws_lb_listener.https.port == 443 && aws_lb_target_group.app.port == 8080 && aws_lb_target_group.app.health_check[0].path == "/api/health/"
    error_message = "Ingress must terminate HTTPS and expose only nginx plus DB-aware readiness."
  }
  assert {
    condition     = alltrue([for group in aws_cloudwatch_log_group.service : group.retention_in_days == 30 && group.kms_key_id == aws_kms_key.main.arn && group.skip_destroy]) && aws_kms_key.main.enable_key_rotation
    error_message = "Application logs require bounded retention, KMS encryption and retention on destroy."
  }
  assert {
    condition     = !strcontains(aws_iam_role_policy.execution["app"].policy, aws_db_instance.main.master_user_secret[0].secret_arn) && strcontains(aws_iam_role_policy.execution["bootstrap"].policy, aws_db_instance.main.master_user_secret[0].secret_arn)
    error_message = "Only bootstrap execution may read the managed master secret."
  }
  assert {
    condition     = toset(jsondecode(aws_iam_role_policy.bedrock.policy).Statement[0].Resource) == var.bedrock_resource_arns && jsondecode(aws_iam_role_policy.bedrock.policy).Statement[0].Condition.StringEquals["aws:SourceVpce"] == aws_vpc_endpoint.bedrock.id
    error_message = "Worker model invocation must name exact resources and the private endpoint."
  }
}
run "staged_tasks_before_bootstrap" {
  command = plan
  variables {
    image_digests = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  assert {
    condition     = length(aws_ecs_task_definition.service) == 6 && alltrue([for service in aws_ecs_service.main : service.desired_count == 0 && !service.network_configuration[0].assign_public_ip])
    error_message = "Image publication defines tasks but must leave normal services stopped before bootstrap."
  }
  assert {
    condition     = length(jsondecode(aws_ecs_task_definition.service["app"].container_definitions)) == 2 && jsondecode(aws_ecs_task_definition.service["app"].container_definitions)[0].command[3] == "127.0.0.1:8000" && jsondecode(aws_ecs_task_definition.service["app"].container_definitions)[1].portMappings[0].containerPort == 8080
    error_message = "The app task must colocate nginx and a localhost-only Django server."
  }
  assert {
    condition     = local.environment.POSTGRES_SSLMODE == "verify-full" && local.environment.RABBITMQ_TLS == "true" && local.environment.MATCH_PROVIDER == "bedrock" && local.environment.RABBITMQ_HOST == "broker.example.invalid" && !contains(keys(local.environment), "BEDROCK_LOCAL_ENDPOINT")
    error_message = "Cloud tasks need verified RDS/MQ TLS and the real Bedrock SDK route."
  }
  assert {
    condition     = join(" ", jsondecode(aws_ecs_task_definition.service["bootstrap"].container_definitions)[0].command) == "python manage.py bootstrap_cloud_db" && !contains([for secret in jsondecode(aws_ecs_task_definition.service["worker"].container_definitions)[0].secrets : secret.name], "RDS_MASTER_PASSWORD")
    error_message = "Master credentials belong only to the one-off bootstrap task."
  }
}
run "reject_early_enable" {
  command = plan
  variables {
    enable_services = true
  }
  expect_failures = [var.enable_services]
}
run "reject_missing_bootstrap_confirmation" {
  command = plan
  variables {
    image_digests   = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    enable_services = true
  }
  expect_failures = [var.bootstrap_completed]
}
run "enabled_after_bootstrap" {
  command = plan
  variables {
    image_digests       = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    enable_services     = true
    bootstrap_completed = true
  }
  assert {
    condition     = aws_ecs_service.main["app"].desired_count == 2 && aws_ecs_service.main["worker"].desired_count == 2 && aws_ecs_service.main["relay"].desired_count == 1
    error_message = "Only explicit post-bootstrap enablement may start the selected replicas."
  }
}

run "durable_documents" {
  command = plan
  assert {
    condition = (
      !aws_s3_bucket.originals.force_destroy &&
      aws_s3_bucket_public_access_block.originals.block_public_acls &&
      aws_s3_bucket_public_access_block.originals.block_public_policy &&
      aws_s3_bucket_public_access_block.originals.ignore_public_acls &&
      aws_s3_bucket_public_access_block.originals.restrict_public_buckets &&
      aws_s3_bucket_ownership_controls.originals.rule[0].object_ownership == "BucketOwnerEnforced" &&
      aws_s3_bucket_versioning.originals.versioning_configuration[0].status == "Suspended"
    )
    error_message = "Originals must have private owner-controlled access without retained historical versions or automatic destructive cleanup."
  }
  assert {
    condition = alltrue([for rule in aws_s3_bucket_server_side_encryption_configuration.originals.rule :
      !rule.bucket_key_enabled && rule.apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms" && rule.apply_server_side_encryption_by_default[0].kms_master_key_id == aws_kms_key.main.arn
    ])
    error_message = "Default encryption must use the selected KMS key and object-level encryption context."
  }
  assert {
    condition = (
      one([for rule in aws_s3_bucket_lifecycle_configuration.originals.rule : rule if rule.id == "original-retention-backstop"]).expiration[0].days == var.document_retention_days &&
      one([for rule in aws_s3_bucket_lifecycle_configuration.originals.rule : rule if rule.id == "original-retention-backstop"]).filter[0].prefix == "originals/" &&
      local.environment.DOCUMENT_RETENTION_DAYS == tostring(var.document_retention_days)
    )
    error_message = "S3 expiry backstop and application policy must agree, scoped to generated original keys."
  }
  assert {
    condition = (
      aws_guardduty_malware_protection_plan.originals.role == aws_iam_role.document_scan.arn &&
      aws_guardduty_malware_protection_plan.originals.protected_resource[0].s3_bucket[0].bucket_name == aws_s3_bucket.originals.id &&
      toset(aws_guardduty_malware_protection_plan.originals.protected_resource[0].s3_bucket[0].object_prefixes) == toset(["originals/"]) &&
      aws_guardduty_malware_protection_plan.originals.actions[0].tagging[0].status == "ENABLED" &&
      aws_s3_bucket_notification.originals.eventbridge
    )
    error_message = "New originals must reach the scanner with scan-result tagging enabled through EventBridge."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Effect == "Deny" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Condition.StringNotEquals["s3:ExistingObjectTag/GuardDutyMalwareScanStatus"] == "NO_THREATS_FOUND" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Condition.ArnNotEquals["aws:PrincipalArn"] == aws_iam_role.document_scan.arn &&
      toset(one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Action) == toset(["s3:GetObject", "s3:GetObjectVersion"])
    )
    error_message = "Only the scanner can read an untagged, pending or non-clean original; app and worker cannot bypass the gate."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NeverUploadScanResult"]).Effect == "Deny" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NeverUploadScanResult"]).Action == "s3:PutObject" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NeverUploadScanResult"]).Condition["ForAnyValue:StringEquals"]["s3:RequestObjectTagKeys"] == "GuardDutyMalwareScanStatus" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "OnlyScannerCanChangeTags"]).Effect == "Deny" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "OnlyScannerCanChangeTags"]).Condition.ArnNotEquals["aws:PrincipalArn"] == aws_iam_role.document_scan.arn &&
      toset(one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "OnlyScannerCanChangeTags"]).Action) == toset(["s3:PutObjectTagging", "s3:PutObjectVersionTagging", "s3:DeleteObjectTagging", "s3:DeleteObjectVersionTagging"])
    )
    error_message = "Applications cannot forge scan results during PUT or replace/delete scanner tags."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "RejectKMSKeyOverride"]).Condition.StringNotEquals["s3:x-amz-server-side-encryption-aws-kms-key-id"] == aws_kms_key.main.arn &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "RejectEncryptionOverride"]).Condition.StringNotEquals["s3:x-amz-server-side-encryption"] == "aws:kms" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "RejectImplicitManagedKMSKey"]).Condition.Null["s3:x-amz-server-side-encryption-aws-kms-key-id"] == "true"
    )
    error_message = "Default encryption must not be bypassed with another key or encryption algorithm."
  }
  assert {
    condition = (
      toset(keys(aws_iam_role_policy.documents)) == toset(["app", "worker", "relay"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[0].Action) == toset(["s3:PutObject", "s3:GetObject", "s3:GetObjectTagging"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["worker"].policy).Statement[0].Action) == toset(["s3:GetObject", "s3:GetObjectTagging"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["relay"].policy).Statement[0].Action) == toset(["s3:DeleteObject"]) &&
      length(jsondecode(aws_iam_role_policy.documents["relay"].policy).Statement) == 1 &&
      alltrue([for policy in aws_iam_role_policy.documents : jsondecode(policy.policy).Statement[0].Resource == "${aws_s3_bucket.originals.arn}/originals/*" && jsondecode(policy.policy).Statement[0].Condition.StringEquals["aws:SourceVpce"] == aws_vpc_endpoint.s3_layers.id])
    )
    error_message = "Only API may upload, worker may read, relay may delete, and bootstrap has no document access; all application objects use generated original keys through the endpoint."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[1].Condition.ArnLike["kms:EncryptionContext:aws:s3:arn"] == "${aws_s3_bucket.originals.arn}/originals/*" &&
      jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[1].Condition.StringEquals["kms:ViaService"] == "s3.${var.region}.amazonaws.com" &&
      toset(jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[1].Action) == toset(["kms:GenerateDataKey", "kms:Decrypt"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["worker"].policy).Statement[1].Action) == toset(["kms:Decrypt"])
    )
    error_message = "Document KMS permissions must be limited to S3 original-object context and each role's actual operation."
  }
  assert {
    condition = (
      toset(one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "ECRImageLayers"]).Resource) == toset(["arn:aws:s3:::prod-${var.region}-starport-layer-bucket/*"]) &&
      toset(one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "ECRImageLayers"]).Action) == toset(["s3:GetObject"]) &&
      length(jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement) == 4 &&
      alltrue([for role, actions in local.document_access :
        one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "Document${title(role)}"]).Principal.AWS == aws_iam_role.task[role].arn &&
        toset(one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "Document${title(role)}"]).Resource) == toset(["${aws_s3_bucket.originals.arn}/originals/*"])
      ])
    )
    error_message = "The S3 endpoint must preserve ECR layer access while restricting documents to their three separate task roles."
  }
  assert {
    condition = (
      local.environment.DOCUMENT_BUCKET == aws_s3_bucket.originals.id && local.environment.DOCUMENT_REGION == var.region && local.environment.DOCUMENT_SCAN_MODE == "guardduty" &&
      alltrue([for name in ["DOCUMENT_ENDPOINT", "DOCUMENT_ACCESS_KEY", "DOCUMENT_SECRET_KEY"] : !contains(keys(local.environment), name)])
    )
    error_message = "Cloud tasks must use the real bucket/region/GuardDuty with task credentials, never local endpoints or keys."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "ValidateBucket"]).Resource == "${aws_s3_bucket.originals.arn}/malware-protection-resource-validation-object" &&
      one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "ReadAndTagOriginals"]).Resource == "${aws_s3_bucket.originals.arn}/originals/*" &&
      one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "ManageGuardDutyRule"]).Condition.StringEquals["events:ManagedBy"] == "malware-protection-plan.guardduty.amazonaws.com" &&
      toset(one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "DecryptScanAndEncryptValidation"]).Condition.ArnLike["kms:EncryptionContext:aws:s3:arn"]) == toset(["${aws_s3_bucket.originals.arn}/originals/*", "${aws_s3_bucket.originals.arn}/malware-protection-resource-validation-object"])
    )
    error_message = "Scanner setup must include the precise validation object, EventBridge ownership condition and required encrypted-object contexts."
  }
}
run "reject_invalid_document_retention" {
  command = plan
  variables {
    document_retention_days = 0
  }
  expect_failures = [var.document_retention_days]
}
run "block_enable_when_scan_protection_is_not_active" {
  command = plan
  variables {
    image_digests       = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    enable_services     = true
    bootstrap_completed = true
  }
  override_resource {
    target          = aws_guardduty_malware_protection_plan.originals
    override_during = plan
    values          = { status = "WARNING" }
  }
  expect_failures = [aws_ecs_service.main]
}

override_resource {
  target          = aws_secretsmanager_secret.app["django"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:app-django-AbCdEf" }
}

override_resource {
  target          = aws_secretsmanager_secret.app["database"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:app-database-AbCdEf" }
}

override_resource {
  target          = aws_secretsmanager_secret.app["broker"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:app-broker-AbCdEf" }
}

override_resource {
  target          = aws_secretsmanager_secret.app["reviewer"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:app-reviewer-AbCdEf" }
}

override_resource {
  target          = aws_secretsmanager_secret.fanout["gateway"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:fanout-gateway-AbCdEf" }
}

override_resource {
  target          = aws_secretsmanager_secret.fanout["relay"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:fanout-relay-AbCdEf" }
}

override_resource {
  target          = aws_secretsmanager_secret.proxy["app"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:proxy-app-AbCdEf" }
}

override_resource {
  target          = aws_secretsmanager_secret.proxy["stream"]
  override_during = plan
  values          = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:proxy-stream-AbCdEf" }
}

run "event_delivery_small_profile" {
  command = plan
  variables {
    image_digests       = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    enable_services     = true
    bootstrap_completed = true
  }
  assert {
    condition     = length(aws_elasticache_replication_group.fanout) == 2 && alltrue([for shard in aws_elasticache_replication_group.fanout : shard.engine == "valkey" && shard.cluster_mode == "disabled" && shard.num_cache_clusters == 2 && shard.automatic_failover_enabled && shard.multi_az_enabled && shard.at_rest_encryption_enabled && shard.kms_key_id == aws_kms_key.main.arn && shard.transit_encryption_enabled && shard.transit_encryption_mode == "required" && toset(shard.user_group_ids) == toset([aws_elasticache_user_group.fanout.id])])
    error_message = "Each independent owner shard requires private authenticated encrypted failover topology."
  }
  assert {
    condition     = aws_elasticache_user_group.fanout.engine == "valkey" && toset(keys(aws_elasticache_user.fanout)) == toset(["gateway", "relay"]) && !strcontains(aws_elasticache_user.fanout["gateway"].access_string, "+@all") && !strcontains(aws_elasticache_user.fanout["relay"].access_string, "+eval") && !strcontains(aws_elasticache_user.fanout["relay"].access_string, "+subscribe") && toset(keys(aws_vpc_security_group_ingress_rule.fanout)) == toset(["gateway", "event-relay"])
    error_message = "Fan-out must reject default/admin access and restrict relay commands and network roles."
  }
  assert {
    condition     = one(one(aws_lb_listener_rule.events.condition).path_pattern).values == toset(["/api/events/"]) && aws_lb_listener_rule.events.action[0].target_group_arn == aws_lb_target_group.gateway.arn && aws_lb_target_group.gateway.port == 8001 && aws_lb_target_group.gateway.health_check[0].path == "/health/" && aws_lb.main.idle_timeout > 15 && aws_vpc_security_group_ingress_rule.gateway.from_port == 8001
    error_message = "Only exact SSE traffic may enter the async gateway through the existing HTTPS ALB."
  }
  assert {
    condition     = aws_ecs_service.main["gateway"].desired_count == 3 && aws_appautoscaling_target.service["gateway"].min_capacity == 3 && aws_appautoscaling_target.service["gateway"].max_capacity == 12 && jsondecode(aws_ecs_task_definition.service["gateway"].container_definitions)[0].portMappings[0].containerPort == 8001 && join(" ", local.commands["event-relay"]) == "python manage.py relay_events" && contains(local.commands["gateway"], "event_gateway:application")
    error_message = "Start small while running the same independent ASGI gateway and durable event relay."
  }
  assert {
    condition     = local.role_environment["gateway"].STREAM_REDIS_HOSTS == local.fanout_hosts && local.role_environment["event-relay"].STREAM_REDIS_HOSTS == local.fanout_hosts && local.role_environment["gateway"].STREAM_REDIS_USERNAME == "gateway" && local.role_environment["event-relay"].STREAM_REDIS_USERNAME == "relay" && local.role_environment["gateway"].STREAM_REDIS_TLS == "true" && local.role_environment["gateway"].DELIVERY_CLOUD_METRICS == "true"
    error_message = "Publisher and every gateway need the same ordered map, scoped identities, TLS and actual EMF emission."
  }
  assert {
    condition     = local.role_environment["gateway"].POSTGRES_USER == "resume_stream" && local.role_environment["gateway"].POSTGRES_HOST == aws_db_proxy.main.endpoint && local.role_environment["app"].POSTGRES_HOST == aws_db_proxy.main.endpoint && local.role_environment["bootstrap"].POSTGRES_HOST == aws_db_instance.main.address && local.role_environment["gateway"].POSTGRES_PROXY_MODE == "true" && local.role_environment["bootstrap"].POSTGRES_PROXY_MODE == "false" && local.role_environment["gateway"].POSTGRES_SSLROOTCERT == "/app/certs/amazon-trust-services.pem" && local.role_environment["bootstrap"].POSTGRES_SSLROOTCERT == "/app/certs/rds-global-bundle.pem"
    error_message = "Gateway/app use proxy-specific verified TLS while bootstrap remains direct and credential-isolated."
  }
  assert {
    condition     = aws_db_proxy.main.require_tls && aws_db_proxy.main.engine_family == "POSTGRESQL" && length(aws_db_proxy.main.auth) == 2 && aws_db_proxy_default_target_group.main.connection_pool_config[0].connection_borrow_timeout == 2 && aws_db_proxy_target.main.db_instance_identifier == aws_db_instance.main.identifier && toset(keys(aws_vpc_security_group_ingress_rule.database)) == toset(["bootstrap"])
    error_message = "Only bootstrap may bypass the private bounded proxy; both database identities need its scoped authentication."
  }
  assert {
    condition     = jsondecode(aws_secretsmanager_secret_version.proxy["app"].secret_string).username == "resume_app" && jsondecode(aws_secretsmanager_secret_version.proxy["stream"].secret_string).username == "resume_stream" && toset(local.secret_access["gateway"]) == toset([aws_secretsmanager_secret.app["django"].arn, aws_secretsmanager_secret.proxy["stream"].arn, aws_secretsmanager_secret.fanout["gateway"].arn]) && !strcontains(aws_iam_role_policy.execution["gateway"].policy, aws_secretsmanager_secret.app["database"].arn) && !strcontains(aws_iam_role_policy.execution["event-relay"].policy, aws_secretsmanager_secret.app["broker"].arn) && !contains(keys(aws_iam_role_policy.documents), "gateway") && !contains(keys(aws_iam_role_policy.documents), "event-relay")
    error_message = "Credential JSON and execution policies must preserve read-only gateway and broker/source isolation."
  }
  assert {
    condition     = aws_appautoscaling_policy.connections["gateway"].target_tracking_scaling_policy_configuration[0].customized_metric_specification[0].metric_name == "ConnectedStreams" && aws_appautoscaling_policy.connections["gateway"].target_tracking_scaling_policy_configuration[0].customized_metric_specification[0].statistic == "Average" && aws_appautoscaling_policy.connections["gateway"].target_tracking_scaling_policy_configuration[0].target_value == 1400 && length(aws_appautoscaling_policy.utilization) == 6 && alltrue([for alarm in aws_cloudwatch_metric_alarm.fanout : alarm.dimensions.CacheNodeId == "0001"]) && length(aws_cloudwatch_query_definition.journey.log_group_names) == 5 && alltrue([for alarm in aws_cloudwatch_metric_alarm.proxy : alarm.dimensions.ProxyName == aws_db_proxy.main.name && length(alarm.dimensions) == 1]) && aws_cloudwatch_metric_alarm.admission_queue_age.threshold == var.queue_age_limit_seconds * 1000 && aws_cloudwatch_log_metric_filter.admission_queue_age.metric_transformation[0].value == "$.oldest_queue_age_ms" && local.rollout_vcpu <= var.capacity_limits.fargate_vcpu && alltrue([for subnet in aws_subnet.private : endswith(subnet.cidr_block, "/20")])
    error_message = "Small actual limits need connection/CPU/memory scaling and enough private address/rollout headroom."
  }
  assert {
    condition     = alltrue([for secret in local.api_containers["gateway"].secrets : secret.name != "RABBITMQ_PASSWORD" && secret.name != "RDS_MASTER_PASSWORD" && secret.name != "CLOUD_REVIEWER_PASSWORD"]) && one([for item in local.web_container.environment : item.value if item.name == "FRONTEND_EVENTS_TRANSPORT"]) == "alb"
    error_message = "Cloud nginx must delegate events to ALB and gateway must receive no privileged/broker credentials."
  }
}
run "disabled_scaling_stops_services" {
  command = plan
  variables {
    image_digests = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  assert {
    condition     = alltrue([for target in aws_appautoscaling_target.service : target.min_capacity == 0 && target.max_capacity == 0 && target.suspended_state[0].dynamic_scaling_out_suspended])
    error_message = "Disabling must clamp even an already autoscaled service to zero instead of ignoring desired-count drift."
  }
}
run "reject_insufficient_rollout_budget" {
  command = plan
  variables {
    capacity_limits = { alb_targets = 10, target_group_targets = 10, fargate_vcpu = 64, proxy_clients = 512, database_backends = 256 }
  }
  expect_failures = [terraform_data.capacity]
}
run "reject_insufficient_database_budget" {
  command = plan
  variables {
    capacity_limits = { alb_targets = 1000, target_group_targets = 1000, fargate_vcpu = 64, proxy_clients = 32, database_backends = 100 }
  }
  expect_failures = [terraform_data.capacity]
}
run "reject_too_small_vpc" {
  command = plan
  variables { vpc_cidr = "10.42.0.0/20" }
  expect_failures = [var.vpc_cidr]
}
run "large_configuration_arithmetic_only" {
  command = plan
  variables {
    service_capacity = {
      app         = { min = 2, max = 12 }
      worker      = { min = 2, max = 12 }
      relay       = { min = 1, max = 1 }
      gateway     = { min = 1074, max = 1074 }
      event-relay = { min = 1, max = 1 }
    }
    capacity_limits = { alb_targets = 3000, target_group_targets = 3000, fargate_vcpu = 1200, proxy_clients = 10000, database_backends = 256 }
  }
  assert {
    condition     = local.gateway_rollout_targets == 2148 && local.proxy_rollout_clients < 10000 && length(aws_ecs_service.main) == 0
    error_message = "Large inputs exercise the same finite budget model without starting resources or claiming measured capacity."
  }
}

override_resource {
  target          = aws_elasticache_user_group.fanout
  override_during = plan
  values          = { id = "resume-match-fanout" }
}
override_resource {
  target          = aws_lb_target_group.gateway
  override_during = plan
  values          = { arn = "arn:aws:elasticloadbalancing:us-east-1:111122223333:targetgroup/resume-match-events/1234567890123456" }
}

run "reject_insufficient_private_addresses" {
  command = plan
  variables {
    service_capacity = {
      app         = { min = 2, max = 12 }
      worker      = { min = 2, max = 12 }
      relay       = { min = 1, max = 1 }
      gateway     = { min = 3, max = 5000 }
      event-relay = { min = 1, max = 1 }
    }
    capacity_limits = { alb_targets = 20000, target_group_targets = 20000, fargate_vcpu = 10000, proxy_clients = 50000, database_backends = 256 }
  }
  expect_failures = [terraform_data.capacity]
}
