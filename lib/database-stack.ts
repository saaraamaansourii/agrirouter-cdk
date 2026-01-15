import * as cdk from 'aws-cdk-lib/core';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

interface DatabaseStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  databaseSecurityGroup: ec2.SecurityGroup;
}

export class DatabaseStack extends cdk.Stack {
  public readonly postgresCredentialsSecret: secretsmanager.Secret;
  public readonly postgresInstance: rds.DatabaseInstance;
  public readonly sqlServerCredentialsSecret: secretsmanager.Secret;
  public readonly sqlServerInstance: rds.DatabaseInstance;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    const { vpc, databaseSecurityGroup } = props;

    // Create master credentials for PostgreSQL (admin access)
    const postgresMasterSecret = new secretsmanager.Secret(this, 'PostgreSQLMasterCredentials', {
      secretName: 'postgres-master-credentials',
      description: 'PostgreSQL master/admin credentials',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          username: 'postgres_admin',
        }),
        generateStringKey: 'password',
        excludePunctuation: true,
        passwordLength: 32,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create master credentials for SQL Server (admin access)
    const sqlServerMasterSecret = new secretsmanager.Secret(this, 'SQLServerMasterCredentials', {
      secretName: 'sqlserver-master-credentials',
      description: 'SQL Server master/admin credentials',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          username: 'sqlserver_admin',
        }),
        generateStringKey: 'password',
        excludePunctuation: true,
        passwordLength: 32,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create application-specific credentials for PostgreSQL (limited access)
    this.postgresCredentialsSecret = new secretsmanager.Secret(this, 'PostgreSQLCredentials', {
      secretName: 'postgres-analytics-credentials',
      description: 'PostgreSQL credentials for analytics service',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          username: 'analytics_service',
          dbname: 'analytics_service_db',
          port: 5432,
        }),
        generateStringKey: 'password',
        excludePunctuation: true,
        passwordLength: 32,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create application-specific credentials for SQL Server (limited access)
    this.sqlServerCredentialsSecret = new secretsmanager.Secret(this, 'SQLServerCredentials', {
      secretName: 'sqlserver-analytics-credentials',
      description: 'SQL Server credentials for analytics service',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          username: 'analytics-service',
          dbname: 'analytics_service_db',
          port: 1433,
          tablename: 'EventMetricsDev',
        }),
        generateStringKey: 'password',
        excludePunctuation: true,
        passwordLength: 32,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create DB subnet group using PUBLIC subnets for internet access
    const dbSubnetGroup = new rds.SubnetGroup(this, 'DatabaseSubnetGroup', {
      vpc,
      description: 'Subnet group for RDS instances (publicly accessible)',
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC,
      },
    });

    // Create parameter group for PostgreSQL to allow non-SSL connections
    const postgresParameterGroup = new rds.ParameterGroup(this, 'PostgreSQLParameterGroup', {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      description: 'Parameter group to allow non-SSL connections',
      parameters: {
        'rds.force_ssl': '0',  // Allow non-SSL connections
      },
    });

    // PostgreSQL instance with minimal specs - PUBLICLY ACCESSIBLE
    this.postgresInstance = new rds.DatabaseInstance(this, 'PostgreSQLInstance', {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_16,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO), // Smallest instance
      vpc,
      subnetGroup: dbSubnetGroup,
      securityGroups: [databaseSecurityGroup],
      credentials: rds.Credentials.fromSecret(postgresMasterSecret), // Use master credentials for RDS instance
      databaseName: 'postgres', // Default postgres database - we'll create analytics_service_db separately
      allocatedStorage: 20, // Minimum allocated storage
      storageType: rds.StorageType.GP2,
      multiAz: false, // Single AZ for cost savings
      autoMinorVersionUpgrade: false,
      backupRetention: cdk.Duration.days(1), // Minimum backup retention
      deleteAutomatedBackups: true,
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      publiclyAccessible: true, // Enable public access
      parameterGroup: postgresParameterGroup,  // Use custom parameter group
    });

    // SQL Server Express instance with minimal specs - PUBLICLY ACCESSIBLE
    this.sqlServerInstance = new rds.DatabaseInstance(this, 'SQLServerInstance', {
      engine: rds.DatabaseInstanceEngine.sqlServerEx({
        version: rds.SqlServerEngineVersion.VER_15_00_4073_23_V1,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO), // Smallest instance
      vpc,
      subnetGroup: dbSubnetGroup,
      securityGroups: [databaseSecurityGroup],
      credentials: rds.Credentials.fromSecret(sqlServerMasterSecret), // Use master credentials for RDS instance
      // SQL Server Express creates a default database, we'll create our analytics DB separately
      licenseModel: rds.LicenseModel.LICENSE_INCLUDED, // Express edition includes license
      allocatedStorage: 20, // Minimum for SQL Server
      storageType: rds.StorageType.GP2,
      multiAz: false, // Single AZ for cost savings
      autoMinorVersionUpgrade: false,
      backupRetention: cdk.Duration.days(1), // Minimum backup retention
      deleteAutomatedBackups: true,
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      publiclyAccessible: true, // Enable public access
    });

    // Outputs
    new cdk.CfnOutput(this, 'PostgreSQLEndpoint', {
      value: this.postgresInstance.instanceEndpoint.hostname,
      description: 'PostgreSQL database endpoint',
      exportName: `${this.stackName}-PostgreSQLEndpoint`,
    });

    new cdk.CfnOutput(this, 'PostgreSQLPort', {
      value: this.postgresInstance.instanceEndpoint.port.toString(),
      description: 'PostgreSQL database port',
      exportName: `${this.stackName}-PostgreSQLPort`,
    });

    new cdk.CfnOutput(this, 'SQLServerEndpoint', {
      value: this.sqlServerInstance.instanceEndpoint.hostname,
      description: 'SQL Server database endpoint',
      exportName: `${this.stackName}-SQLServerEndpoint`,
    });

    new cdk.CfnOutput(this, 'SQLServerPort', {
      value: this.sqlServerInstance.instanceEndpoint.port.toString(),
      description: 'SQL Server database port',
      exportName: `${this.stackName}-SQLServerPort`,
    });

    new cdk.CfnOutput(this, 'PostgreSQLCredentialsSecretArn', {
      value: this.postgresCredentialsSecret.secretArn,
      description: 'PostgreSQL application credentials secret ARN (limited permissions)',
      exportName: `${this.stackName}-PostgreSQLCredentialsSecretArn`,
    });

    new cdk.CfnOutput(this, 'SQLServerCredentialsSecretArn', {
      value: this.sqlServerCredentialsSecret.secretArn,
      description: 'SQL Server application credentials secret ARN (limited permissions)',
      exportName: `${this.stackName}-SQLServerCredentialsSecretArn`,
    });

    new cdk.CfnOutput(this, 'PostgreSQLMasterSecretArn', {
      value: postgresMasterSecret.secretArn,
      description: 'PostgreSQL master/admin credentials secret ARN (full permissions)',
      exportName: `${this.stackName}-PostgreSQLMasterSecretArn`,
    });

    new cdk.CfnOutput(this, 'SQLServerMasterSecretArn', {
      value: sqlServerMasterSecret.secretArn,
      description: 'SQL Server master/admin credentials secret ARN (full permissions)',
      exportName: `${this.stackName}-SQLServerMasterSecretArn`,
    });

    // Cost estimation output
    new cdk.CfnOutput(this, 'EstimatedMonthlyCostPostgreSQL', {
      value: 'Approximately $12-15/month (t3.micro instance + 20GB GP2 storage)',
      description: 'Estimated monthly cost for PostgreSQL instance',
    });

    new cdk.CfnOutput(this, 'EstimatedMonthlyCostSQLServer', {
      value: 'Approximately $15-20/month (t3.micro instance + 20GB GP2 storage + Express license)',
      description: 'Estimated monthly cost for SQL Server Express instance',
    });

    new cdk.CfnOutput(this, 'TotalEstimatedMonthlyCost', {
      value: 'Approximately $27-35/month (both database instances + 4 secrets in Secrets Manager)',
      description: 'Total estimated monthly cost for database stack with secure credential separation',
    });

    new cdk.CfnOutput(this, 'SecurityNote', {
      value: 'Master credentials provide full admin access. Application credentials should be used for service connections with limited permissions.',
      description: 'Security best practice reminder',
    });

    new cdk.CfnOutput(this, 'PublicAccessWarning', {
      value: '⚠️ WARNING: Databases are PUBLICLY ACCESSIBLE from the internet. Ensure strong passwords and consider IP restrictions for production!',
      description: 'Public access security warning',
    });

    new cdk.CfnOutput(this, 'PostgreSQLSetupInstructions', {
      value: `
# PostgreSQL Setup Instructions:
# 1. Connect as postgres_admin to create database and user:
psql -h ${this.postgresInstance.instanceEndpoint.hostname} -U postgres_admin -d postgres

# 2. Create database:
CREATE DATABASE analytics_service_db;

# 3. Create user with password from analytics credentials secret:
CREATE USER analytics_service WITH PASSWORD 'get_from_secret';

# 4. Grant privileges:
GRANT ALL PRIVILEGES ON DATABASE analytics_service_db TO analytics_service;
\\c analytics_service_db
GRANT ALL ON SCHEMA public TO analytics_service;
GRANT ALL ON ALL TABLES IN SCHEMA public TO analytics_service;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO analytics_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO analytics_service;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO analytics_service;
      `.trim(),
      description: 'PostgreSQL database and user setup commands',
    });

    new cdk.CfnOutput(this, 'SQLServerSetupInstructions', {
      value: `
# SQL Server Setup Instructions:
# 1. Connect as sqlserver_admin:
sqlcmd -S ${this.sqlServerInstance.instanceEndpoint.hostname} -U sqlserver_admin -P 'get_from_secret'

# 2. Create database:
CREATE DATABASE [analytics_service_db];
GO

# 3. Create login and user:
CREATE LOGIN [analytics-service] WITH PASSWORD = 'get_from_secret';
GO
USE [analytics_service_db];
GO
CREATE USER [analytics-service] FOR LOGIN [analytics-service];
GO
ALTER ROLE db_owner ADD MEMBER [analytics-service];
GO

# 4. Create EventMetricsDev table:
CREATE TABLE [EventMetricsDev] (
    id INT IDENTITY(1,1) PRIMARY KEY,
    event_name NVARCHAR(255) NOT NULL,
    metric_value DECIMAL(18,2),
    timestamp DATETIME2 DEFAULT GETDATE(),
    metadata NVARCHAR(MAX)
);
GO
      `.trim(),
      description: 'SQL Server database, user, and table setup commands',
    });

    // Create Lambda layer for psycopg2 (PostgreSQL driver)
    const psycopg2Layer = new lambda.LayerVersion(this, 'Psycopg2Layer', {
      code: lambda.Code.fromAsset('lambda-layers/postgres', {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c',
            'pip install psycopg2-binary -t /asset-output/python'
          ],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'PostgreSQL psycopg2 driver for Lambda',
    });

    // Create Lambda layer for pymssql (SQL Server driver)
    const pymssqlLayer = new lambda.LayerVersion(this, 'PymssqlLayer', {
      code: lambda.Code.fromAsset('lambda-layers/sqlserver', {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c',
            'pip install pymssql -t /asset-output/python'
          ],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'SQL Server pymssql driver for Lambda',
    });

    // Create Lambda function to initialize PostgreSQL database and user
    // Uses PRIVATE_WITH_EGRESS subnets (with NAT Gateway) to access both RDS and Secrets Manager
    const postgresInitFunction = new lambda.Function(this, 'PostgresInitFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      vpc,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      },
      securityGroups: [databaseSecurityGroup],
      timeout: cdk.Duration.minutes(5),
      layers: [psycopg2Layer],
      code: lambda.Code.fromAsset('lambda-functions/postgres-init'),
      description: 'Initializes PostgreSQL service database and user',
      environment: {
        PYTHONUNBUFFERED: '1',
      },
    });

    // Grant Lambda permission to read secrets
    postgresMasterSecret.grantRead(postgresInitFunction);
    this.postgresCredentialsSecret.grantRead(postgresInitFunction);
    this.postgresCredentialsSecret.grantWrite(postgresInitFunction);

    // Create Lambda function to initialize SQL Server database and user
    // Uses PRIVATE_WITH_EGRESS subnets (with NAT Gateway) to access both RDS and Secrets Manager
    const sqlServerInitFunction = new lambda.Function(this, 'SqlServerInitFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      vpc,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
      },
      securityGroups: [databaseSecurityGroup],
      timeout: cdk.Duration.minutes(5),
      layers: [pymssqlLayer],
      code: lambda.Code.fromAsset('lambda-functions/sqlserver-init'),
      description: 'Initializes SQL Server service database, user, and table',
      environment: {
        PYTHONUNBUFFERED: '1',
      },
    });

    // Grant Lambda permission to read secrets
    sqlServerMasterSecret.grantRead(sqlServerInitFunction);
    this.sqlServerCredentialsSecret.grantRead(sqlServerInitFunction);
    this.sqlServerCredentialsSecret.grantWrite(sqlServerInitFunction);

    // Create custom resource provider for PostgreSQL initialization
    const postgresInitProvider = new cr.Provider(this, 'PostgresInitProvider', {
      onEventHandler: postgresInitFunction,
    });

    // Create custom resource for PostgreSQL initialization
    const postgresInit = new cdk.CustomResource(this, 'PostgresInit', {
      serviceToken: postgresInitProvider.serviceToken,
      properties: {
        MasterSecretArn: postgresMasterSecret.secretArn,
        ServiceSecretArn: this.postgresCredentialsSecret.secretArn,
        DatabaseHost: this.postgresInstance.instanceEndpoint.hostname,
        DatabasePort: '5432',
        // Add a timestamp to force updates when secrets change
        Timestamp: Date.now().toString(),
      },
    });

    // Ensure the database is created before initializing
    postgresInit.node.addDependency(this.postgresInstance);

    // Create custom resource provider for SQL Server initialization
    const sqlServerInitProvider = new cr.Provider(this, 'SqlServerInitProvider', {
      onEventHandler: sqlServerInitFunction,
    });

    // Create custom resource for SQL Server initialization
    const sqlServerInit = new cdk.CustomResource(this, 'SqlServerInit', {
      serviceToken: sqlServerInitProvider.serviceToken,
      properties: {
        MasterSecretArn: sqlServerMasterSecret.secretArn,
        ServiceSecretArn: this.sqlServerCredentialsSecret.secretArn,
        DatabaseHost: this.sqlServerInstance.instanceEndpoint.hostname,
        DatabasePort: '1433',
        // Add a timestamp to force updates when secrets change
        Timestamp: Date.now().toString(),
      },
    });

    // Ensure the database is created before initializing
    sqlServerInit.node.addDependency(this.sqlServerInstance);

    // Add outputs to indicate initialization status
    new cdk.CfnOutput(this, 'PostgresInitStatus', {
      value: 'Database and user initialized automatically',
      description: 'PostgreSQL database and service user creation status',
    });

    new cdk.CfnOutput(this, 'SqlServerInitStatus', {
      value: 'Database, user, and table initialized automatically',
      description: 'SQL Server database, service user, and table creation status',
    });
  }
}
