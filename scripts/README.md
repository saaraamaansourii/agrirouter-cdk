# Validation Scripts

This directory contains validation scripts to test the deployed AWS infrastructure components.

## Prerequisites

### System Requirements

- **Python 3.9+** installed on your development machine
- **AWS CLI** configured with valid credentials
- **AWS Profile**: `dke-thdeg-admin` configured with appropriate IAM permissions
- **Network Access**: Ability to connect to public endpoints (databases and Kafka are publicly accessible)

### Required IAM Permissions

Your AWS credentials must have permissions to:
- Read secrets from AWS Secrets Manager (`secretsmanager:GetSecretValue`)
- Describe CloudFormation stacks (`cloudformation:DescribeStacks`)
- Connect to RDS databases (network access)
- Connect to Kafka service (network access)

### AWS Profile Setup

Ensure your AWS profile is configured:

```bash
# Set the AWS profile
export AWS_PROFILE=dke-thdeg-admin
export AWS_REGION=eu-central-1

# Verify profile is working
aws sts get-caller-identity
```

## Installation

### 1. Create Python Virtual Environment

```bash
# From the project root directory
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate     # Windows
```

### 2. Install Dependencies

```bash
# Install all required packages
pip install -r scripts/requirements.txt
```

This will install:
- **boto3**: AWS SDK for Python (retrieve credentials and stack outputs)
- **pymssql**: SQL Server database driver
- **kafka-python**: Apache Kafka Python client

## Scripts Overview

### 1. `publish-kafka-messages.py`

**Purpose**: Publishes simulated Kafka messages for testing the analytics service based on protobuf definitions.

**Message Types Supported**:
- ✓ **RoutedMessageEvent** (topics: `routed_message_delivered.event`, `message_command_sent.event`)
- ✓ **Endpoint** (topic: `endpoint.state`)
- ✓ **Application** (topic: `application.state`)

**What it does**:
- ✓ Retrieves Kafka credentials from AWS Secrets Manager or uses local config
- ✓ Generates realistic protobuf-based messages with random but valid data
- ✓ Sends messages to appropriate topics with configurable intervals
- ✓ Includes proper error handling and progress reporting
- ✓ Supports both AWS-deployed and local Kafka clusters

**Usage**:

```bash
# Ensure AWS profile is set (for AWS-deployed Kafka)
export AWS_PROFILE=dke-thdeg-admin

# Activate virtual environment
source scripts/venv/bin/activate

# Basic usage - send 10 messages per topic
python3 scripts/publish-kafka-messages.py

# Send specific number of messages with custom interval
python3 scripts/publish-kafka-messages.py --count 20 --interval 2.0

# Focus on specific topic
python3 scripts/publish-kafka-messages.py --topic routed_message_delivered.event --count 50

# Use local Kafka (no AWS credentials needed)
python3 scripts/publish-kafka-messages.py --local --count 5

# Available topics:
# - routed_message_delivered.event
# - message_command_sent.event  
# - endpoint.state
# - application.state
# - all (default - sends to all topics)
```

### 2. `consume-kafka-messages.py`

**Purpose**: Consumes and displays Kafka messages from the analytics topics, with protobuf deserialization.

**What it does**:
- ✓ Retrieves Kafka credentials from AWS Secrets Manager or uses local config
- ✓ Subscribes to one or all analytics topics
- ✓ Deserializes protobuf messages and displays them in human-readable or JSON format
- ✓ Supports consuming from beginning or latest offset
- ✓ Graceful shutdown with Ctrl+C
- ✓ Configurable timeout and consumer group

**Usage**:

```bash
# Ensure AWS profile is set (for AWS-deployed Kafka)
export AWS_PROFILE=dke-thdeg-admin

# Activate virtual environment
source scripts/venv/bin/activate

# Consume from all topics (default 30s timeout)
python3 scripts/consume-kafka-messages.py

# Consume from specific topic
python3 scripts/consume-kafka-messages.py --topic endpoint.state

# Start from beginning of topic
python3 scripts/consume-kafka-messages.py --from-beginning

# Run for longer duration
python3 scripts/consume-kafka-messages.py --timeout 120

# Output as JSON (useful for piping to other tools)
python3 scripts/consume-kafka-messages.py --json

# Use local Kafka (no AWS credentials needed)
python3 scripts/consume-kafka-messages.py --local

# Custom consumer group
python3 scripts/consume-kafka-messages.py --group my-test-consumer
```

**Example Output** (human-readable):
```
┌─ endpoint.state (partition=1, offset=42)
│  Time: 2025-12-15T14:30:45.123456
│  Reason: endpoint_registered
│  Endpoint ID: 6ba7b813-9dad-11d1-80b4-00c04fd430c8
│  Name: John Deere 8R 410 - Unit 42
│  Type: COMMUNICATION_UNIT
│  Gateway: MQTT
│  Deactivated: False
└─
```

### 3. `example-simulations.py`

**Purpose**: Demonstrates different simulation scenarios and provides ready-to-run examples.

**Usage**:
```bash
# Run predefined example scenarios
python3 scripts/example-simulations.py
```

This script runs several test scenarios:
- Quick test with 3 messages per topic
- Focus test on routed message events
- Endpoint state change simulation
- Application state change simulation

### 4. `update-db-passwords.py`

**Purpose**: Manually updates database service user passwords after secret rotation in AWS Secrets Manager.

**What it does**:
- ✓ Retrieves master/admin credentials from AWS Secrets Manager
- ✓ Retrieves new service credentials from AWS Secrets Manager
- ✓ Connects to SQL Server using master credentials
- ✓ Updates SQL Server login password with ALTER LOGIN
- ✓ Creates users/grants permissions if they don't exist

