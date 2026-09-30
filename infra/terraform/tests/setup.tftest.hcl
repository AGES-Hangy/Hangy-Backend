mock_provider "aws" {
  override_during = plan

  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-2a", "us-east-2b"] }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_ami" {
    defaults = { id = "ami-0123456789abcdef0", architecture = "arm64" }
  }
  mock_resource "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/tools.ages.pucrs.br" }
  }
  mock_resource "aws_db_instance" {
    defaults = { address = "hangy.test.rds.amazonaws.com" }
  }
  mock_resource "aws_security_group" {
    defaults = { id = "sg-0123456789abcdef0" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::hangy-production-123456789012-us-east-2" }
  }
}

mock_provider "random" {
  override_during = plan

  mock_resource "random_password" {
    defaults = { result = "TestPasswordForMockProviderOnly1234567890" }
  }
}

variables {
  gitlab_project_path = "2026-2/2jk-4jk/hangy/hangy-backend"
  frontend_base_url = "https://hangy.example"
  api_allowed_cidrs = ["203.0.113.0/24"]
}

run "secure_arm_stack" {
  command = plan

  assert {
    condition     = aws_instance.api.instance_type == "t4g.medium" && aws_instance.api.ami == data.aws_ami.amazon_linux.id
    error_message = "A API deve usar t4g.medium com a AMI ARM64 selecionada."
  }
  assert {
    condition     = aws_instance.api.metadata_options[0].http_tokens == "required" && aws_instance.api.root_block_device[0].encrypted
    error_message = "A EC2 deve exigir IMDSv2 e criptografar o volume."
  }
  assert {
    condition     = !aws_db_instance.main.publicly_accessible && aws_db_instance.main.storage_encrypted && aws_db_instance.main.deletion_protection && aws_db_instance.main.backup_retention_period == 7
    error_message = "O banco deve ser privado, criptografado, protegido contra exclusão e ter backups."
  }
  assert {
    condition     = length(aws_subnet.database) == 2 && aws_subnet.database[0].availability_zone != aws_subnet.database[1].availability_zone
    error_message = "O RDS precisa de sub-redes em duas zonas distintas."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.database.referenced_security_group_id == aws_security_group.api.id && aws_vpc_security_group_ingress_rule.database.from_port == 5432 && aws_vpc_security_group_ingress_rule.database.cidr_ipv4 == null
    error_message = "A porta do RDS deve aceitar somente o security group da API."
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.api) == 1 && aws_vpc_security_group_ingress_rule.api["203.0.113.0/24"].from_port == 8000
    error_message = "A API deve respeitar os CIDRs e a porta configurados."
  }
  assert {
    condition     = jsondecode(aws_iam_role.gitlab.assume_role_policy).Statement[0].Condition.StringEquals["tools.ages.pucrs.br:sub"] == "project_path:2026-2/2jk-4jk/hangy/hangy-backend:ref_type:branch:ref:main"
    error_message = "OIDC deve autorizar somente a main do repositório informado."
  }
  assert {
    condition     = aws_iam_openid_connect_provider.gitlab[0].url == "https://tools.ages.pucrs.br" && contains(aws_iam_openid_connect_provider.gitlab[0].client_id_list, "sts.amazonaws.com") && jsondecode(aws_iam_role.gitlab.assume_role_policy).Statement[0].Condition.StringEquals["tools.ages.pucrs.br:aud"] == "sts.amazonaws.com"
    error_message = "O provedor e a role devem validar o emissor AGES e a audiência AWS STS."
  }
  assert {
    condition     = jsondecode(aws_secretsmanager_secret_version.app.secret_string).DATABASE_URL == "postgresql+psycopg://hangy:TestPasswordForMockProviderOnly1234567890@hangy.test.rds.amazonaws.com:5432/hangy?sslmode=require&connect_timeout=10"
    error_message = "O segredo deve apontar para o RDS criado e exigir TLS."
  }
  assert {
    condition     = jsondecode(aws_secretsmanager_secret_version.app.secret_string).CORS_ORIGINS == var.frontend_base_url && jsondecode(aws_secretsmanager_secret_version.app.secret_string).FRONTEND_BASE_URL == var.frontend_base_url
    error_message = "O segredo deve incluir a URL do frontend e usá-la como origem CORS padrão."
  }
  assert {
    condition     = toset(keys(output.deployment_variables)) == toset(["AWS_REGION", "AWS_ROLE_ARN", "ECR_REPOSITORY", "EC2_INSTANCE_ID", "APP_SECRET_ARN"])
    error_message = "Os outputs devem incluir exatamente as variáveis consumidas pelo deploy."
  }
}

