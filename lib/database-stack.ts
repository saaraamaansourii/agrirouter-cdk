import * as cdk from 'aws-cdk-lib';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';

interface DatabaseStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  databaseSecurityGroup: ec2.SecurityGroup;
}

export class DatabaseStack extends cdk.Stack {
  public readonly sqlServerCredentialsSecret: secretsmanager.Secret;
  public readonly sqlServerInstance: rds.DatabaseInstance;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    const { vpc, databaseSecurityGroup } = props;

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

    // SQL Server Express instance with minimal specs - PUBLICLY ACCESSIBLE
    this.sqlServerInstance = new rds.DatabaseInstance(this, 'SQLServerInstance', {
      engine: rds.DatabaseInstanceEngine.sqlServerEx({
        version: rds.SqlServerEngineVersion.VER_15_00_4073_23_V1,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
      vpc,
      subnetGroup: dbSubnetGroup,
      securityGroups: [databaseSecurityGroup],
      credentials: rds.Credentials.fromSecret(sqlServerMasterSecret),
      licenseModel: rds.LicenseModel.LICENSE_INCLUDED,
      allocatedStorage: 20,
      storageType: rds.StorageType.GP2,
      multiAz: false,
      autoMinorVersionUpgrade: false,
      backupRetention: cdk.Duration.days(1),
      deleteAutomatedBackups: true,
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      publiclyAccessible: true,
    });

    // Outputs
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

    new cdk.CfnOutput(this, 'SQLServerCredentialsSecretArn', {
      value: this.sqlServerCredentialsSecret.secretArn,
      description: 'SQL Server application credentials secret ARN (limited permissions)',
      exportName: `${this.stackName}-SQLServerCredentialsSecretArn`,
    });

    new cdk.CfnOutput(this, 'SQLServerMasterSecretArn', {
      value: sqlServerMasterSecret.secretArn,
      description: 'SQL Server master/admin credentials secret ARN (full permissions)',
      exportName: `${this.stackName}-SQLServerMasterSecretArn`,
    });

    // Cost estimation output
    new cdk.CfnOutput(this, 'EstimatedMonthlyCostSQLServer', {
      value: 'Approximately $15-20/month (t3.micro instance + 20GB GP2 storage + Express license)',
      description: 'Estimated monthly cost for SQL Server Express instance',
    });

    new cdk.CfnOutput(this, 'SecurityNote', {
      value: 'Master credentials provide full admin access. Application credentials should be used for service connections with limited permissions.',
      description: 'Security best practice reminder',
    });

    new cdk.CfnOutput(this, 'PublicAccessWarning', {
      value: '⚠️ WARNING: Database is PUBLICLY ACCESSIBLE from the internet. Ensure strong passwords and consider IP restrictions for production!',
      description: 'Public access security warning',
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

    // Create Lambda layer for pymssql (SQL Server driver)
    const pymssqlLayer = new lambda.LayerVersion(this, 'PymssqlLayer', {
      code: lambda.Code.fromAsset('lambda-layers/sqlserver', {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: ['bash', '-c', 'pip install pymssql -t /asset-output/python'],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'SQL Server pymssql driver for Lambda',
    });

    // Create Lambda function to initialize SQL Server database and user
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
        Timestamp: Date.now().toString(),
      },
    });

    // Ensure the database is created before initializing
    sqlServerInit.node.addDependency(this.sqlServerInstance);

    // Add output to indicate initialization status
    new cdk.CfnOutput(this, 'SqlServerInitStatus', {
      value: 'Database, user, and table initialized automatically',
      description: 'SQL Server database, service user, and table creation status',
    });
  }
}
