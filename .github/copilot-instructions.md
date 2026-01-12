# GitHub Copilot Agent Context

## Project Overview

This is an AWS CDK TypeScript project for deploying an analytics infrastructure with:
- MSK Serverless (Kafka)
- ECS Fargate service
- Lambda functions for database initialization
- VPC with public and private subnets

**Account:** 592579839809  
**Region:** eu-central-1  
**AWS Profile:** dke-thdeg-admin

## Critical Rules

### 1. TypeScript Build Commands

**NEVER** run `npm run build` or `tsc` without the `--noEmit` flag.

```bash
# ✅ CORRECT
npx tsc --noEmit

# ❌ WRONG
npm run build
tsc
```

### 2. AWS Deployment

**ALWAYS** set the AWS profile before deploying:

```bash
export AWS_PROFILE=dke-thdeg-admin
npx cdk deploy StackName
```

### 3. Stack Dependencies

The stacks have dependencies that must be respected:

```
ComputeStack (base)
├── KafkaStack
├── DatabaseStack
└── ServiceStack (depends on Kafka + Database)
```

**Important:** When updating ComputeStack security groups, you must:
1. Delete dependent stacks first (KafkaStack, ServiceStack)
2. Update ComputeStack
3. Redeploy dependent stacks

### 4. Database Configuration

- **SQL Server Version:** `rds.SqlServerEngineVersion.VER_15_00_4073_23_V1`
- **Public Access:** Both databases are configured with `publiclyAccessible: true`
- **Subnets:** Databases use PUBLIC subnets
- **Security:** Master credentials separate from service credentials

### 5. Lambda Functions

Lambda functions use PRIVATE subnets with NAT Gateway for internet/AWS service access:

```typescript
{
  vpcSubnets: {
    subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,  // ← Uses NAT Gateway
  },
  securityGroups: [databaseSecurityGroup],  // ← Access to RDS
}
```

**Important:** Lambda in PUBLIC subnets cannot access internet or AWS services without NAT!

### 6. Lambda Function Structure

Lambda functions are in separate directories:
- `lambda-functions/sqlserver-init/` - SQL Server initialization

Each contains:
- `index.py` - Main handler
- `cfnresponse.py` - CloudFormation response helper (REQUIRED)
- `requirements.txt` - Dependencies documentation

**Never use inline Lambda code** - always use `lambda.Code.fromAsset()`.

### 7. Lambda Layers

Lambda layers are auto-bundled by CDK:
- `lambda-layers/sqlserver/` - pymssql layer

Bundling command pattern:
```typescript
  bundling: {
    image: lambda.Runtime.PYTHON_3_11.bundlingImage,
    command: [
      'bash', '-c',
      'pip install psycopg2-binary -t /asset-output/python'
    ],
  },
})
```

**Do NOT** add `&& cp -r /asset-output/python /asset-output/` (causes error).

### 8. Security Groups

Current configuration (PUBLIC ACCESS):

```typescript
// Database Security Group
ec2.Peer.anyIpv4()  // Allows internet access
ec2.Port.tcp(1433)  // SQL Server

// Kafka Security Group
ec2.Peer.anyIpv4()  // Allows internet access
ec2.Port.tcp(9098)  // IAM authentication
ec2.Port.tcp(9096)  // SASL/SCRAM
ec2.Port.tcp(9094)  // TLS
```

### 9. Secrets Management

Four secrets are created:
- `sqlserver-master-credentials` - Admin access (DO NOT use in applications)
- `sqlserver-analytics-credentials` - Service access (use in applications)

Service secrets are automatically updated by Lambda with connection details (host, port, engine).

### 10. Database Initialization

Initialization is automatic via Lambda Custom Resources:
- Creates service databases (`analytics_service_db`)
- Creates service users with limited permissions
- Updates service secrets with connection info
- Runs on stack deployment

### 11. Cost Optimization

Current configuration is cost-optimized:
- t3.micro instances (smallest)
- Single AZ (no multi-AZ)
- 20GB storage (minimum)
- Containerized Kafka on ECS Fargate (instead of expensive MSK)
- 1-day backup retention

**Estimated cost:** ~$27-35/month for databases + ~$28-32/month for Kafka container.

### 11a. Kafka Container Configuration

**DO NOT use Bitnami images** - they have changed their product policy and may have licensing/availability issues.

