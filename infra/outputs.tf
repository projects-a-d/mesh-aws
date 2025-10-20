output "bucket_name" {
  value       = module.s3_private_site.bucket_name
  description = "Name of the created S3 bucket"
}

output "website_endpoint" {
  value       = module.s3_private_site.website_endpoint
  description = "Open this URL to view the site"
}
