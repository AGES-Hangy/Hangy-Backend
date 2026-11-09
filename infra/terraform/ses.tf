resource "aws_sesv2_email_identity" "password_reset" {
  email_identity = var.email_from
}
