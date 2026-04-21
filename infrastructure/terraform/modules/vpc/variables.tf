variable "project" {
  description = "Project name prefix"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
}

variable "aws_region" {
  description = "AWS Region"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Must contain >= 2 AZs (spec: EC2 ASG spans >= 2 AZs)."
  type        = list(string)
  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "availability_zones must contain at least 2 AZs."
  }
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (same length as availability_zones)"
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (ASG worker + Lambda)"
  type        = list(string)
}

variable "db_subnet_cidrs" {
  description = "CIDR blocks for RDS subnets"
  type        = list(string)
}

variable "common_tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
