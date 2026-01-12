import * as cdk from 'aws-cdk-lib';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import { Construct } from 'constructs';

interface KafkaStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  kafkaSecurityGroup: ec2.SecurityGroup;
  ecsCluster: ecs.Cluster;
}

export class KafkaStack extends cdk.Stack {
  public readonly kafkaCredentialsSecret: secretsmanager.Secret;
  public readonly kafkaBootstrapServers: string;
  public readonly kafkaService: ecs.FargateService;

  constructor(scope: Construct, id: string, props: KafkaStackProps) {
    super(scope, id, props);

    const { vpc, kafkaSecurityGroup, ecsCluster } = props;

    // Create secrets for Kafka credentials (SASL/PLAIN authentication for compatibility)
    this.kafkaCredentialsSecret = new secretsmanager.Secret(this, 'KafkaCredentials', {
      secretName: 'kafka-credentials',
      description: 'Kafka SASL/PLAIN credentials for analytics service (public access with authentication)',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({
          username: 'analytics-service',
          consumer_group: 'agrirouter-analytics-group',
          auth_type: 'SASL_SCRAM',  // App expects SCRAM
          sasl_mechanism: 'SCRAM-SHA-256',  // App expects SCRAM
          security_protocol: 'SASL_PLAINTEXT',
        }),
        generateStringKey: 'password',
        excludePunctuation: true,
        passwordLength: 32,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create EFS file system for Kafka data persistence (public subnets for internet access)
    const kafkaFileSystem = new efs.FileSystem(this, 'KafkaEFS', {
      vpc,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC, // Use public subnets for internet-accessible setup
      },
      securityGroup: kafkaSecurityGroup,
      encrypted: true,
      lifecyclePolicy: efs.LifecyclePolicy.AFTER_30_DAYS,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      throughputMode: efs.ThroughputMode.BURSTING,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // CloudWatch Log Group for Kafka container
    const kafkaLogGroup = new logs.LogGroup(this, 'KafkaLogGroup', {
      logGroupName: '/ecs/kafka-container',
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Task Definition for Kafka
    const kafkaTaskDefinition = new ecs.FargateTaskDefinition(this, 'KafkaTaskDefinition', {
      memoryLimitMiB: 1024, // 1GB memory for Kafka
      cpu: 512, // 0.5 vCPU
      family: 'kafka-container',
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64, // bitnami images support x86_64
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    // Add EFS volume to task definition
    kafkaTaskDefinition.addVolume({
      name: 'kafka-data',
      efsVolumeConfiguration: {
        fileSystemId: kafkaFileSystem.fileSystemId,
        rootDirectory: '/', // Use root directory - subdirectories will be created by containers
        transitEncryption: 'ENABLED',
        authorizationConfig: {
          iam: 'ENABLED',
        },
      },
    });

    // Add shared volume for configuration files
    kafkaTaskDefinition.addVolume({
      name: 'kafka-config',
    });

    // Grant EFS permissions to task role
    kafkaFileSystem.grantReadWrite(kafkaTaskDefinition.taskRole);
    
    // Grant access to read Kafka credentials secret
    this.kafkaCredentialsSecret.grantRead(kafkaTaskDefinition.taskRole);

    // Create Network Load Balancer first to get DNS name
    const nlb = new elbv2.NetworkLoadBalancer(this, 'KafkaNLB', {
      vpc,
      internetFacing: true,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC,
      },
      crossZoneEnabled: true,
    });

    // Container Definition for Kafka with NLB DNS as advertised listener
    // Using Apache Kafka with KRaft mode (no ZooKeeper needed)
    const kafkaContainer = kafkaTaskDefinition.addContainer('KafkaContainer', {
      image: ecs.ContainerImage.fromRegistry('apache/kafka:latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'kafka',
        logGroup: kafkaLogGroup,
      }),
      essential: true,
      environment: {
        // KRaft mode configuration (no ZooKeeper)
        KAFKA_NODE_ID: '1',
        KAFKA_PROCESS_ROLES: 'broker,controller',
        KAFKA_CONTROLLER_QUORUM_VOTERS: '1@localhost:9093',
        KAFKA_CONTROLLER_LISTENER_NAMES: 'CONTROLLER',
        // Advertised listener uses NLB DNS name
        KAFKA_ADVERTISED_LISTENERS: `SASL_PLAINTEXT://${nlb.loadBalancerDnsName}:9092`,
        KAFKA_LISTENERS: 'SASL_PLAINTEXT://:9092,CONTROLLER://:9093',
        // Security configuration
        KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: 'SASL_PLAINTEXT:SASL_PLAINTEXT,CONTROLLER:PLAINTEXT',
        KAFKA_INTER_BROKER_LISTENER_NAME: 'SASL_PLAINTEXT',
        KAFKA_SECURITY_INTER_BROKER_PROTOCOL: 'SASL_PLAINTEXT',
        // SASL Configuration - Start with PLAIN for bootstrap, then enable SCRAM
        KAFKA_SASL_MECHANISM_INTER_BROKER_PROTOCOL: 'PLAIN',
        KAFKA_SASL_ENABLED_MECHANISMS: 'PLAIN,SCRAM-SHA-256',
        // Cluster ID for KRaft
        CLUSTER_ID: 'kafka-poc-cluster-1',
        // Topic and replication settings
        KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: '1',
        KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: '1',
        KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: '1',
        KAFKA_NUM_PARTITIONS: '3',
        KAFKA_DEFAULT_REPLICATION_FACTOR: '1',
        KAFKA_AUTO_CREATE_TOPICS_ENABLE: 'true',
        // JVM settings for memory constraints
        KAFKA_HEAP_OPTS: '-Xmx512m -Xms256m',
        KAFKA_JVM_PERFORMANCE_OPTS: '-server -XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=35',
        // Log directory
        KAFKA_LOG_DIRS: '/var/lib/kafka/data',
      },
      user: '0:0', // Run as root to ensure EFS write permissions
      command: [
        '/bin/bash',
        '-c',
        `
# Ensure data directory exists and is writable
mkdir -p /var/lib/kafka/data
chmod -R 777 /var/lib/kafka/data
chown -R 1000:1000 /var/lib/kafka/data || true

# Clean up any stale lock files and metadata from previous crashed instances
rm -f /var/lib/kafka/data/.lock || true
rm -f /var/lib/kafka/data/meta.properties || true
echo "✓ Cleaned up stale files"

# Use fixed cluster ID for KRaft (consistent across restarts)
CLUSTER_ID="KafkaPoCCluster1234"
echo "✓ Using cluster ID: \$CLUSTER_ID"
SKIP_FORMAT=false

# Create server.properties for KRaft mode
mkdir -p /tmp/config
cat > /tmp/config/server.properties << EOF
# KRaft configuration
node.id=$KAFKA_NODE_ID
process.roles=$KAFKA_PROCESS_ROLES
controller.quorum.voters=$KAFKA_CONTROLLER_QUORUM_VOTERS
controller.listener.names=$KAFKA_CONTROLLER_LISTENER_NAMES

# Listeners
listeners=$KAFKA_LISTENERS
advertised.listeners=$KAFKA_ADVERTISED_LISTENERS
listener.security.protocol.map=$KAFKA_LISTENER_SECURITY_PROTOCOL_MAP
inter.broker.listener.name=$KAFKA_INTER_BROKER_LISTENER_NAME

# SASL configuration
sasl.enabled.mechanisms=$KAFKA_SASL_ENABLED_MECHANISMS
sasl.mechanism.inter.broker.protocol=$KAFKA_SASL_MECHANISM_INTER_BROKER_PROTOCOL

# Replication settings
offsets.topic.replication.factor=$KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR
transaction.state.log.replication.factor=$KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR
transaction.state.log.min.isr=$KAFKA_TRANSACTION_STATE_LOG_MIN_ISR
num.partitions=$KAFKA_NUM_PARTITIONS
default.replication.factor=$KAFKA_DEFAULT_REPLICATION_FACTOR
auto.create.topics.enable=$KAFKA_AUTO_CREATE_TOPICS_ENABLE

# Log directories
log.dirs=$KAFKA_LOG_DIRS
EOF

# Step 1: Create initial JAAS config for PLAIN authentication (bootstrap phase)
cat > /tmp/config/kafka_server_jaas.conf << EOFJAAS
KafkaServer {
    org.apache.kafka.common.security.plain.PlainLoginModule required
    username="kafka-admin"
    password="$KAFKA_PASSWORD"
    user_kafka-admin="$KAFKA_PASSWORD"
    user_analytics-service="$KAFKA_PASSWORD";
};
EOFJAAS

echo "✓ Initial JAAS config created for PLAIN authentication"

# Step 2: Start with PLAIN-only configuration first
# Create temporary server properties with PLAIN only for bootstrap
cp /tmp/config/server.properties /tmp/config/server.properties.backup
sed -i 's/sasl.enabled.mechanisms=PLAIN,SCRAM-SHA-256/sasl.enabled.mechanisms=PLAIN/' /tmp/config/server.properties

# Format the log directory for KRaft (only if no existing metadata)
if [ "\$SKIP_FORMAT" = "false" ]; then
  /opt/kafka/bin/kafka-storage.sh format -t \$CLUSTER_ID -c /tmp/config/server.properties
  echo "✓ Log directory formatted with cluster ID: \$CLUSTER_ID"
else
  echo "✓ Skipping format - using existing metadata"
fi

# Set JAAS config path
export KAFKA_OPTS="-Djava.security.auth.login.config=/tmp/config/kafka_server_jaas.conf $KAFKA_HEAP_OPTS $KAFKA_JVM_PERFORMANCE_OPTS"

echo "✓ Starting Kafka in PLAIN-only mode for SCRAM setup..."

# Start Kafka in background with PLAIN authentication
/opt/kafka/bin/kafka-server-start.sh /tmp/config/server.properties &
KAFKA_PID=$!

# Wait for Kafka to be ready
echo "Waiting for Kafka to start..."
sleep 15

# Verify Kafka is running before configuring SCRAM users
for i in {1..30}; do
  if /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list >/dev/null 2>&1; then
    echo "✓ Kafka is responding to requests"
    break
  else
    echo "Waiting for Kafka to be ready... (attempt $i/30)"
    sleep 2
  fi
done

# Step 3: Configure SCRAM credentials using PLAIN authentication
echo "Configuring SCRAM-SHA-256 users..."

# Create admin config for authenticated operations using PLAIN
cat > /tmp/config/admin-plain.properties << EOFADMIN
sasl.mechanism=PLAIN
security.protocol=SASL_PLAINTEXT
sasl.jaas.config=org.apache.kafka.common.security.plain.PlainLoginModule required username="kafka-admin" password="$KAFKA_PASSWORD";
EOFADMIN

# Add SCRAM credentials for kafka-admin
echo "Adding SCRAM credentials for kafka-admin..."
/opt/kafka/bin/kafka-configs.sh --bootstrap-server localhost:9092 \
  --alter --add-config "SCRAM-SHA-256=[password=$KAFKA_PASSWORD]" \
  --entity-type users --entity-name kafka-admin \
  --command-config /tmp/config/admin-plain.properties

# Add SCRAM credentials for analytics-service
echo "Adding SCRAM credentials for analytics-service..."
/opt/kafka/bin/kafka-configs.sh --bootstrap-server localhost:9092 \
  --alter --add-config "SCRAM-SHA-256=[password=$KAFKA_PASSWORD]" \
  --entity-type users --entity-name analytics-service \
  --command-config /tmp/config/admin-plain.properties

echo "✓ SCRAM user configuration complete"

# Step 4: Stop Kafka and restart with SCRAM enabled
echo "Stopping Kafka to enable SCRAM authentication..."
kill $KAFKA_PID
wait $KAFKA_PID 2>/dev/null || true

# Step 5: Update JAAS config to support both PLAIN and SCRAM
cat > /tmp/config/kafka_server_jaas.conf << EOFJAASSCRAM
KafkaServer {
    org.apache.kafka.common.security.plain.PlainLoginModule required
    username="kafka-admin"
    password="$KAFKA_PASSWORD"
    user_kafka-admin="$KAFKA_PASSWORD"
    user_analytics-service="$KAFKA_PASSWORD";
    
    org.apache.kafka.common.security.scram.ScramLoginModule required;
};
EOFJAASSCRAM

# Step 6: Restore server properties with both PLAIN and SCRAM
mv /tmp/config/server.properties.backup /tmp/config/server.properties

echo "✓ Starting Kafka with SCRAM-SHA-256 authentication enabled..."

# Start Kafka with both PLAIN and SCRAM support
exec /opt/kafka/bin/kafka-server-start.sh /tmp/config/server.properties
        `,
      ],
      secrets: {
        // Kafka SASL password from Secrets Manager
        KAFKA_PASSWORD: ecs.Secret.fromSecretsManager(this.kafkaCredentialsSecret, 'password'),
      },
    });

    // Add EFS mount point for data
    kafkaContainer.addMountPoints({
      sourceVolume: 'kafka-data',
      containerPath: '/var/lib/kafka/data',
      readOnly: false,
    });

    // Add port mappings
    kafkaContainer.addPortMappings({
      containerPort: 9092,
      protocol: ecs.Protocol.TCP,
    });
    kafkaContainer.addPortMappings({
      containerPort: 9093, // Controller port for KRaft
      protocol: ecs.Protocol.TCP,
    });

    // No ZooKeeper needed - using KRaft mode!

    // Fargate Service for Kafka (public access for PoC)
    this.kafkaService = new ecs.FargateService(this, 'KafkaService', {
      cluster: ecsCluster,
      taskDefinition: kafkaTaskDefinition,
      serviceName: 'kafka-container-service',
      desiredCount: 1, // Single Kafka instance
      assignPublicIp: true, // Assign public IP for internet access
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC, // Use public subnets for internet access
      },
      securityGroups: [kafkaSecurityGroup],
      platformVersion: ecs.FargatePlatformVersion.LATEST,
      enableExecuteCommand: true,
    });

    // Add listener for Kafka port
    const listener = nlb.addListener('KafkaListener', {
      port: 9092,
      protocol: elbv2.Protocol.TCP,
    });

    // Add Fargate service as target
    listener.addTargets('KafkaTarget', {
      port: 9092,
      protocol: elbv2.Protocol.TCP,
      targets: [this.kafkaService],
      healthCheck: {
        enabled: true,
        protocol: elbv2.Protocol.TCP,
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 2,
        interval: cdk.Duration.seconds(30),
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // Set bootstrap servers to NLB DNS name - single point of access for all
    this.kafkaBootstrapServers = `${nlb.loadBalancerDnsName}:9092`;

    // Outputs
    new cdk.CfnOutput(this, 'KafkaServiceArn', {
      value: this.kafkaService.serviceArn,
      description: 'Kafka ECS Service ARN',
    });

    new cdk.CfnOutput(this, 'KafkaCredentialsSecretArn', {
      value: this.kafkaCredentialsSecret.secretArn,
      description: 'Kafka Credentials Secret ARN (SASL/SCRAM-SHA-256 authentication)',
    });

    new cdk.CfnOutput(this, 'KafkaBootstrapServers', {
      value: this.kafkaBootstrapServers,
      description: 'Kafka Bootstrap Servers (NLB DNS - use for ALL connections internal/external)',
    });

    new cdk.CfnOutput(this, 'KafkaNLBDnsName', {
      value: nlb.loadBalancerDnsName,
      description: 'Network Load Balancer DNS name for Kafka access',
    });

    new cdk.CfnOutput(this, 'KafkaEFSFileSystemId', {
      value: kafkaFileSystem.fileSystemId,
      description: 'EFS File System ID for Kafka data persistence',
    });

    new cdk.CfnOutput(this, 'KafkaConnectionInfo', {
      value: JSON.stringify({
        bootstrap_servers: this.kafkaBootstrapServers,
        security_protocol: 'SASL_PLAINTEXT',
        sasl_mechanism: 'SCRAM-SHA-256',
        sasl_username: 'analytics-service',
        sasl_password_secret: this.kafkaCredentialsSecret.secretArn,
        note: 'Use same bootstrap servers for internal and external access',
      }),
      description: 'Complete Kafka connection configuration',
    });

    // Cost estimation output
    new cdk.CfnOutput(this, 'EstimatedMonthlyCost', {
      value: 'Approximately $28-32/month (Fargate: 0.5vCPU/1GB single container + NLB + EFS storage ~1GB + CloudWatch logs)',
      description: 'Estimated cost for containerized Kafka in KRaft mode (no ZooKeeper needed, much cheaper than MSK)',
    });
  }
}
