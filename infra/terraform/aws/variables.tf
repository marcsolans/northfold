variable "name" {
  description = "Prefix for every resource (lowercase letters, digits and dashes)."
  type        = string
  default     = "messer-dp"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "name must be 3-25 characters: lowercase letters, digits and dashes."
  }
}

variable "region" {
  description = "AWS region. Must be an EU region (data residency)."
  type        = string
  default     = "eu-central-1"

  validation {
    condition     = startswith(var.region, "eu-")
    error_message = "The Messer data plane must run in an EU region (eu-*)."
  }
}

variable "bedrock_regions" {
  description = "EU regions where the data plane may invoke Claude on Amazon Bedrock (strict EU residency)."
  type        = list(string)
  default     = ["eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1"]

  validation {
    condition     = alltrue([for r in var.bedrock_regions : startswith(r, "eu-")])
    error_message = "Bedrock regions must be EU regions."
  }
}

variable "vpc_cidr" {
  description = "CIDR of the data-plane VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "availability_zones" {
  description = "Number of availability zones (2 or 3)."
  type        = number
  default     = 3
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.31"
}

variable "node_instance_types" {
  description = "Instance types of the EKS managed node group."
  type        = list(string)
  default     = ["m6i.xlarge"]
}

variable "node_min_size" {
  type    = number
  default = 3
}

variable "node_max_size" {
  type    = number
  default = 10
}

variable "node_desired_size" {
  type    = number
  default = 3
}

variable "cluster_public_access_cidrs" {
  description = "CIDRs allowed to reach the EKS API publicly. Empty = private endpoint only."
  type        = list(string)
  default     = []
}

variable "postgres_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "postgres_allocated_storage_gb" {
  type    = number
  default = 100
}

variable "postgres_multi_az" {
  type    = bool
  default = true
}

variable "postgres_backup_retention_days" {
  type    = number
  default = 14
}

variable "redis_node_type" {
  type    = string
  default = "cache.r7g.large"
}

variable "deletion_protection" {
  description = "Protect the database and the KMS key from accidental deletion."
  type        = bool
  default     = true
}

variable "kubernetes_namespace" {
  description = "Namespace where the messer-data-plane Helm chart is installed (for workload identity)."
  type        = string
  default     = "messer"
}

variable "kubernetes_service_account" {
  description = "Service account of the Helm release (fullname of the chart)."
  type        = string
  default     = "messer-dp-messer-data-plane"
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
