variable "function_name" {
  type = string
}

variable "source_file_path" {
  type = string
}

variable "additional_dirs" {
  type        = map(string)
  default     = {}
  description = "Extra directories (text files only) to bundle into the Lambda zip: directory inside the zip => local directory path."
}

variable "target_zip_file_path" {
  type = string
}
variable "runtime" {
  type = string
}

variable "handler" {
  type = string
}

variable "timeout_seconds" {
  type        = number
  default     = 120
  description = "Maximum Lambda execution time in seconds (1-900)."

  validation {
    condition     = var.timeout_seconds >= 1 && var.timeout_seconds <= 900
    error_message = "timeout_seconds must be between 1 and 900 seconds (15 minutes)."
  }
}

# arm64 (Graviton) is ~20% cheaper per GB-second than x86_64, with equal or better performance
variable "architecture" {
  type        = string
  default     = "arm64"
  description = "Lambda instruction set architecture (arm64 or x86_64)."

  validation {
    condition     = contains(["arm64", "x86_64"], var.architecture)
    error_message = "architecture must be either \"arm64\" or \"x86_64\"."
  }
}

variable "layers" {
  type        = list(string)
  default     = []
  description = "Lambda layer version ARNs to attach to the function (max 5)."
}


variable "env_vars" {
  type = map(string)

  default = {}
}

variable "additional_iam_policy_statements" {
  type = list(object({
    sid       = optional(string)
    effect    = optional(string, "Allow")
    actions   = list(string)
    resources = list(string)
  }))

  default     = []
  description = "Extra IAM policy statements granted to the Lambda execution role (in addition to basic execution)."
}

variable "managed_policy_arns" {
  type        = list(string)
  default     = []
  description = "ARNs of IAM managed policies attached to the Lambda execution role (in addition to basic execution)."
}

variable "log_retention_days" {
  type        = number
  default     = 14
  description = "CloudWatch log group retention in days for the Lambda's logs (0 = never expire)."

  validation {
    condition     = contains([0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a value supported by CloudWatch Logs (e.g. 1, 3, 5, 7, 14, 30, 60, 90, ...) or 0 for never expire."
  }
}


#Lambda allocates CPU power in proportion to the amount of memory configured.
# You can increase or decrease the memory and CPU power allocated to your function using the Memory (MB) setting.
# At 1,769 MB, a function has the equivalent of one vCPU.
variable "memory_size_mb" {
  default = 256
  type    = number
}


variable "schedule_expression" {
  type        = string
  default     = null
  description = "Optional schedule to invoke the Lambda on, in UTC: cron(...), rate(...) or at(...). AWS cron needs ? in day-of-month or day-of-week, e.g. cron(0 2 * * ? *). Creates an EventBridge Scheduler schedule and its IAM role when set."
}
