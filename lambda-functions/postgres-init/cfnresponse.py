"""
CloudFormation response helper module.

This module provides helper functions for sending responses back to CloudFormation
for custom resources.
"""

import json
import urllib3

SUCCESS = "SUCCESS"
FAILED = "FAILED"

http = urllib3.PoolManager()


def send(event, context, response_status, response_data, physical_resource_id=None, no_echo=False, reason=None):
    """
    Send a response to CloudFormation for a custom resource.
    
    Args:
        event: The CloudFormation event
        context: The Lambda context
        response_status: SUCCESS or FAILED
        response_data: Dictionary of response data
        physical_resource_id: Physical resource ID (optional)
        no_echo: Whether to mask the output (optional)
        reason: Reason for failure (optional)
    """
    response_url = event['ResponseURL']

    response_body = {
        'Status': response_status,
        'Reason': reason or f"See the details in CloudWatch Log Stream: {context.log_stream_name}",
        'PhysicalResourceId': physical_resource_id or context.log_stream_name,
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'NoEcho': no_echo,
        'Data': response_data
    }

    json_response_body = json.dumps(response_body)

    print("Response body:")
    print(json_response_body)

    headers = {
        'content-type': '',
        'content-length': str(len(json_response_body))
    }

    try:
        response = http.request(
            'PUT',
            response_url,
            headers=headers,
            body=json_response_body
        )
        print(f"Status code: {response.status}")
    except Exception as e:
        print(f"send(..) failed executing http.request(..): {e}")
