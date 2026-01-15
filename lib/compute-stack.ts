import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as servicediscovery from 'aws-cdk-lib/aws-servicediscovery';
import { Construct } from 'constructs';

export class ComputeStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly kafkaSecurityGroup: ec2.SecurityGroup;
  public readonly databaseSecurityGroup: ec2.SecurityGroup;
  public readonly ecsCluster: ecs.Cluster;
  public readonly flinkSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Create shared VPC for all compute resources
    this.vpc = new ec2.Vpc(this, 'SharedVpc', {
      maxAzs: 2, // Use only 2 AZs to minimize costs
      natGateways: 1, // Minimal NAT gateway for serverless Kafka connectivity
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: 'public-subnet',
          subnetType: ec2.SubnetType.PUBLIC,
        },
        {
          cidrMask: 24,
          name: 'private-subnet',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        },
        {
          cidrMask: 24,
          name: 'database-subnet',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    // Security group for Kafka - PUBLIC ACCESS VIA NLB
    this.kafkaSecurityGroup = new ec2.SecurityGroup(this, 'KafkaSecurityGroup', {
      vpc: this.vpc,
      description: 'Security group for Kafka container (public access via NLB with SASL auth)',
      allowAllOutbound: true,
    });

    // Allow Kafka traffic from anywhere (protected by SASL/PLAIN authentication)
    this.kafkaSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(9092),
      'Kafka SASL/PLAIN from internet (via NLB)'
    );
    // Allow KRaft controller port (internal only)
    this.kafkaSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
      ec2.Port.tcp(9093),
      'Kafka KRaft controller from VPC only'
    );
    // Allow NFS traffic for EFS
    this.kafkaSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
      ec2.Port.tcp(2049),
      'EFS NFS from VPC'
    );

    // Security group for databases - PUBLIC ACCESS
    this.databaseSecurityGroup = new ec2.SecurityGroup(this, 'DatabaseSecurityGroup', {
      vpc: this.vpc,
      description: 'Security group for RDS instances (publicly accessible)',
      allowAllOutbound: true,
    });

    // Allow database connections from ANYWHERE (public internet)
        this.databaseSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(5432),
      'PostgreSQL access from internet'
    );
    this.databaseSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(1433),
      'SQL Server access from internet'
    );

    // Allow cross-communication between Kafka and Database security groups
    this.databaseSecurityGroup.addIngressRule(
      this.kafkaSecurityGroup,
      ec2.Port.tcp(5432),
      'PostgreSQL access from Kafka'
    );
    this.databaseSecurityGroup.addIngressRule(
      this.kafkaSecurityGroup,
      ec2.Port.tcp(1433),
      'SQL Server access from Kafka'
    );

    // Security group for the Flink application (Amazon Managed Service for Apache Flink)
    this.flinkSecurityGroup = new ec2.SecurityGroup(this, 'FlinkSecurityGroup', {
      vpc: this.vpc,
      description: 'Security group for Amazon Managed Service for Apache Flink application',
      allowAllOutbound: true,
    });

    // Allow Flink to communicate with databases
    this.databaseSecurityGroup.addIngressRule(
      this.flinkSecurityGroup,
      ec2.Port.tcp(1433),
      'SQL Server access from Flink application'
    );

    // Allow Flink to communicate with Kafka
    this.kafkaSecurityGroup.addIngressRule(
      this.flinkSecurityGroup,
      ec2.Port.tcp(9092),
      'Kafka access from Flink application'
    );

    // ECS Cluster (currently used by the Kafka PoC container).
    // NOTE: Analytics compute has moved to Amazon Managed Service for Apache Flink.
    this.ecsCluster = new ecs.Cluster(this, 'AnalyticsCluster', {
      vpc: this.vpc,
      clusterName: 'agrirouter-analytics-cluster',
      containerInsights: false, // Disable to save costs
      defaultCloudMapNamespace: {
        name: 'analytics.local',
        type: servicediscovery.NamespaceType.DNS_PRIVATE,
      },
    });

    // Outputs for reference
    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpc.vpcId,
      description: 'Shared VPC ID',
      exportName: `${this.stackName}-VpcId`,
    });

    new cdk.CfnOutput(this, 'VpcCidr', {
      value: this.vpc.vpcCidrBlock,
      description: 'VPC CIDR Block',
      exportName: `${this.stackName}-VpcCidr`,
    });

    new cdk.CfnOutput(this, 'KafkaSecurityGroupId', {
      value: this.kafkaSecurityGroup.securityGroupId,
      description: 'Kafka Security Group ID',
      exportName: `${this.stackName}-KafkaSecurityGroupId`,
    });

    new cdk.CfnOutput(this, 'DatabaseSecurityGroupId', {
      value: this.databaseSecurityGroup.securityGroupId,
      description: 'Database Security Group ID',
      exportName: `${this.stackName}-DatabaseSecurityGroupId`,
    });

    new cdk.CfnOutput(this, 'EcsClusterName', {
      value: this.ecsCluster.clusterName,
      description: 'ECS Cluster Name',
      exportName: `${this.stackName}-EcsClusterName`,
    });

    new cdk.CfnOutput(this, 'FlinkSecurityGroupId', {
      value: this.flinkSecurityGroup.securityGroupId,
      description: 'Flink Security Group ID',
      exportName: `${this.stackName}-FlinkSecurityGroupId`,
    });

    // Cost estimation output
    new cdk.CfnOutput(this, 'EstimatedMonthlyCost', {
      value: 'Approximately $32-40/month (1 NAT Gateway + ECS Cluster for Kafka PoC). Flink is priced separately.',
      description: 'Estimated monthly cost for shared compute infrastructure (excluding Kafka/Flink/RDS)',
    });
  }
}
