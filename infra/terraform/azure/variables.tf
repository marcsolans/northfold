variable "subscription_id" {
  description = "Azure subscription that hosts the data plane."
  type        = string
}

variable "name" {
  description = "Prefix for every resource (lowercase letters and digits, 3-16 characters)."
  type        = string
  default     = "messerdp"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.name))
    error_message = "name must be 3-16 lowercase letters or digits (storage accounts do not allow dashes)."
  }
}

variable "location" {
  description = "Azure region. Must be in the EU (data residency)."
  type        = string
  default     = "westeurope"

  validation {
    condition = contains([
      "westeurope", "northeurope", "germanywestcentral", "francecentral", "swedencentral", "italynorth",
      "polandcentral", "spaincentral", "norwayeast", "switzerlandnorth",
    ], var.location)
    error_message = "The Messer data plane must run in a European region."
  }
}

variable "vnet_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

variable "node_vm_size" {
  type    = string
  default = "Standard_D4s_v5"
}

variable "node_min_count" {
  type    = number
  default = 3
}

variable "node_max_count" {
  type    = number
  default = 10
}

variable "postgres_sku" {
  description = "PostgreSQL Flexible Server SKU."
  type        = string
  default     = "GP_Standard_D4ds_v5"
}

variable "postgres_storage_mb" {
  type    = number
  default = 131072
}

variable "postgres_backup_retention_days" {
  type    = number
  default = 14
}

variable "postgres_high_availability" {
  type    = bool
  default = true
}

variable "redis_sku" {
  type    = string
  default = "Standard"
}

variable "redis_capacity" {
  type    = number
  default = 1
}

variable "kubernetes_namespace" {
  type    = string
  default = "messer"
}

variable "kubernetes_service_account" {
  type    = string
  default = "messer-dp-messer-data-plane"
}

variable "tags" {
  type    = map(string)
  default = {}
}
