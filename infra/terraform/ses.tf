resource "aws_sesv2_email_identity" "password_reset" {
  email_identity = var.email_from
}

resource "aws_sesv2_email_identity" "test_recipient" {
  count          = var.ses_test_recipient != null && var.ses_test_recipient != var.email_from ? 1 : 0
  email_identity = var.ses_test_recipient
}
