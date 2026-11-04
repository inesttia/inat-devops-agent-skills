variable "region" {
  type    = string
  default = "eu-west-1"
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "vpc_id" {
  type    = string
  default = "vpc-0a1b2c3d4e5f60000"
}

variable "public_subnet_ids" {
  type    = list(string)
  default = ["subnet-0a1b2c3d4e5f60001", "subnet-0a1b2c3d4e5f60002"]
}

variable "db_subnet_ids" {
  type    = list(string)
  default = ["subnet-0a1b2c3d4e5f60010", "subnet-0a1b2c3d4e5f60011"]
}

# Database sizing. Not set in terraform.tfvars, so the defaults apply at deploy time.
variable "db_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 200
}

# Worker fleet
variable "worker_instance_type" {
  type    = string
  default = "m6g.large"
}

variable "worker_desired_capacity" {
  type    = number
  default = 2
}

variable "worker_root_volume_gb" {
  type    = number
  default = 50
}

# Cache
variable "cache_node_type" {
  type    = string
  default = "cache.r6g.large"
}

variable "cache_replicas" {
  type    = number
  default = 1
}

# Feature toggles
variable "enable_nat_gateway" {
  type    = bool
  default = true
}

variable "scratch_volume_count" {
  type    = number
  default = 2
}
