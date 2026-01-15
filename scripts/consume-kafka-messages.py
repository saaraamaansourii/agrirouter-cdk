#!/usr/bin/env python3
"""
Consumes Kafka messages for the analytics service.

Consumes protobuf-based messages from the following topics:
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
    
    # Consume from all topics
    python3 scripts/consume-kafka-messages.py
    
    # Consume from specific topic
    python3 scripts/consume-kafka-messages.py --topic endpoint.state
    
    # Consume with custom timeout
    python3 scripts/consume-kafka-messages.py --timeout 60
    
    # Use local Kafka (no AWS credentials needed)
    python3 scripts/consume-kafka-messages.py --local
    
    # Start from beginning (earliest offset)
    python3 scripts/consume-kafka-messages.py --from-beginning
    
    # Output as JSON for processing
    python3 scripts/consume-kafka-messages.py --json
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime

import boto3

try:
    from kafka import KafkaConsumer
except ImportError:
    print("Error: kafka-python not installed. Install with: pip install kafka-python")
    sys.exit(1)

# Add generated_pb to path for protobuf imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'generated_pb'))

try:
    from google.protobuf.json_format import MessageToDict
    from gateway_service.routed_message_event_pb2 import RoutedMessageEvent
    from endpoint_service.endpoint_pb2 import Endpoint
    from application_service.application_pb2 import Application
except ImportError as e:
    print(f"Error importing protobuf modules: {e}")
    print("Run: python3 scripts/generate-protobuf.py")
    sys.exit(1)


# Topic configurations with deserializers
TOPICS = {
    'routed_message_delivered.event': {
        'description': 'Routed message delivery events',
        'deserializer': RoutedMessageEvent,
    },
    'message_command_sent.event': {
        'description': 'Message command sent events',
        'deserializer': RoutedMessageEvent,
    },
    'endpoint.state': {
        'description': 'Endpoint state changes',
        'deserializer': Endpoint,
    },
    'application.state': {
        'description': 'Application state changes',
        'deserializer': Application,
    }
}

# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    print("\n\nℹ Received shutdown signal, stopping consumer...")
    running = False


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
        'consumer_group': 'local-analytics-consumer',
    }


def create_kafka_consumer(topics: list, use_local=False, from_beginning=False, consumer_group=None):
    """Create a Kafka consumer with appropriate configuration."""
    if use_local:
        config = get_local_kafka_config()
        kafka_params = {
            'bootstrap_servers': config['bootstrap_servers'],
            'auto_offset_reset': 'earliest' if from_beginning else 'latest',
            'enable_auto_commit': True,
            'group_id': consumer_group or config['consumer_group'],
            'consumer_timeout_ms': 5000,  # Poll timeout
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
            'auto_offset_reset': 'earliest' if from_beginning else 'latest',
            'enable_auto_commit': True,
            'group_id': consumer_group or credentials.get('consumer_group', 'agrirouter-analytics-group'),
            'consumer_timeout_ms': 5000,  # Poll timeout
            'request_timeout_ms': 30000,
            'api_version': (3, 6, 0),
        }
        
        print(f"ℹ Bootstrap Servers: {bootstrap_servers}")
        print(f"ℹ Username: {credentials['username']}")
        print(f"ℹ Security Protocol: {credentials['security_protocol']}")
        print(f"ℹ Consumer Group: {kafka_params['group_id']}")
    
    return KafkaConsumer(*topics, **kafka_params)


def deserialize_message(topic: str, data: bytes) -> dict:
    """Deserialize a protobuf message from the given topic."""
    try:
        message_class = TOPICS[topic]['deserializer']
        message = message_class()
        message.ParseFromString(data)
        return MessageToDict(message, preserving_proto_field_name=True)
    except Exception as e:
        return {
            'error': f'Failed to deserialize: {e}',
            'raw_bytes': data.hex()[:100] + '...' if len(data) > 50 else data.hex()
        }


def format_message(topic: str, message_dict: dict, partition: int, offset: int, 
                   timestamp: int, output_json: bool) -> str:
    """Format a message for display."""
    if output_json:
        return json.dumps({
            'topic': topic,
            'partition': partition,
            'offset': offset,
            'timestamp': timestamp,
            'timestamp_human': datetime.fromtimestamp(timestamp / 1000).isoformat() if timestamp else None,
            'message': message_dict
        }, indent=2, default=str)
    
    # Human-readable format
    lines = [
        f"┌─ {topic} (partition={partition}, offset={offset})",
        f"│  Time: {datetime.fromtimestamp(timestamp / 1000).isoformat() if timestamp else 'N/A'}",
    ]
    
    # Add topic-specific summary
    if topic in ['routed_message_delivered.event', 'message_command_sent.event']:
        lines.append(f"│  Message ID: {message_dict.get('message_id', 'N/A')}")
        lines.append(f"│  Source: {message_dict.get('source_id', 'N/A')[:36]}...")
        lines.append(f"│  Type: {message_dict.get('message_type', 'N/A')}")
        payload_size_raw = message_dict.get('payload_size', 0)
        try:
            payload_size = int(payload_size_raw)
        except (TypeError, ValueError):
            payload_size = 0

        lines.append(f"│  Payload Size: {payload_size:,} bytes")
        recipients = message_dict.get('recipient_ids', [])
        lines.append(f"│  Recipients: {len(recipients)}")
        
    elif topic == 'endpoint.state':
        state = message_dict.get('state', {})
        metadata = message_dict.get('metadata', {})
        lines.append(f"│  Reason: {metadata.get('reason', 'N/A')}")
        lines.append(f"│  Endpoint ID: {state.get('id', 'N/A')}")
        lines.append(f"│  Name: {state.get('name', 'N/A')}")
        lines.append(f"│  Type: {state.get('endpointType', 'N/A')}")
        lines.append(f"│  Gateway: {state.get('gatewayId', 'N/A')}")
        lines.append(f"│  Deactivated: {state.get('isDeactivated', False)}")
        
    elif topic == 'application.state':
        state = message_dict.get('state', {})
        metadata = message_dict.get('metadata', {})
        lines.append(f"│  Reason: {metadata.get('reason', 'N/A')}")
        lines.append(f"│  Name: {state.get('name', 'N/A')}")
        lines.append(f"│  Brand: {state.get('brand', 'N/A')}")
        lines.append(f"│  Type: {state.get('applicationType', 'N/A')}")
        lines.append(f"│  Tenant: {state.get('tenantId', 'N/A')[:36]}..." if state.get('tenantId') else "│  Tenant: N/A")
    
    else:
        # Generic format for unknown topics
        lines.append(f"│  Data: {json.dumps(message_dict, default=str)[:200]}...")
    
    lines.append("└─")
    
    return '\n'.join(lines)


def consume_messages(consumer, timeout: int, output_json: bool):
    """Consume messages from Kafka topics."""
    global running
    
    message_count = 0
    topic_counts = {}
    start_time = time.time()
    
    print(f"\n📥 Consuming messages (timeout: {timeout}s, press Ctrl+C to stop)...\n")
    
    while running:
        # Check timeout
        if time.time() - start_time > timeout:
            print(f"\nℹ Timeout reached ({timeout}s)")
            break
        
        try:
            # Poll for messages (returns after consumer_timeout_ms)
            message_batch = consumer.poll(timeout_ms=1000, max_records=100)
            
            for topic_partition, messages in message_batch.items():
                for message in messages:
                    if not running:
                        break
                    
                    topic = message.topic
                    message_count += 1
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1
                    
                    # Deserialize and format
                    message_dict = deserialize_message(topic, message.value)
                    formatted = format_message(
                        topic, message_dict,
                        message.partition, message.offset,
                        message.timestamp, output_json
                    )
                    
                    print(formatted)
                    if not output_json:
                        print()  # Add blank line for readability
                        
        except StopIteration:
            # No messages available, continue polling
            continue
        except Exception as e:
            print(f"✗ Error consuming message: {e}")
            continue
    
    return message_count, topic_counts


def main():
    parser = argparse.ArgumentParser(
        description='Consume Kafka messages for analytics testing',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Available topics:
  - routed_message_delivered.event  Message delivery events
  - message_command_sent.event      Message command events
  - endpoint.state                  Endpoint state changes
  - application.state               Application state changes
  - all                             All topics (default)

Examples:
  %(prog)s                              # Consume from all topics
  %(prog)s --topic endpoint.state       # Only endpoint state messages
  %(prog)s --from-beginning             # Start from earliest offset
  %(prog)s --timeout 120                # Run for 2 minutes
  %(prog)s --local                      # Use local Kafka (localhost:9092)
  %(prog)s --json                       # Output as JSON
'''
    )
    
    parser.add_argument(
        '--topic', '-t',
        choices=list(TOPICS.keys()) + ['all'],
        default='all',
        help='Topic to consume from (default: all)'
    )
    parser.add_argument(
        '--timeout', '-T',
        type=int,
        default=30,
        help='Timeout in seconds (default: 30, 0 for infinite)'
    )
    parser.add_argument(
        '--from-beginning', '-b',
        action='store_true',
        help='Start consuming from the beginning of the topic'
    )
    parser.add_argument(
        '--local', '-l',
        action='store_true',
        help='Use local Kafka (localhost:9092) instead of AWS'
    )
    parser.add_argument(
        '--json', '-j',
        action='store_true',
        help='Output messages as JSON'
    )
    parser.add_argument(
        '--group', '-g',
        type=str,
        default=None,
        help='Consumer group ID (default: from credentials)'
    )
    
    args = parser.parse_args()
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 60)
    print("  Kafka Message Consumer")
    print("=" * 60)
    print(f"Mode: {'Local' if args.local else 'AWS'}")
    print(f"Topic(s): {args.topic}")
    print(f"Timeout: {args.timeout}s" if args.timeout > 0 else "Timeout: Infinite")
    print(f"From beginning: {args.from_beginning}")
    print(f"Output format: {'JSON' if args.json else 'Human-readable'}")
    print("=" * 60)
    
    # Determine which topics to consume from
    if args.topic == 'all':
        topics_to_consume = list(TOPICS.keys())
    else:
        topics_to_consume = [args.topic]
    
    print(f"\nℹ Subscribing to topics: {topics_to_consume}")
    
    # Create consumer
    print("\nℹ Connecting to Kafka...")
    try:
        consumer = create_kafka_consumer(
            topics_to_consume,
            use_local=args.local,
            from_beginning=args.from_beginning,
            consumer_group=args.group
        )
        print("✓ Connected to Kafka successfully!")
    except Exception as e:
        print(f"✗ Failed to connect to Kafka: {e}")
        sys.exit(1)
    
    # Consume messages
    timeout = args.timeout if args.timeout > 0 else float('inf')
    message_count, topic_counts = consume_messages(consumer, timeout, args.json)
    
    # Summary
    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"Total messages consumed: {message_count}")
    for topic, count in sorted(topic_counts.items()):
        print(f"  - {topic}: {count}")
    print("=" * 60)
    
    consumer.close()


if __name__ == '__main__':
    main()
