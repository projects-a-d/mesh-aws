resource "aws_s3_bucket" "site" {
  bucket = var.bucket_name
}

data "aws_s3_buckets" "all" {}