run "estimate_settings" {
  command = plan

  assert {
    condition     = var.aws_region == "us-east-2" && output.deployment_variables.AWS_REGION == "us-east-2"
    error_message = "A infraestrutura e o deploy devem usar Ohio, conforme a estimativa."
  }
  assert {
    condition     = aws_instance.api.instance_type == "t4g.medium" && aws_instance.api.tenancy == "default" && !aws_instance.api.monitoring
    error_message = "A EC2 deve usar t4g.medium, tenancy compartilhada e monitoramento básico."
  }
  assert {
    condition     = aws_db_instance.main.instance_class == "db.t4g.micro" && !aws_db_instance.main.multi_az && aws_db_instance.main.allocated_storage == 50 && aws_db_instance.main.storage_type == "gp2" && aws_db_instance.main.max_allocated_storage == 0
    error_message = "O RDS deve corresponder à estimativa: db.t4g.micro, Single-AZ, 50 GB gp2 fixos."
  }
  assert {
    condition     = aws_s3_bucket.app.bucket == "hangy-production-123456789012-us-east-2" && !aws_s3_bucket.app.force_destroy
    error_message = "O bucket deve ter nome específico da conta/região e preservar objetos na exclusão."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.app.block_public_acls && aws_s3_bucket_public_access_block.app.block_public_policy && aws_s3_bucket_public_access_block.app.ignore_public_acls && aws_s3_bucket_public_access_block.app.restrict_public_buckets
    error_message = "O bucket de armazenamento deve permanecer privado."
  }
  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.app.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256" && aws_s3_bucket_ownership_controls.app.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "O bucket deve criptografar objetos com SSE-S3 e desabilitar ACLs."
  }
  assert {
    condition     = jsondecode(aws_s3_bucket_policy.app.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false" && jsondecode(aws_s3_bucket_policy.app.policy).Statement[0].Effect == "Deny"
    error_message = "O bucket deve recusar transporte sem TLS."
  }
}

run "reuse_oidc_and_multiple_origins" {
  command = plan
  variables {
    gitlab_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/tools.ages.pucrs.br"
    cors_origins             = ["https://hangy.example", "https://admin.hangy.example"]
  }
  assert {
    condition     = length(aws_iam_openid_connect_provider.gitlab) == 0
    error_message = "Não deve tentar recriar um provedor OIDC compartilhado existente."
  }
  assert {
    condition     = jsondecode(aws_iam_role.gitlab.assume_role_policy).Statement[0].Principal.Federated == var.gitlab_oidc_provider_arn
    error_message = "A role deve confiar no provedor OIDC reutilizado."
  }
  assert {
    condition     = jsondecode(aws_secretsmanager_secret_version.app.secret_string).CORS_ORIGINS == "https://hangy.example,https://admin.hangy.example"
    error_message = "As origens devem ser serializadas no formato aceito pela API."
  }
}

run "reject_invalid_network" {
  command = plan
  variables {
    api_allowed_cidrs = ["not-a-cidr"]
  }
  expect_failures = [var.api_allowed_cidrs]
}

run "reject_invalid_repository" {
  command = plan
  variables {
    gitlab_project_path = "example/*"
  }
  expect_failures = [var.gitlab_project_path]
}
