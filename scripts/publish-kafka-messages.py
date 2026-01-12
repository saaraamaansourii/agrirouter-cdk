#!/usr/bin/env python3
"""
Publishes simulated Kafka messages for testing the analytics service.

Generates realistic protobuf-based messages for the following topics:
- routed_message_delivered.event (MessageForMetricsEvent / RoutedMessageEvent)
- message_command_sent.event (MessageForMetricsEvent / RoutedMessageEvent)
- endpoint.state (Endpoint state changes)
- application.state (Application state changes)

Requirements:
    pip install kafka-python boto3 protobuf
    
Usage:
    # Activate virtual environment
    source scripts/venv/bin/activate
    
    # Set AWS profile
    export AWS_PROFILE=dke-thdeg-admin
    
    # Basic usage - send 10 messages per topic
    python3 scripts/publish-kafka-messages.py
    
    # Send specific number of messages with custom interval
    python3 scripts/publish-kafka-messages.py --count 20 --interval 2.0
    
    # Focus on specific topic
    python3 scripts/publish-kafka-messages.py --topic routed_message_delivered.event --count 50
    
    # Use local Kafka (no AWS credentials needed)
    python3 scripts/publish-kafka-messages.py --local --count 5
"""

import argparse
import json
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

import boto3

try:
    from kafka import KafkaProducer
    from kafka.admin import KafkaAdminClient, NewTopic
except ImportError:
    print("Error: kafka-python not installed. Install with: pip install kafka-python")
    sys.exit(1)

# Add generated_pb to path for protobuf imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'generated_pb'))

try:
    from google.protobuf.timestamp_pb2 import Timestamp
    from gateway_service.routed_message_event_pb2 import RoutedMessageEvent
    from endpoint_service.endpoint_pb2 import Endpoint, EndpointState, EndpointType, GatewayId
    from application_service.application_pb2 import Application, ApplicationState
    import common_pb2 as common
except ImportError as e:
    print(f"Error importing protobuf modules: {e}")
    print("Run: python3 scripts/generate-protobuf.py")
    sys.exit(1)


# Topic configurations
TOPICS = {
    'routed_message_delivered.event': {
        'description': 'Routed message delivery events',
        'generator': 'generate_routed_message_event'
    },
    'message_command_sent.event': {
        'description': 'Message command sent events',
        'generator': 'generate_routed_message_event'
    },
    'endpoint.state': {
        'description': 'Endpoint state changes',
        'generator': 'generate_endpoint_event'
    },
    'application.state': {
        'description': 'Application state changes',
        'generator': 'generate_application_event'
    }
}

# Realistic technical message types
TECHNICAL_MESSAGE_TYPES = [
    'iso:11783:-10:taskdata:zip',
    'iso:11783:-10:efdi_device_description:protobuf',
    'iso:11783:-10:efdi_time_log:protobuf',
    'dke:agrirouter:push_notification',
    'dke:agrirouter:list_endpoints',
    'dke:agrirouter:subscription',
    'dke:agrirouter:capabilities',
    'dke:agrirouter:feed_header_query',
    'dke:agrirouter:feed_message_query',
    'dke:agrirouter:feed_confirm',
    'dke:agrirouter:feed_delete',
]

# Endpoint state change reasons
ENDPOINT_REASONS = [
    'endpoint_registered',
    'endpoint_updated',
    'endpoint_deactivated',
    'endpoint_reactivated',
    'capabilities_changed',
    'subscription_changed',
]

# Application state change reasons
APPLICATION_REASONS = [
    'application_registered',
    'application_updated',
    'application_version_changed',
    'application_deactivated',
]

# Equipment names for realistic data
EQUIPMENT_NAMES = [
    'John Deere 8R 410',
    'Case IH Magnum 380',
    'Fendt 1050 Vario',
    'New Holland T9.700',
    'Claas Xerion 5000',
    'Massey Ferguson 8S.265',
    'Kubota M7-172',
    'Valtra S394',
]

# Application names
APPLICATION_NAMES = [
    'FarmWorks Pro',
    'AgriSync',
    'CropManager',
    'FieldView Plus',
    'TractorConnect',
    'HarvestTracker',
    'SoilSense',
    'WeatherGuard Ag',
]


def get_kafka_credentials_aws():
    """Retrieve Kafka credentials from AWS Secrets Manager."""
    try:
        secrets_client = boto3.client('secretsmanager')
        secret = json.loads(secrets_client.get_secret_value(
            SecretId='kafka-credentials'
        )['SecretString'])
        return secret
    except Exception as e:
        print(f"✗ Failed to retrieve Kafka credentials from Secrets Manager: {e}")
        return None


