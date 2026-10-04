data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-*-arm64"]
  }
  filter {
    name   = "architecture"
    values = ["arm64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_ecr_repository" "app" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_instance" "api" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = "t4g.medium"
  tenancy                     = "default"
  monitoring                  = false
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.api.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.ec2.name

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail
    systemctl enable --now amazon-ssm-agent
  EOF

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = { Name = var.name }

  # Keep the chosen AMI until an intentional instance replacement is requested.
  lifecycle {
    ignore_changes = [ami]
  }

  depends_on = [
    aws_route.internet,
    aws_route_table_association.public,
    aws_iam_role_policy_attachment.ssm,
    aws_iam_role_policy.ec2,
    aws_vpc_security_group_egress_rule.api,
  ]
}

resource "aws_eip" "api" {
  domain   = "vpc"
  instance = aws_instance.api.id

  depends_on = [aws_internet_gateway.main]
}

resource "aws_ssm_document" "bootstrap" {
  name          = "${var.name}-bootstrap"
  document_type = "Command"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Prepare Hangy ARM64 EC2 for Docker deployments"
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "InstallRuntime"
      inputs = {
        timeoutSeconds = "900"
        runCommand     = ["echo '${filebase64("${path.module}/bootstrap-ec2.sh")}' | base64 --decode | bash"]
      }
    }]
  })
}

resource "aws_ssm_association" "bootstrap" {
  name                             = aws_ssm_document.bootstrap.name
  document_version                 = aws_ssm_document.bootstrap.latest_version
  association_name                 = "${var.name}-bootstrap"
  wait_for_success_timeout_seconds = 1200

  targets {
    key    = "InstanceIds"
    values = [aws_instance.api.id]
  }

  depends_on = [aws_eip.api]
}