**Usage**:

```bash
# Ensure AWS profile is set
export AWS_PROFILE=dke-thdeg-admin

# Activate virtual environment
source .venv/bin/activate

# Run the password update
python3 scripts/update-db-passwords.py
```

**When to use**:
- After rotating secrets in Secrets Manager
- When service credentials are out of sync with database passwords
- After deploying updated DatabaseStack with new secrets

### 5. `validate-db-connections.py`


**What it tests**:
- ✓ Retrieves service credentials from AWS Secrets Manager
- ✓ Connects to SQL Server database using service account
- ✓ Verifies SQL Server table existence and permissions
- ✓ Tests SQL Server operations (INSERT, SELECT, DELETE)

**Usage**:

```bash
# Ensure AWS profile is set
export AWS_PROFILE=dke-thdeg-admin

# Activate virtual environment
source .venv/bin/activate

# Run the validation
python3 scripts/validate-db-connections.py
```

### 6. `validate-kafka-connection.py`

**Purpose**: Validates connectivity, authentication, and functionality of the Kafka service running on ECS Fargate.

**What it tests**:
- ✓ Retrieves Kafka credentials from AWS Secrets Manager
- ✓ Retrieves Kafka bootstrap servers from CloudFormation stack outputs
- ✓ Tests connection to Kafka cluster with SASL/PLAIN authentication
- ✓ Lists existing topics
- ✓ Creates a test topic with multiple partitions
- ✓ Produces test messages to the topic
- ✓ Consumes messages from the topic
- ✓ Validates message integrity (all messages received)
- ✓ Tests write/read performance (100 messages)
- ✓ Cleans up test topics

**Usage**:

```bash
# Ensure AWS profile is set
export AWS_PROFILE=dke-thdeg-admin

# Activate virtual environment
source .venv/bin/activate

# Run the validation
python3 scripts/validate-kafka-connection.py
```

## Troubleshooting

### Common Issues

#### 1. AWS Authentication Errors

**Error**: `Unable to locate credentials` or `NoCredentialsError`

**Solution**:
```bash
# Verify AWS profile is set
echo $AWS_PROFILE

# Set it if not configured
export AWS_PROFILE=dke-thdeg-admin

# Test credentials
aws sts get-caller-identity
```

#### 2. Module Import Errors

**Error**: `ModuleNotFoundError: No module named 'psycopg2'` or similar

**Solution**:
```bash
# Ensure virtual environment is activated
source .venv/bin/activate

# Reinstall dependencies
pip install -r scripts/requirements.txt
```

#### 3. Connection Timeout

**Error**: `Connection timed out` or `Unable to connect`

**Solutions**:
- Verify the CDK stacks are deployed: `npx cdk list`
- Check security groups allow your IP (databases and Kafka are configured for public access)
- Ensure NLB and RDS instances are running in AWS Console
- Check CloudWatch logs for service issues

#### 4. Secret Not Found

**Error**: `SecretNotFoundException` or `ResourceNotFoundException`

**Solution**:
- Verify the DatabaseStack is deployed: `aws cloudformation describe-stacks --stack-name DatabaseStack`
- Verify the KafkaStack is deployed: `aws cloudformation describe-stacks --stack-name KafkaStack`
- Check Secrets Manager for the secrets:
  ```bash
  aws secretsmanager list-secrets
  ```

#### 5. Kafka IncompatibleBrokerVersion

**Error**: `IncompatibleBrokerVersion` or API version mismatch

**Solution**: The scripts use `api_version=(3, 6, 0)` which should work with Apache Kafka. If you encounter issues:
- Check Kafka container logs: `aws logs tail /ecs/kafka-container --follow`
- Verify Kafka is fully started (look for "Kafka Server started" message)
- Wait 30 seconds after deployment before running validation

## Integration with CI/CD

These scripts can be integrated into your CI/CD pipeline for automated validation:

```bash
#!/bin/bash
set -e

# Set AWS credentials
export AWS_PROFILE=dke-thdeg-admin
export AWS_REGION=eu-central-1

# Activate virtual environment
source .venv/bin/activate

# Run validations
echo "Validating database connections..."
python3 scripts/validate-db-connections.py

echo "Validating Kafka service..."
python3 scripts/validate-kafka-connection.py

echo "✓ All validations passed!"
```

## Connection Details

- **Port**: 5432
- **Database**: `analytics_service_db`
- **Username**: `analytics_service`
- **Password**: Stored in Secrets Manager

### SQL Server
- **Host**: Retrieved from `sqlserver-analytics-credentials` secret
- **Port**: 1433
- **Database**: `analytics_service_db`
- **Username**: `analytics_service`
- **Password**: Stored in Secrets Manager

### Kafka
- **Bootstrap Servers**: Retrieved from KafkaStack CloudFormation outputs
- **Security Protocol**: SASL_PLAINTEXT
- **SASL Mechanism**: SASL_PLAIN
- **Username**: `analytics_service`
- **Password**: Stored in `kafka-credentials` secret
- **Consumer Group**: `agrirouter-analytics-group`

## Security Notes

⚠️ **Important**: These services are currently configured with **public access** for PoC/development purposes:
- RDS instances have `publiclyAccessible: true`
- Kafka is exposed via Network Load Balancer on the internet
- All services use authentication (credentials in Secrets Manager)

**For production deployments**, consider:
- IP whitelisting in security groups
- VPC peering or VPN for private access
- AWS PrivateLink for service endpoints
- Secrets rotation policies
- Enhanced monitoring and alerting

## Support

For issues or questions:
1. Check CloudWatch Logs for service-level issues
2. Review security group configurations
3. Verify IAM permissions
4. Check the main project README.md for deployment instructions
