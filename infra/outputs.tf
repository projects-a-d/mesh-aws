output "bucket_name" {
  value       = module.s3_private_site.bucket_name
  description = "Name of the created S3 bucket"
}

output "all_bucket_names" {
  value = data.aws_s3_buckets.all.names
}
