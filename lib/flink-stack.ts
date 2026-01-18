import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as kinesisanalyticsv2 from 'aws-cdk-lib/aws-kinesisanalyticsv2';
import { Construct } from 'constructs';
import { ArnFormat } from 'aws-cdk-lib';

interface FlinkStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  flinkSecurityGroup: ec2.SecurityGroup;

  // Kafka
  kafkaCredentialsSecret: secretsmanager.Secret;
  kafkaBootstrapServers: string;

  // PostgreSQL
  postgresCredentialsSecret: secretsmanager.Secret;
  postgresEndpoint: string;
  postgresPort: string;

  // SQL Server
  sqlServerCredentialsSecret: secretsmanager.Secret;
  sqlServerEndpoint: string;
  sqlServerPort: string;
}

/**
 * Amazon Managed Service for Apache Flink (Kinesis Data Analytics v2) stack.
 *
 * Notes:
 * - This stack only provisions the Flink application + its IAM role + networking.
 * - The Flink job artifact is uploaded to a dedicated S3 bucket by CDK from `flink-app/app.zip`.
 * - The Flink application reads configuration (Kafka + SQL Server connection info) from property groups.
 */
export class FlinkStack extends cdk.Stack {
  public readonly flinkApplicationName: string;
  public readonly artifactBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: FlinkStackProps) {
    super(scope, id, props);

    const {
      vpc,
      flinkSecurityGroup,
      kafkaCredentialsSecret,
      kafkaBootstrapServers,
      sqlServerCredentialsSecret,
      sqlServerEndpoint,
      sqlServerPort,
      postgresCredentialsSecret,
      postgresEndpoint,
      postgresPort
    } = props;

    // --- Logs ---
    const logGroup = new logs.LogGroup(this, 'FlinkAppLogGroup', {
      logGroupName: '/aws/kinesis-analytics/agrirouter-analytics-flink',
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const logStream = new logs.LogStream(this, 'FlinkAppLogStream', {
      logGroup,
      logStreamName: 'application',
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // --- Artifact bucket (S3) ---
    // Amazon Managed Service for Apache Flink loads your application artifact from S3.
    // We create a dedicated bucket and (for dev convenience) upload `flink-app/app.zip` into it.
    const artifactBucket = new s3.Bucket(this, 'FlinkArtifactsBucket', {
      versioned: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      // NOTE: For production, consider RETAIN and manage lifecycle rules carefully.
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        {
          noncurrentVersionExpiration: cdk.Duration.days(30),
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(7),
        },
      ],
    });

    const artifactKey = 'artifacts/agri_flinkjob.zip';

    // Upload local artifact (ZIPFILE) into the dedicated bucket at a stable key.
    // This makes updates predictable: replace `flink-app/app.zip` and redeploy.
    const deployFlinkArtifact = new s3deploy.BucketDeployment(this, 'DeployFlinkArtifact', {
      destinationBucket: artifactBucket,
      destinationKeyPrefix: 'artifacts',
      sources: [s3deploy.Source.asset('flink-app')],
      prune: false,
    });

    // --- IAM role for the Flink application ---
    const flinkRole = new iam.Role(this, 'FlinkApplicationRole', {
      assumedBy: new iam.ServicePrincipal('kinesisanalytics.amazonaws.com'),
      description: 'Execution role for Amazon Managed Service for Apache Flink application',
    });

    // Allow reading the job artifact from the dedicated bucket
    artifactBucket.grantRead(flinkRole);

    // Allow reading secrets (Kafka + SQL Server)
    kafkaCredentialsSecret.grantRead(flinkRole);
    sqlServerCredentialsSecret.grantRead(flinkRole);
    postgresCredentialsSecret.grantRead(flinkRole);

    // Allow writing logs
    flinkRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'logs:DescribeLogStreams',
        'logs:CreateLogStream',
        'logs:PutLogEvents',
      ],
      resources: [
        logGroup.logGroupArn,
        `${logGroup.logGroupArn}:log-stream:*`,
      ],
    }));

    // Allow VPC networking (ENI management) for Amazon Managed Service for Apache Flink
    flinkRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'ec2:DescribeVpcs',
        'ec2:DescribeSubnets',
        'ec2:DescribeSecurityGroups',
        'ec2:DescribeDhcpOptions',
      ],
      resources: ['*'],
    }));

    flinkRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'ec2:CreateNetworkInterface',
        'ec2:CreateNetworkInterfacePermission',
        'ec2:DescribeNetworkInterfaces',
        'ec2:DeleteNetworkInterface',
      ],
      resources: ['*'],
    }));

    // --- Networking ---
    const privateSubnets = vpc.selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS });

    // --- Flink application (Kinesis Analytics v2) ---
    // This uses the low-level CFN resource because the L2 construct coverage is limited.
    const application = new kinesisanalyticsv2.CfnApplication(this, 'AgrirouterAnalyticsFlinkApp', {
      applicationName: 'agrirouter-analytics-flink',
      runtimeEnvironment: 'FLINK-1_20',
      serviceExecutionRole: flinkRole.roleArn,
      applicationConfiguration: {
        applicationCodeConfiguration: {
          codeContent: {
            s3ContentLocation: {
              bucketArn: artifactBucket.bucketArn,
              fileKey: artifactKey,
            },
          },
          codeContentType: 'ZIPFILE',
        },
        vpcConfigurations: [
          {
            securityGroupIds: [flinkSecurityGroup.securityGroupId],
            subnetIds: privateSubnets.subnetIds,
          },
        ],
        applicationSnapshotConfiguration: {
          snapshotsEnabled: false,
        },
        environmentProperties: {
          propertyGroups: [
            {
              propertyGroupId: 'kafka',
              propertyMap: {
                BOOTSTRAP_SERVERS: kafkaBootstrapServers,
                SECURITY_PROTOCOL: 'SASL_PLAINTEXT',
                SASL_MECHANISM: 'SCRAM-SHA-256',
                CREDENTIALS_SECRET_ARN: kafkaCredentialsSecret.secretArn,
                USERNAME_KEY: 'username',
                PASSWORD_KEY: 'password',
                CONSUMER_GROUP: 'agrirouter-analytics-group',
              },
            },
            {
              propertyGroupId: 'sqlserver',
              propertyMap: {
                HOST: sqlServerEndpoint,
                PORT: sqlServerPort,
                DB_NAME: 'analytics_service_db',
                TABLE_NAME: 'EventMetricsDev',
                CREDENTIALS_SECRET_ARN: sqlServerCredentialsSecret.secretArn,
                USERNAME_KEY: 'username',
                PASSWORD_KEY: 'password',
              },
            },
            {
              propertyGroupId: 'postgres',
              propertyMap: {
                HOST: postgresEndpoint,
                PORT: postgresPort,
                DB_NAME: 'analytics_service_db',
                CREDENTIALS_SECRET_ARN: postgresCredentialsSecret.secretArn,
                USERNAME_KEY: 'username',
                PASSWORD_KEY: 'password',
              },
            },
            {
              propertyGroupId: 'app',
              propertyMap: {
                ENV: 'cloud',
                ENVIRONMENT: 'dev',
                OBSERVABILITY_MODE: 'CLOUDWATCH',
                AWS_REGION: this.region,
              },
            },
          ],
        },
        flinkApplicationConfiguration: {
          checkpointConfiguration: {
            configurationType: 'DEFAULT',
          },
          monitoringConfiguration: {
            configurationType: 'CUSTOM',
            logLevel: 'INFO',
            metricsLevel: 'APPLICATION',
          },
          parallelismConfiguration: {
            configurationType: 'CUSTOM',
            parallelism: 1,
            parallelismPerKpu: 1,
            autoScalingEnabled: false,
          },
        },
      },
    });

    application.node.addDependency(deployFlinkArtifact);

    const logStreamArn = cdk.Stack.of(this).formatArn({
      service: 'logs',
      resource: 'log-group',
      resourceName: `${logGroup.logGroupName}:log-stream:${logStream.logStreamName}`,
      arnFormat: ArnFormat.COLON_RESOURCE_NAME, // <-- CRITICAL for CloudWatch Logs
    });

    // CloudWatch logging option is a separate CFN resource.
    const loggingOption =
      new kinesisanalyticsv2.CfnApplicationCloudWatchLoggingOption(this, 'FlinkCloudWatchLogging', {
        applicationName: application.ref,
        cloudWatchLoggingOption: {
          logStreamArn,
        },
      });

    // Ensure resources exist before logging option is created
    loggingOption.node.addDependency(application);
    loggingOption.node.addDependency(logStream);

    this.flinkApplicationName = application.applicationName ?? 'agrirouter-analytics-flink';
    this.artifactBucket = artifactBucket;

    new cdk.CfnOutput(this, 'FlinkApplicationName', {
      value: this.flinkApplicationName,
      description: 'Amazon Managed Service for Apache Flink application name',
      exportName: `${this.stackName}-FlinkApplicationName`,
    });

    new cdk.CfnOutput(this, 'FlinkArtifactBucketName', {
      value: artifactBucket.bucketName,
      description: 'S3 bucket that stores the Managed Flink application artifact (ZIPFILE)',
      exportName: `${this.stackName}-FlinkArtifactBucketName`,
    });

    new cdk.CfnOutput(this, 'FlinkArtifactObjectKey', {
      value: artifactKey,
      description: 'S3 object key used for the Managed Flink application artifact',
      exportName: `${this.stackName}-FlinkArtifactObjectKey`,
    });

    new cdk.CfnOutput(this, 'KafkaConfigurationForFlink', {
      value: JSON.stringify({
        brokers: kafkaBootstrapServers,
        consumerGroup: 'agrirouter-analytics-group',
        securityProtocol: 'SASL_PLAINTEXT',
        saslMechanism: 'SCRAM-SHA-256',
        credentialsSecret: kafkaCredentialsSecret.secretArn,
      }),
      description: 'Kafka configuration passed to the Flink application as property groups',
    });

    new cdk.CfnOutput(this, 'SQLServerConfigurationForFlink', {
      value: JSON.stringify({
        host: sqlServerEndpoint,
        port: sqlServerPort,
        dbname: 'analytics_service_db',
        tablename: 'EventMetricsDev',
        credentialsSecret: sqlServerCredentialsSecret.secretArn,
      }),
      description: 'SQL Server configuration passed to the Flink application as property groups',
    });
  }
}