Instead use Apache Kafka official images:
- `apache/kafka:latest` for Kafka (supports KRaft mode, no ZooKeeper needed)
- Or `wurstmeister/kafka` + `wurstmeister/zookeeper` for traditional setup

Current Kafka setup:
- Runs on ECS Fargate with x86_64 architecture
- Uses Network Load Balancer for public access with stable DNS
- SASL/PLAIN authentication for security
- EFS for data persistence
- Single instance for cost optimization

### 12. Python Code Style

In Lambda functions:
- Use visual indicators in logs: ✓ (success), ℹ (info), ✗ (error)
- Include comprehensive docstrings
- Always handle CloudFormation Delete events gracefully
- Include traceback in error messages

### 13. CloudFormation Custom Resources

When using Custom Resources:
- Always check `event['RequestType']`
- Return success on Delete to prevent rollback issues
- Include detailed logging
- Use proper error handling with cfnresponse

### 14. File Organization

```
├── bin/                          # CDK app entry point
├── lib/                          # Stack definitions
│   ├── compute-stack.ts         # VPC, Security Groups, ECS, ECR
│   ├── database-stack.ts        # RDS instances, Lambda init
│   ├── kafka-stack.ts           # MSK Serverless
│   └── service-stack.ts         # ECS service
├── lambda-functions/            # Lambda source code
│   └── sqlserver-init/
├── lambda-layers/               # Lambda layer bundling
├── scripts/                     # Utility scripts
└── *.md                        # Documentation
```

### 15. Documentation Files

Keep documentation up to date.
If there are changes relevant to AI agents, put them in .github/copilot-instructions.md.

### 16. Testing

After deployment, validate with:
```bash
# Activate the virtual environment
source scripts/venv/bin/activate

# Run validation scripts
python3 scripts/validate-db-connections.py
python3 scripts/validate-kafka-connection.py
```

**Important:** Always use the virtual environment at `scripts/venv` to run validation scripts.

Dependencies are already installed in the venv:
- `pymssql` - SQL Server client
- `boto3` - AWS SDK
- `kafka-python` - Kafka client

### 17. Common Issues


**Issue:** "Lambda Functions in a public subnet can NOT access the internet"  
**Solution:** Add `allowPublicSubnet: true`

**Issue:** "No module named 'cfnresponse'"  
**Solution:** Include `cfnresponse.py` in Lambda function directory

**Issue:** "Cannot update export ... as it is in use"  
**Solution:** Delete dependent stacks first, update, then redeploy

### 18. Security Warnings

⚠️ **Current configuration has databases and Kafka publicly accessible.**

This is for development/testing. For production:
- Consider IP whitelisting
- Use VPC endpoints
- Enable CloudTrail logging
- Implement WAF rules
- Use Secrets rotation

### 19. Git Best Practices

- Commit Lambda functions separately from CDK code
- Keep documentation in sync with code changes
- Tag releases with cost estimates
- Include deployment instructions in README

### 20. CDK Best Practices

- Always use `removalPolicy: cdk.RemovalPolicy.DESTROY` for dev resources
- Export only what's necessary (avoid export conflicts)
- Use explicit dependencies with `addDependency()`
- Include cost estimation outputs
- Add descriptive CloudFormation outputs

## Quick Commands

```bash
# ALWAYS set this first to disable pagers
export PAGER=

# Type check
npx tsc --noEmit

# Deploy single stack
export AWS_PROFILE=dke-thdeg-admin
npx cdk deploy DatabaseStack

# Deploy all stacks
npx cdk deploy --all

# Destroy stack
npx cdk destroy StackName --force

# Synthesize (dry run)
npx cdk synth

# Check differences
npx cdk diff

# Check CloudWatch logs (example)
aws logs get-log-events --log-group-name "/aws/lambda/FunctionName" --log-stream-name "stream" --query 'events[*].message' --output text
```

## Environment Variables

```bash
export AWS_PROFILE=dke-thdeg-admin
export AWS_REGION=eu-central-1
export AWS_ACCOUNT=592579839809
export PAGER=  # Disable pager for CLI commands to read output directly
```

**Important:** Always disable the pager when running AWS CLI or other commands that use pagers (git, etc.) to ensure output is readable in terminals.

---

**Last Updated:** November 4, 2025

**Project Type:** AWS CDK Infrastructure as Code (TypeScript)

**Primary Purpose:** Analytics infrastructure with databases and message streaming
