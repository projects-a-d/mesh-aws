module "s3_private_site" {
  source = "./modules/s3_private_site"
}

data "aws_s3_buckets" "all" {}
