#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { ComputeStack } from '../lib/compute-stack';
import { KafkaStack } from '../lib/kafka-stack';
import { DatabaseStack } from '../lib/database-stack';
import { FlinkStack } from '../lib/flink-stack';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION,
};

// Shared compute infrastructure stack (VPC, Security Groups, ECS Cluster for Kafka PoC)
const computeStack = new ComputeStack(app, 'ComputeStack', {
  env,
});

// Kafka stack depends on compute stack
const kafkaStack = new KafkaStack(app, 'KafkaStack', {
  env,
  vpc: computeStack.vpc,
  kafkaSecurityGroup: computeStack.kafkaSecurityGroup,
  ecsCluster: computeStack.ecsCluster,
});
kafkaStack.addDependency(computeStack);

// Database stack depends on compute stack
const databaseStack = new DatabaseStack(app, 'DatabaseStack', {
  env,
  vpc: computeStack.vpc,
  databaseSecurityGroup: computeStack.databaseSecurityGroup,
});
databaseStack.addDependency(computeStack);

// Flink stack depends on compute stack, kafka stack, and database stack
const flinkStack = new FlinkStack(app, 'FlinkStack', {
  env,
  vpc: computeStack.vpc,
  flinkSecurityGroup: computeStack.flinkSecurityGroup,
  kafkaCredentialsSecret: kafkaStack.kafkaCredentialsSecret,
  kafkaBootstrapServers: kafkaStack.kafkaBootstrapServers,
  sqlServerCredentialsSecret: databaseStack.sqlServerCredentialsSecret,
  sqlServerEndpoint: databaseStack.sqlServerInstance.instanceEndpoint.hostname,
  sqlServerPort: databaseStack.sqlServerInstance.instanceEndpoint.port.toString(),
  postgresCredentialsSecret: databaseStack.postgresCredentialsSecret,
  postgresEndpoint: databaseStack.postgresInstance.instanceEndpoint.hostname,
  postgresPort: databaseStack.postgresInstance.instanceEndpoint.port.toString(),
});
flinkStack.addDependency(computeStack);
flinkStack.addDependency(kafkaStack);
flinkStack.addDependency(databaseStack);
