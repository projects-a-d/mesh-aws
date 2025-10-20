variable "s3_bucket_name" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "s3_origin_domain_name" {
  type        = string
  description = "e.g., my-bucket.s3.us-east-1.amazonaws.com"
}

variable "default_root_object" {
  type    = string
  default = "index.html"
}
