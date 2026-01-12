# Lambda Layers for Database Initialization

This directory contains the Lambda layers needed for database initialization functions.

## Building the Layers


```bash
mkdir -p python
pip install psycopg2-binary -t python/
```

### SQL Server Layer (pymssql)

```bash
cd lambda-layers/sqlserver
mkdir -p python
pip install pymssql -t python/
zip -r sqlserver-layer.zip python
```

### Alternative: Using Docker for Lambda-compatible builds

For better compatibility with Lambda's runtime environment:

```bash
docker run --rm -v "$PWD":/var/task public.ecr.aws/lambda/python:3.11 \

# SQL Server Layer
docker run --rm -v "$PWD":/var/task public.ecr.aws/lambda/python:3.11 \
  pip install pymssql -t /var/task/lambda-layers/sqlserver/python
```

## Note

The CDK stack will automatically create and reference these layers. Make sure to build them before deploying the stack.
