variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for globally unique names. The bucket is <prefix>-weather-<account id>."
  type        = string
}

variable "image_tag" {
  description = "Tag of the pushed image; the Lambda pins its digest."
  type        = string
  default     = "latest"
}

variable "default_tags" {
  type    = map(string)
  default = { project = "weather-lake" }
}

variable "alarm_topic_arns" {
  description = "SNS topics for the freshness alarm; empty for none."
  type        = list(string)
  default     = []
}

variable "config_path" {
  description = "config.yaml, relative to this root."
  type        = string
  default     = "../../config.yaml"
}

variable "contract_path" {
  description = "The library module defining CONTRACT_VERSION, relative to this root."
  type        = string
  default     = "../../lake/src/weather_lake/contract.py"
}

variable "github_sub_prefix" {
  description = "OIDC subject prefix of the deploying repository; null skips the CI roles."
  type        = string
  default     = null
}

variable "tfstate_bucket" {
  description = "Bucket holding this root's state (the deploy role reads and writes it)."
  type        = string
  default     = null

  validation {
    condition     = var.github_sub_prefix == null || var.tfstate_bucket != null
    error_message = "tfstate_bucket is required when github_sub_prefix is set."
  }
}
