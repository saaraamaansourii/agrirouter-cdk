#!/usr/bin/env python3
"""
Validation script to test Kafka connectivity using service credentials.
Run this after the CDK stack has been deployed.

Requirements:
    pip install kafka-python boto3
"""

import boto3
import json
import sys
import time

try:
    from kafka import KafkaProducer, KafkaConsumer
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import KafkaError
except ImportError:
    print("Error: kafka-python not installed. Install with: pip install kafka-python")
    sys.exit(1)


def get_kafka_credentials():
    """Retrieve Kafka credentials from AWS Secrets Manager."""
    try:
        secrets_client = boto3.client('secretsmanager')
        secret = json.loads(secrets_client.get_secret_value(
            SecretId='kafka-credentials'
        )['SecretString'])
        return secret
    except Exception as e:
        print(f"✗ Failed to retrieve Kafka credentials from Secrets Manager: {e}")
        sys.exit(1)


def get_kafka_bootstrap_servers():
    """Retrieve Kafka bootstrap servers from CloudFormation outputs."""
    try:
        cfn_client = boto3.client('cloudformation')
        response = cfn_client.describe_stacks(StackName='KafkaStack')
        outputs = response['Stacks'][0]['Outputs']
        
        for output in outputs:
            if output['OutputKey'] == 'KafkaBootstrapServers':
                return output['OutputValue']
        
        print("✗ Could not find KafkaBootstrapServers in CloudFormation outputs")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Failed to retrieve Kafka bootstrap servers from CloudFormation: {e}")
        sys.exit(1)


def test_kafka_connection():
    """Test basic Kafka connectivity."""
    print("\n=== Testing Kafka Connectivity ===")
    
    credentials = get_kafka_credentials()
    bootstrap_servers = get_kafka_bootstrap_servers()
    
    print(f"Bootstrap Servers: {bootstrap_servers}")
    print(f"Username: {credentials['username']}")
    print(f"Security Protocol: {credentials['security_protocol']}")
    print(f"SASL Mechanism: {credentials.get('sasl_mechanism', credentials.get('auth_type', 'PLAIN'))}")
    
    # Determine SASL mechanism
    sasl_mechanism = credentials.get('sasl_mechanism', credentials.get('auth_type', 'SCRAM-SHA-256'))
    if sasl_mechanism == 'SASL_PLAIN':
        sasl_mechanism = 'PLAIN'
    elif sasl_mechanism == 'SASL_SCRAM' or 'SCRAM' in sasl_mechanism:
        # Use SCRAM-SHA-256 as configured in the broker
        sasl_mechanism = 'SCRAM-SHA-256'
    
    # Prepare connection parameters based on SASL mechanism
    kafka_params = {
        'bootstrap_servers': bootstrap_servers,
        'security_protocol': credentials['security_protocol'],
        'sasl_mechanism': sasl_mechanism,
        'request_timeout_ms': 30000,
        'api_version': (3, 6, 0),
    }
    
    # Add authentication parameters based on mechanism
    if sasl_mechanism in ['PLAIN']:
        kafka_params['sasl_plain_username'] = credentials['username']
        kafka_params['sasl_plain_password'] = credentials['password']
    elif 'SCRAM' in sasl_mechanism:
        kafka_params['sasl_plain_username'] = credentials['username']
        kafka_params['sasl_plain_password'] = credentials['password']
    
    try:
        # Test connection with admin client
        admin_client = KafkaAdminClient(**kafka_params)
        
        print("✓ Connected to Kafka cluster successfully!")
        
        # List topics
        topics = admin_client.list_topics()
        print(f"✓ Existing topics: {list(topics) if topics else '(none)'}")
        
        admin_client.close()
        return True
        
    except Exception as e:
        print(f"✗ Kafka connection failed: {e}")
        return False


