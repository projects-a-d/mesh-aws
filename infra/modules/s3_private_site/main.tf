resource "aws_s3_bucket" "site" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_website_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  index_document {
    suffix = "index.html"
  }
}

locals {
  site_files = fileset("../site", "**") # adjust path if needed
}

resource "aws_s3_object" "site_files" {
  for_each = { for file in local.site_files : file => file }

  bucket = aws_s3_bucket.site.id
  key    = each.value
  source = "../site/${each.value}"

  depends_on = [aws_s3_bucket_website_configuration.site]


  # Guess content type based on extension
  content_type = lookup(
    {
      html = "text/html"
      css  = "text/css"
      js   = "application/javascript"
      json = "application/json"
      png  = "image/png"
      jpg  = "image/jpeg"
      jpeg = "image/jpeg"
      gif  = "image/gif"
      svg  = "image/svg+xml"
    },
    regex("\\.([^.]+)$", each.value)[0],
    "binary/octet-stream"
  )

  etag = filemd5("../site/${each.value}")
}


resource "aws_s3_bucket_public_access_block" "site_private" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}


# resource "aws_s3_bucket_policy" "public_read" {
#   bucket = aws_s3_bucket.site.id
#   policy = jsonencode({
#     Version = "2012-10-17",
#     Statement = [{
#       Sid: "AllowPublicReadOfWebsite",
#       Effect: "Allow",
#       Principal = "*",
#       Action: "s3:GetObject",
#       Resource: "${aws_s3_bucket.site.arn}/*"
#     }]
#   })
#   depends_on = [aws_s3_bucket_public_access_block.site_public]
# }