def get_kafka_bootstrap_servers_aws():
    """Retrieve Kafka bootstrap servers from CloudFormation outputs."""
    try:
        cfn_client = boto3.client('cloudformation')
        response = cfn_client.describe_stacks(StackName='KafkaStack')
        outputs = response['Stacks'][0]['Outputs']
        
        for output in outputs:
            if output['OutputKey'] == 'KafkaBootstrapServers':
                return output['OutputValue']
        
        print("✗ Could not find KafkaBootstrapServers in CloudFormation outputs")
        return None
    except Exception as e:
        print(f"✗ Failed to retrieve Kafka bootstrap servers: {e}")
        return None


def get_local_kafka_config():
    """Return local Kafka configuration for testing."""
    return {
        'bootstrap_servers': 'localhost:9092',
        'username': None,
        'password': None,
        'security_protocol': 'PLAINTEXT',
        'sasl_mechanism': None,
    }


def create_kafka_producer(use_local=False):
    """Create a Kafka producer with appropriate configuration."""
    if use_local:
        config = get_local_kafka_config()
        kafka_params = {
            'bootstrap_servers': config['bootstrap_servers'],
            'value_serializer': lambda v: v,  # Already serialized protobuf bytes
            'request_timeout_ms': 30000,
            'api_version': (3, 6, 0),
        }
    else:
        credentials = get_kafka_credentials_aws()
        bootstrap_servers = get_kafka_bootstrap_servers_aws()
        
        if not credentials or not bootstrap_servers:
            print("✗ Failed to get AWS Kafka configuration")
            sys.exit(1)
        
        # Determine SASL mechanism
        sasl_mechanism = credentials.get('sasl_mechanism', credentials.get('auth_type', 'SCRAM-SHA-256'))
        if sasl_mechanism == 'SASL_PLAIN':
            sasl_mechanism = 'PLAIN'
        elif sasl_mechanism == 'SASL_SCRAM' or 'SCRAM' in sasl_mechanism:
            sasl_mechanism = 'SCRAM-SHA-256'
        
        kafka_params = {
            'bootstrap_servers': bootstrap_servers,
            'security_protocol': credentials['security_protocol'],
            'sasl_mechanism': sasl_mechanism,
            'sasl_plain_username': credentials['username'],
            'sasl_plain_password': credentials['password'],
            'value_serializer': lambda v: v,  # Already serialized protobuf bytes
            'request_timeout_ms': 30000,
            'api_version': (3, 6, 0),
        }
        
        print(f"ℹ Bootstrap Servers: {bootstrap_servers}")
        print(f"ℹ Username: {credentials['username']}")
        print(f"ℹ Security Protocol: {credentials['security_protocol']}")
    
    return KafkaProducer(**kafka_params)


def ensure_topics_exist(use_local=False):
    """Ensure all required topics exist."""
    if use_local:
        config = get_local_kafka_config()
        kafka_params = {
            'bootstrap_servers': config['bootstrap_servers'],
            'request_timeout_ms': 30000,
            'api_version': (3, 6, 0),
        }
    else:
        credentials = get_kafka_credentials_aws()
        bootstrap_servers = get_kafka_bootstrap_servers_aws()
        
        if not credentials or not bootstrap_servers:
            return False
        
        sasl_mechanism = credentials.get('sasl_mechanism', credentials.get('auth_type', 'SCRAM-SHA-256'))
        if sasl_mechanism == 'SASL_PLAIN':
            sasl_mechanism = 'PLAIN'
        elif sasl_mechanism == 'SASL_SCRAM' or 'SCRAM' in sasl_mechanism:
            sasl_mechanism = 'SCRAM-SHA-256'
        
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
        admin_client = KafkaAdminClient(**kafka_params)
        existing_topics = set(admin_client.list_topics())
        
        topics_to_create = []
        for topic_name in TOPICS.keys():
            if topic_name not in existing_topics:
                topics_to_create.append(NewTopic(
                    name=topic_name,
                    num_partitions=3,
                    replication_factor=1
                ))
        
        if topics_to_create:
            admin_client.create_topics(new_topics=topics_to_create, validate_only=False)
            print(f"✓ Created topics: {[t.name for t in topics_to_create]}")
            time.sleep(2)  # Wait for topics to be ready
        else:
            print(f"ℹ All topics already exist: {list(TOPICS.keys())}")
        
        admin_client.close()
        return True
    except Exception as e:
        print(f"⚠ Could not verify/create topics: {e}")
        return True  # Continue anyway, topics might be auto-created


