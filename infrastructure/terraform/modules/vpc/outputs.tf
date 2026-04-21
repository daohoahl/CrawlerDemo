output "vpc_id" {
  value       = aws_vpc.main.id
  description = "VPC ID"
}

output "vpc_cidr" {
  value       = aws_vpc.main.cidr_block
  description = "VPC CIDR block"
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "Public subnet IDs"
}

output "private_subnet_ids" {
  value       = aws_subnet.private[*].id
  description = "Private subnet IDs (ASG worker + Lambda)"
}

output "db_subnet_ids" {
  value       = aws_subnet.db[*].id
  description = "DB subnet IDs (RDS)"
}

output "nat_gateway_ip" {
  value       = aws_eip.nat.public_ip
  description = "Public IP of the NAT Gateway (whitelist this on crawl targets)"
}
