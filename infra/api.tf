# Package the Lambda code from ../api into a zip at apply-time
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.root}/../api"
  output_path = "${path.root}/.build/api.zip"
}

# IAM role for Lambda
resource "aws_iam_role" "lambda_exec" {
  name               = "mesh-aws-api-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action = "sts:AssumeRole"
    }]
  })
}

# Basic logging permissions
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda function (Python 3.12 runtime)
resource "aws_lambda_function" "api" {
  function_name = "mesh-aws-api"
  role          = aws_iam_role.lambda_exec.arn
  runtime       = "python3.12"
  handler       = "app.handler"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      # later: put API base URLs, etc.
    }
  }
}

# HTTP API (API Gateway v2)
resource "aws_apigatewayv2_api" "http_api" {
  name          = "mesh-aws-http-api"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["content-type", "authorization"]
  }
}

# Integrate API with Lambda (proxy)
resource "aws_apigatewayv2_integration" "lambda_proxy" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.arn
  integration_method     = "POST"
  payload_format_version = "2.0"
}

# Routes → all to the same Lambda (simple)
resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_route" "link_token" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "POST /mesh/link-token"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_route" "pay" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "POST /mesh/pay"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_route" "portfolio" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "GET /mesh/portfolio"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

# Use the $default stage so the base URL has NO /stage suffix
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "$default"
  auto_deploy = true
}

# Allow API Gateway to invoke the Lambda
resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}

# Outputs
output "api_invoke_url" {
  value       = aws_apigatewayv2_api.http_api.api_endpoint
  description = "Base URL for your API (no stage suffix with $default)"
}

output "api_id" {
    value = aws_apigatewayv2_api.http_api.id
}

# Catch-all (forward anything to the Lambda)
resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

# Also match ANY / and ANY /{proxy+} for good measure
resource "aws_apigatewayv2_route" "any_root" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_route" "any_proxy" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}
