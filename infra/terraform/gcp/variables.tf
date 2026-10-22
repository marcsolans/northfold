variable "project_id" {
  description = "GCP project that hosts the data plane."
  type        = string
}

variable "name" {
  description = "Prefix for every resource (lowercase letters, digits and dashes)."
  type        = string
  default     = "messer-dp"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.name))
    error_message = "name must be 3-21 characters: lowercase letters, digits and dashes."
  }
}

variable "region" {
  description = "GCP region. Must be in Europe (data residency)."
  type        = string
  default     = "europe-west3"

  validation {
    condition     = startswith(var.region, "europe-")
    error_message = "The Messer data plane must run in a European region (europe-*)."
  }
}

variable "subnet_cidr" {
  type    = string
  default = "10.44.0.0/20"
}

variable "pods_cidr" {
  type    = string
  default = "10.48.0.0/14"
}

variable "services_cidr" {
  type    = string
  default = "10.52.0.0/20"
}

variable "master_cidr" {
  description = "CIDR of the private GKE control plane."
  type        = string
  default     = "172.16.0.0/28"
}

variable "master_authorized_cidrs" {
  description = "CIDRs allowed to reach the GKE API."
  type        = list(string)
  default     = []
}

variable "node_machine_type" {
  type    = string
  default = "e2-standard-4"
}

variable "node_min_count" {
  description = "Minimum nodes per zone."
  type        = number
  default     = 1
}

variable "node_max_count" {
  description = "Maximum nodes per zone."
  type        = number
  default     = 4
}

variable "postgres_tier" {
  type    = string
  default = "db-custom-4-16384"
}

variable "postgres_disk_gb" {
  type    = number
  default = 100
}

variable "postgres_high_availability" {
  type    = bool
  default = true
}

variable "redis_memory_gb" {
  type    = number
  default = 5
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "kubernetes_namespace" {
  type    = string
  default = "messer"
}

variable "kubernetes_service_account" {
  type    = string
  default = "messer-dp-messer-data-plane"
}

variable "labels" {
  type    = map(string)
  default = {}
}