def generate_uuid() -> str:
    """Generate a random UUID string."""
    return str(uuid.uuid4())


def generate_timestamp() -> Timestamp:
    """Generate a protobuf Timestamp for the current time."""
    ts = Timestamp()
    ts.FromDatetime(datetime.now(timezone.utc))
    return ts


def generate_routed_message_event() -> bytes:
    """Generate a RoutedMessageEvent protobuf message."""
    event = RoutedMessageEvent()
    
    event.message_id = generate_uuid()
    event.source_id = generate_uuid()
    event.message_type = random.choice(TECHNICAL_MESSAGE_TYPES)
    event.application_seq_number = random.randint(1, 100000)
    event.recipient_ids.extend([generate_uuid() for _ in range(random.randint(1, 3))])
    event.team_set_context_id = generate_uuid()
    event.timestamp.CopyFrom(generate_timestamp())
    event.payload_size = random.randint(100, 10 * 1024 * 1024)  # 100B to 10MB
    event.payload_file_key = f"s3://bucket/{generate_uuid()}"
    event.created_at.CopyFrom(generate_timestamp())
    event.application_message_id = generate_uuid()
    event.tenant_id = generate_uuid()
    
    # Optional: Add metadata
    event.metadata.file_name = f"taskdata_{random.randint(1000, 9999)}.zip"
    
    # Optional: Add chunk component for large messages
    if event.payload_size > 1024 * 1024:  # If > 1MB, simulate chunking
        event.chunk_component.context_id = generate_uuid()
        event.chunk_component.current = 1
        event.chunk_component.total = random.randint(2, 5)
        event.chunk_component.total_size = event.payload_size
    
    return event.SerializeToString()


def generate_endpoint_event() -> bytes:
    """Generate an Endpoint protobuf message."""
    endpoint = Endpoint()
    
    # Metadata
    endpoint.metadata.reason = random.choice(ENDPOINT_REASONS)
    
    # State
    endpoint.state.id = generate_uuid()
    endpoint.state.tenantId = generate_uuid()
    endpoint.state.name = f"{random.choice(EQUIPMENT_NAMES)} - Unit {random.randint(1, 99)}"
    endpoint.state.description = f"Agricultural equipment in Field {random.randint(1, 20)}"
    endpoint.state.endpointType = random.choice([
        EndpointType.AGRICULTURAL_SOFTWARE,
        EndpointType.COMMUNICATION_UNIT,
        EndpointType.VIRTUAL_COMMUNICATION_UNIT,
        EndpointType.TELEMETRY_PLATFORM,
    ])
    endpoint.state.isDefaultGroup = random.choice([True, False])
    endpoint.state.appVersionId = f"v{random.randint(1, 5)}.{random.randint(0, 9)}.{random.randint(0, 99)}"
    endpoint.state.isDeactivated = random.choice([True, False, False, False])  # Mostly active
    endpoint.state.externalId = f"EXT-{random.randint(10000, 99999)}"
    endpoint.state.versionTag = generate_uuid()[:8]
    endpoint.state.gatewayId = random.choice([
        GatewayId.MQTT,
        GatewayId.HTTP,
        GatewayId.G4,
    ])
    endpoint.state.applicationId = generate_uuid()
    
    return endpoint.SerializeToString()


def generate_application_event() -> bytes:
    """Generate an Application protobuf message."""
    app = Application()
    
    # Metadata
    app.metadata.reason = random.choice(APPLICATION_REASONS)
    
    # State
    app_name = random.choice(APPLICATION_NAMES)
    app.state.tenantId = generate_uuid()
    app.state.name = app_name
    app.state.description = f"{app_name} - Agricultural management software"
    app.state.type = random.choice(['farming_software', 'telemetry', 'analytics', 'fleet_management'])
    app.state.logoUrl = f"https://example.com/logos/{app_name.lower().replace(' ', '_')}.png"
    app.state.brand = random.choice(['DKE-Data', 'AgriTech', 'FarmSoft', 'CropCo'])
    app.state.supportUrl = f"https://support.example.com/{app_name.lower().replace(' ', '-')}"
    app.state.deepUrl = f"app://{app_name.lower().replace(' ', '')}"
    app.state.redirectUrl.extend([
        f"https://{app_name.lower().replace(' ', '')}.example.com/callback",
        f"https://{app_name.lower().replace(' ', '')}.example.com/oauth/callback",
    ])
    app.state.publicKey = f"-----BEGIN PUBLIC KEY-----\n{generate_uuid().replace('-', '')}\n-----END PUBLIC KEY-----"
    app.state.versionTag = generate_uuid()[:8]
    app.state.applicationType = random.choice([
        ApplicationState.ApplicationType.COMMUNICATION_UNIT,
        ApplicationState.ApplicationType.FARMING_SOFTWARE,
        ApplicationState.ApplicationType.TELEMETRY_PLATFORM,
    ])
    
    return app.SerializeToString()


