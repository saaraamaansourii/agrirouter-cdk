# Lambda Functions for Database Initialization

This directory contains Lambda functions that are deployed as part of the database stack to automatically initialize databases and users.

## Structure

```
lambda-functions/
└── sqlserver-init/
    └── index.py          # SQL Server initialization Lambda
```

## Functions



**Operations**:
1. Connects to RDS using master credentials
2. Creates service database (`analytics_service_db`)
3. Creates service user (`analytics_service`)
4. Grants all privileges on database and schema
5. Updates service secret with connection details

**Dependencies**: 
- `psycopg2-binary` (provided via Lambda Layer)
- `boto3` (included in Lambda runtime)

**Handler**: `index.handler`

### sqlserver-init

**Purpose**: Initializes SQL Server service database, user, and table

**Operations**:
1. Connects to RDS using master credentials
2. Creates service database (`analytics_service_db`)
3. Creates service login and user (`analytics-service`)
4. Grants `db_owner` role
5. Creates `EventMetricsDev` table
6. Updates service secret with connection details

**Dependencies**:
- `pymssql` (provided via Lambda Layer)
- `boto3` (included in Lambda runtime)

**Handler**: `index.handler`

## How They're Used

These functions are invoked by CloudFormation Custom Resources during stack deployment:

1. **Stack Create/Update**: Functions initialize databases and users
2. **Stack Delete**: Functions do nothing (to prevent data loss)

## CloudFormation Custom Resource Integration

The CDK stack (`lib/database-stack.ts`) creates:
- Lambda Functions with VPC access
- Lambda Layers with database drivers
- Custom Resource Providers
- Custom Resources that invoke the functions

## Error Handling

- Functions log detailed information to CloudWatch Logs
- Errors are reported back to CloudFormation
- Stack creation fails if initialization fails
- Timeout is set to 5 minutes

## Idempotency

Functions are idempotent:
- Check if resources exist before creating
- Update passwords if user/login already exists
- Safe to re-run multiple times

## Testing Locally

To test these functions locally, you'll need:

```bash
# Install dependencies
pip install psycopg2-binary pymssql boto3

# Set environment variables
export AWS_REGION=us-east-1
export AWS_PROFILE=your-profile

# Create a test event
cat > test-event.json << 'EOF'
{
  "RequestType": "Create",
  "ResourceProperties": {
    "MasterSecretArn": "arn:aws:secretsmanager:...",
    "ServiceSecretArn": "arn:aws:secretsmanager:...",
    "DatabaseHost": "your-db.rds.amazonaws.com",
    "DatabasePort": "5432"
  }
}
EOF

# Run locally (ensure you have access to the VPC)
```

## Security Considerations

1. **VPC Execution**: Functions run in VPC isolated subnets
2. **Security Groups**: Same security group as RDS instances
3. **IAM Permissions**: 
   - Read access to master secret
   - Read/Write access to service secret
4. **Network**: No internet access required (uses VPC endpoints)

## Monitoring

Check function execution in:
- **CloudWatch Logs**: `/aws/lambda/DatabaseStack-SqlServerInitFunction-*`
- **CloudFormation Events**: Custom Resource execution status

## Maintenance

### Updating Function Code

1. Edit `index.py` in the appropriate directory
2. Run `npm run build` (if TypeScript changes in CDK)
3. Deploy: `cdk deploy DatabaseStack`

### Rotating Passwords

The functions automatically update passwords when:
1. Secret value changes in Secrets Manager
2. Stack is updated (Custom Resource re-invoked)

### Adding New Initialization Logic

Follow this pattern:
1. Create new directory: `lambda-functions/new-db-init/`
2. Add `index.py` with handler function
3. Update `database-stack.ts` to reference new function
4. Create Lambda Layer if new dependencies needed
