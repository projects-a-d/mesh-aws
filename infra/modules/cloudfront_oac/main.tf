data "aws_caller_identity" "me" {}

resource "aws_cloudfront_origin_access_control" "oac" {
  name                              = "${var.s3_bucket_name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "cdn" {
  enabled             = true
  default_root_object = var.default_root_object

  origin {
    domain_name              = var.s3_origin_domain_name
    origin_id                = "s3-origin-${var.s3_bucket_name}"
    origin_access_control_id = aws_cloudfront_origin_access_control.oac.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-origin-${var.s3_bucket_name}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]

    # AWS Managed cache policy: "CachingOptimized"
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Allow ONLY this CloudFront distribution to read objects from the bucket
resource "aws_s3_bucket_policy" "allow_cf_only" {
  bucket = var.s3_bucket_name

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Sid: "AllowCloudFrontRead",
      Effect: "Allow",

      # CloudFront service principal (not public)
      Principal = { "Service": "cloudfront.amazonaws.com" },

      # Only read objects
      Action = ["s3:GetObject"],

      # Every object in the bucket
      Resource = "${var.s3_bucket_arn}/*",

      # Lock it to *this* distribution (prevents any other CF dist from reading)
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = "arn:aws:cloudfront::${data.aws_caller_identity.me.account_id}:distribution/${aws_cloudfront_distribution.cdn.id}"
        }
      }
    }]
  })
}
