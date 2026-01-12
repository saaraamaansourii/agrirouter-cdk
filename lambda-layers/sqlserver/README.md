# SQL Server Lambda Layer

This directory serves as the bundling context for the SQL Server Lambda layer.

## Purpose

The layer is built during CDK synthesis using Docker bundling. The actual layer contents (pymssql) are installed via pip during the build process, not from files in this directory.

## How It Works

```typescript
lambda.Code.fromAsset('lambda-layers/sqlserver', {
  bundling: {
    image: lambda.Runtime.PYTHON_3_11.bundlingImage,
    command: ['bash', '-c', 'pip install pymssql -t /asset-output/python']
  }
})
```

The directory must exist (even if empty) to serve as the asset path, but the bundling command creates the layer contents from scratch.

## Note

This is a standard CDK pattern for creating Lambda layers with dependencies - the source directory is the bundling context, not the source of the layer files.
