output "deployment_variables" {
  description = "Identificadores passados pelo Terraform às etapas de deploy no workflow."
  value = {
    AWS_REGION      = var.aws_region
    AWS_ROLE_ARN    = aws_iam_role.gitlab.arn
    ECR_REPOSITORY  = aws_ecr_repository.app.name
    EC2_INSTANCE_ID = aws_instance.api.id
    APP_SECRET_ARN  = aws_secretsmanager_secret.app.arn
  }

  depends_on = [aws_ssm_association.bootstrap, aws_secretsmanager_secret_version.app]
}

output "api_url" {
  description = "Endpoint HTTP; responderá depois do primeiro deploy da aplicação."
  value       = "http://${aws_eip.api.public_ip}:8000"
}

output "rds_endpoint" {
  description = "Endpoint privado do PostgreSQL."
  value       = aws_db_instance.main.endpoint
}

output "s3_bucket_name" {
  description = "Bucket privado de objetos S3 Standard previsto na estimativa."
  value       = aws_s3_bucket.app.id
}
