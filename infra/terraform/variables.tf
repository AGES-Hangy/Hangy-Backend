variable "aws_region" {
  description = "Região de todos os recursos regionais; Ohio conforme My Estimate.json."
  type        = string
  default     = "us-east-2"
}

variable "name" {
  description = "Prefixo único dos recursos desta instalação."
  type        = string
  default     = "hangy-production"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.name)) && !strcontains(var.name, "--")
    error_message = "Use de 3 a 32 letras minúsculas, números ou hífens, sem hífens consecutivos."
  }
}

variable "gitlab_url" {
  description = "URL pública HTTPS da instância GitLab que emite os tokens OIDC."
  type        = string
  default     = "https://tools.ages.pucrs.br"
  validation {
    condition     = can(regex("^https://[A-Za-z0-9.-]+$", var.gitlab_url))
    error_message = "Informe a URL HTTPS do GitLab sem caminho ou barra final."
  }
}

variable "gitlab_project_path" {
  description = "Caminho do projeto autorizado no GitLab, incluindo todos os subgrupos."
  type        = string
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$", var.gitlab_project_path))
    error_message = "Informe o caminho grupo/subgrupo/projeto, sem curingas."
  }
}

variable "gitlab_oidc_provider_arn" {
  description = "ARN do provedor OIDC do GitLab se já existir nesta conta; null cria um."
  type        = string
  default     = null
  validation {
    condition     = var.gitlab_oidc_provider_arn == null ? true : can(regex("^arn:[^:]+:iam::[0-9]{12}:oidc-provider/[^/]+$", var.gitlab_oidc_provider_arn)) && endswith(var.gitlab_oidc_provider_arn, ":oidc-provider/${trimprefix(var.gitlab_url, "https://")}")
    error_message = "Informe o ARN do provedor correspondente a gitlab_url ou null."
  }
}

variable "api_allowed_cidrs" {
  description = "Origens IPv4 autorizadas a acessar a API na porta 8000."
  type        = set(string)
  validation {
    condition     = length(var.api_allowed_cidrs) > 0 && alltrue([for cidr in var.api_allowed_cidrs : can(cidrnetmask(cidr))])
    error_message = "Informe pelo menos um CIDR IPv4 válido."
  }
}

variable "frontend_base_url" {
  description = "URL HTTP(S) do frontend usada nos links de compartilhamento."
  type        = string
  validation {
    condition     = can(regex("^https?://[^,\\s]+$", var.frontend_base_url))
    error_message = "Informe uma URL HTTP(S) sem espaços ou vírgulas."
  }
}

variable "cors_origins" {
  description = "Origens HTTP(S) autorizadas; uma lista vazia usa a URL do frontend."
  type        = list(string)
  default     = []
  validation {
    condition     = alltrue([for origin in var.cors_origins : can(regex("^https?://[^,\\s]+$", origin))])
    error_message = "Cada origem deve ser uma URL HTTP(S) sem espaços ou vírgulas."
  }
}

variable "db_instance_class" {
  description = "Classe do RDS PostgreSQL; a EC2 da API é t4g.medium."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "Versão PostgreSQL aceita pelo RDS na região."
  type        = string
  default     = "17"
}

variable "db_deletion_protection" {
  description = "Proteção adicional contra exclusão do RDS pela AWS."
  type        = bool
  default     = true
}
