module "s3_private_site" {
  source = "./modules/s3_private_site"
}

module "cloudfront_oac" {
  source                = "./modules/cloudfront_oac"
  s3_bucket_name        = module.s3_private_site.bucket_name
  s3_bucket_arn         = module.s3_private_site.bucket_arn
  s3_origin_domain_name = module.s3_private_site.bucket_regional_domain_name
  default_root_object   = "index.html"
}