# Message generators lookup
MESSAGE_GENERATORS = {
    'generate_routed_message_event': generate_routed_message_event,
    'generate_endpoint_event': generate_endpoint_event,
    'generate_application_event': generate_application_event,
}


def publish_messages(producer, topic: str, count: int, interval: float):
    """Publish messages to a specific topic."""
    generator_name = TOPICS[topic]['generator']
    generator = MESSAGE_GENERATORS[generator_name]
    
    print(f"\n📤 Publishing {count} messages to topic: {topic}")
    print(f"   Generator: {generator_name}")
    
    success_count = 0
    error_count = 0
    
    for i in range(count):
        try:
            message = generator()
            future = producer.send(topic, value=message)
            result = future.get(timeout=10)
            success_count += 1
            
            print(f"   ✓ [{i+1}/{count}] Sent to partition {result.partition} at offset {result.offset}")
            
            if interval > 0 and i < count - 1:
                time.sleep(interval)
                
        except Exception as e:
            error_count += 1
            print(f"   ✗ [{i+1}/{count}] Failed: {e}")
    
    producer.flush()
    return success_count, error_count


def main():
    parser = argparse.ArgumentParser(
        description='Publish simulated Kafka messages for analytics testing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Available topics:
  - routed_message_delivered.event  Message delivery events
  - message_command_sent.event      Message command events
  - endpoint.state                  Endpoint state changes
  - application.state               Application state changes
  - all                             All topics (default)

Examples:
  %(prog)s                              # Send 10 messages per topic
  %(prog)s --count 50 --interval 0.5    # Send 50 messages with 0.5s interval
  %(prog)s --topic endpoint.state       # Only endpoint state messages
  %(prog)s --local                      # Use local Kafka (localhost:9092)
'''
    )
    
    parser.add_argument(
        '--topic', '-t',
        choices=list(TOPICS.keys()) + ['all'],
        default='all',
        help='Topic to publish to (default: all)'
    )
    parser.add_argument(
        '--count', '-c',
        type=int,
        default=10,
        help='Number of messages to send per topic (default: 10)'
    )
    parser.add_argument(
        '--interval', '-i',
        type=float,
        default=0.5,
        help='Interval between messages in seconds (default: 0.5)'
    )
    parser.add_argument(
        '--local', '-l',
        action='store_true',
        help='Use local Kafka (localhost:9092) instead of AWS'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  Kafka Message Publisher")
    print("=" * 60)
    print(f"Mode: {'Local' if args.local else 'AWS'}")
    print(f"Topic(s): {args.topic}")
    print(f"Messages per topic: {args.count}")
    print(f"Interval: {args.interval}s")
    print("=" * 60)
    
    # Ensure topics exist
    print("\nℹ Checking/creating topics...")
    ensure_topics_exist(use_local=args.local)
    
    # Create producer
    print("\nℹ Connecting to Kafka...")
    try:
        producer = create_kafka_producer(use_local=args.local)
        print("✓ Connected to Kafka successfully!")
    except Exception as e:
        print(f"✗ Failed to connect to Kafka: {e}")
        sys.exit(1)
    
    # Determine which topics to publish to
    if args.topic == 'all':
        topics_to_publish = list(TOPICS.keys())
    else:
        topics_to_publish = [args.topic]
    
    # Publish messages
    total_success = 0
    total_errors = 0
    
    start_time = time.time()
    
    for topic in topics_to_publish:
        success, errors = publish_messages(producer, topic, args.count, args.interval)
        total_success += success
        total_errors += errors
    
    elapsed_time = time.time() - start_time
    
    # Summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"Total messages sent: {total_success}")
    print(f"Total errors: {total_errors}")
    print(f"Time elapsed: {elapsed_time:.2f}s")
    print(f"Throughput: {total_success / elapsed_time:.2f} msg/s")
    print("=" * 60)
    
    producer.close()
    
    if total_errors > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
