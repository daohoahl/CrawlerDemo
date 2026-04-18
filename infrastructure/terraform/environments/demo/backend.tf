terraform {
  backend "s3" {
    bucket       = "crawler-terraform-state-478111025341"
    key          = "demo/terraform.tfstate"
    region       = "ap-southeast-1"
    use_lockfile = true
    encrypt      = true
  }
}