def test_kafka_topic_operations():
    """Test creating topics, producing, and consuming messages."""
    print("\n=== Testing Kafka Topic Operations ===")
    
    credentials = get_kafka_credentials()
    bootstrap_servers = get_kafka_bootstrap_servers()
    test_topic = 'test-validation-topic'
    
    # Determine SASL mechanism
    sasl_mechanism = credentials.get('sasl_mechanism', credentials.get('auth_type', 'SCRAM-SHA-256'))
    if sasl_mechanism == 'SASL_PLAIN':
        sasl_mechanism = 'PLAIN'
    elif sasl_mechanism == 'SASL_SCRAM' or 'SCRAM' in sasl_mechanism:
        # Use SCRAM-SHA-256 as configured in the broker
        sasl_mechanism = 'SCRAM-SHA-256'
    
    # Prepare connection parameters
    kafka_params = {
        'bootstrap_servers': bootstrap_servers,
        'security_protocol': credentials['security_protocol'],
        'sasl_mechanism': sasl_mechanism,
        'sasl_plain_username': credentials['username'],
        'sasl_plain_password': credentials['password'],
        'request_timeout_ms': 30000,
        'api_version': (3, 6, 0),
    }
    
    try:
        # Create admin client
        admin_client = KafkaAdminClient(**kafka_params)
        
        # Create test topic
        print(f"Creating test topic: {test_topic}")
        topic = NewTopic(name=test_topic, num_partitions=3, replication_factor=1)
        
        try:
            admin_client.create_topics(new_topics=[topic], validate_only=False)
            print(f"✓ Topic '{test_topic}' created successfully")
            time.sleep(2)  # Wait for topic to be ready
        except Exception as e:
            if 'TopicExistsError' in str(e):
                print(f"ℹ Topic '{test_topic}' already exists")
            else:
                raise
        
        admin_client.close()
        
        # Test producer
        print("\nTesting Kafka Producer...")
        producer_params = kafka_params.copy()
        producer_params['value_serializer'] = lambda v: json.dumps(v).encode('utf-8')
        producer = KafkaProducer(**producer_params)
        
        # Send test messages
        test_messages = [
            {'id': 1, 'message': 'Test message 1', 'timestamp': time.time()},
            {'id': 2, 'message': 'Test message 2', 'timestamp': time.time()},
            {'id': 3, 'message': 'Test message 3', 'timestamp': time.time()},
        ]
        
        for msg in test_messages:
            future = producer.send(test_topic, value=msg)
            result = future.get(timeout=10)
            print(f"✓ Sent message {msg['id']} to partition {result.partition} at offset {result.offset}")
        
        producer.flush()
        producer.close()
        print("✓ Producer test completed successfully")
        
        # Test consumer
        print("\nTesting Kafka Consumer...")
        consumer_params = kafka_params.copy()
        consumer_params['value_deserializer'] = lambda m: json.loads(m.decode('utf-8'))
        consumer_params['auto_offset_reset'] = 'earliest'
        consumer_params['consumer_timeout_ms'] = 10000
        consumer_params['group_id'] = credentials['consumer_group']
        consumer = KafkaConsumer(test_topic, **consumer_params)
        
        messages_received = 0
        for message in consumer:
            messages_received += 1
            print(f"✓ Received message {messages_received}: {message.value['message']} "
                  f"(partition={message.partition}, offset={message.offset})")
            
            if messages_received >= len(test_messages):
                break
        
        consumer.close()
        
        if messages_received == len(test_messages):
            print(f"✓ Consumer test completed successfully ({messages_received}/{len(test_messages)} messages)")
        else:
            print(f"⚠ Consumer received {messages_received}/{len(test_messages)} messages")
        
        # Clean up - delete test topic
        print(f"\nCleaning up test topic: {test_topic}")
        admin_client = KafkaAdminClient(**kafka_params)
        
        admin_client.delete_topics([test_topic])
        print(f"✓ Test topic '{test_topic}' deleted")
        admin_client.close()
        
        return messages_received == len(test_messages)
        
    except Exception as e:
        print(f"✗ Kafka topic operations failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kafka_performance():
    """Test basic Kafka performance metrics."""
    print("\n=== Testing Kafka Performance ===")
    
    credentials = get_kafka_credentials()
    bootstrap_servers = get_kafka_bootstrap_servers()
    test_topic = 'test-performance-topic'
    num_messages = 100
    
    # Determine SASL mechanism
    sasl_mechanism = credentials.get('sasl_mechanism', credentials.get('auth_type', 'SCRAM-SHA-256'))
    if sasl_mechanism == 'SASL_PLAIN':
        sasl_mechanism = 'PLAIN'
    elif sasl_mechanism == 'SASL_SCRAM' or 'SCRAM' in sasl_mechanism:
        # Use SCRAM-SHA-256 as configured in the broker
        sasl_mechanism = 'SCRAM-SHA-256'
    
    # Prepare connection parameters
    kafka_params = {
        'bootstrap_servers': bootstrap_servers,
        'security_protocol': credentials['security_protocol'],
        'sasl_mechanism': sasl_mechanism,
        'sasl_plain_username': credentials['username'],
        'sasl_plain_password': credentials['password'],
        'request_timeout_ms': 30000,
        'api_version': (3, 6, 0),
    }
    
    try:
        # Create admin client and topic
        admin_client = KafkaAdminClient(**kafka_params)
        
        topic = NewTopic(name=test_topic, num_partitions=3, replication_factor=1)
        try:
            admin_client.create_topics(new_topics=[topic], validate_only=False)
            time.sleep(2)
        except:
            pass  # Topic might already exist
        
        admin_client.close()
        
        # Test write performance
        print(f"\nSending {num_messages} messages...")
        producer_params = kafka_params.copy()
        producer_params['value_serializer'] = lambda v: json.dumps(v).encode('utf-8')
        producer = KafkaProducer(**producer_params)
        
        start_time = time.time()
        for i in range(num_messages):
            msg = {'id': i, 'data': f'Performance test message {i}', 'timestamp': time.time()}
            producer.send(test_topic, value=msg)
        
        producer.flush()
        producer.close()
        
        write_duration = time.time() - start_time
        write_throughput = num_messages / write_duration
        
        print(f"✓ Write Performance: {num_messages} messages in {write_duration:.2f}s "
              f"({write_throughput:.1f} messages/sec)")
        
        # Test read performance
        print(f"\nReading {num_messages} messages...")
        consumer_params = kafka_params.copy()
        consumer_params['value_deserializer'] = lambda m: json.loads(m.decode('utf-8'))
        consumer_params['auto_offset_reset'] = 'earliest'
        consumer_params['consumer_timeout_ms'] = 15000
        consumer_params['group_id'] = f'{credentials["consumer_group"]}-perf-test'
        consumer = KafkaConsumer(test_topic, **consumer_params)
        
        start_time = time.time()
        messages_read = 0
        for _ in consumer:
            messages_read += 1
            if messages_read >= num_messages:
                break
        
        consumer.close()
        
        read_duration = time.time() - start_time
        read_throughput = messages_read / read_duration if read_duration > 0 else 0
        
        print(f"✓ Read Performance: {messages_read} messages in {read_duration:.2f}s "
              f"({read_throughput:.1f} messages/sec)")
        
        # Clean up
        admin_client = KafkaAdminClient(**kafka_params)
        admin_client.delete_topics([test_topic])
        admin_client.close()
        
        return True
        
    except Exception as e:
        print(f"✗ Performance test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main validation function."""
    print("=" * 70)
    print("Kafka Service Validation")
    print("=" * 70)
    
    connection_ok = test_kafka_connection()
    operations_ok = test_kafka_topic_operations() if connection_ok else False
    performance_ok = test_kafka_performance() if connection_ok else False
    
    print("\n" + "=" * 70)
    print("Summary:")
    print(f"  Connectivity:       {'✓ PASS' if connection_ok else '✗ FAIL'}")
    print(f"  Topic Operations:   {'✓ PASS' if operations_ok else '✗ FAIL or SKIPPED'}")
    print(f"  Performance Test:   {'✓ PASS' if performance_ok else '✗ FAIL or SKIPPED'}")
    print("=" * 70)
    
    if connection_ok and operations_ok:
        print("\n✓ Kafka service is fully operational!")
        print("\nConnection Details:")
        credentials = get_kafka_credentials()
        bootstrap_servers = get_kafka_bootstrap_servers()
        sasl_mechanism = credentials.get('sasl_mechanism', credentials.get('auth_type', 'PLAIN'))
        print(f"  Bootstrap Servers: {bootstrap_servers}")
        print(f"  Security Protocol: {credentials['security_protocol']}")
        print(f"  SASL Mechanism:    {sasl_mechanism}")
        print(f"  Username:          {credentials['username']}")
        print(f"  Consumer Group:    {credentials['consumer_group']}")
        print(f"\n  Password stored in AWS Secrets Manager: kafka-credentials")
        sys.exit(0)
    else:
        print("\n✗ Kafka service validation failed. Check the output above.")
        sys.exit(1)


if __name__ == '__main__':
    main()
