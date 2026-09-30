resource "random_password" "database" {
  length  = 40
  special = false
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_id" "final_snapshot" {
  byte_length = 4
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.database[*].id
}

resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.name}-"
  family      = "postgres${split(".", var.db_engine_version)[0]}"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "main" {
  identifier                 = var.name
  engine                     = "postgres"
  engine_version             = var.db_engine_version
  instance_class             = var.db_instance_class
  db_name                    = "hangy"
  username                   = "hangy"
  password                   = random_password.database.result
  port                       = 5432
  allocated_storage          = 50
  max_allocated_storage      = 0
  storage_type               = "gp2"
  storage_encrypted          = true
  publicly_accessible        = false
  multi_az                   = false
  db_subnet_group_name       = aws_db_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.database.id]
  parameter_group_name       = aws_db_parameter_group.main.name
  backup_retention_period    = 7
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.db_deletion_protection
  skip_final_snapshot        = false
  final_snapshot_identifier  = "${var.name}-final-${random_id.final_snapshot.hex}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/app"
  recovery_window_in_days = 30

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL                = "postgresql+psycopg://hangy:${urlencode(random_password.database.result)}@${aws_db_instance.main.address}:5432/hangy?sslmode=require&connect_timeout=10"
    JWT_SECRET_KEY              = random_password.jwt.result
    JWT_ALGORITHM               = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = "30"
    CORS_ORIGINS                = join(",", length(var.cors_origins) > 0 ? var.cors_origins : [trimsuffix(var.frontend_base_url, "/")])
    FRONTEND_BASE_URL           = var.frontend_base_url
    INVITE_LINK_BASE_URL        = "hangy://invite/"
  })
}
