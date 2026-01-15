"""
PostgreSQL Database Initialization Lambda Function

This Lambda function is invoked by a CloudFormation Custom Resource to:
1. Create a service-level database
2. Create a service-level user with restricted permissions
3. Grant appropriate privileges
4. Update the service secret with connection details
"""

import json
import boto3
import psycopg2
import cfnresponse

secrets_client = boto3.client('secretsmanager')


def handler(event, context):
    """
    CloudFormation Custom Resource handler for PostgreSQL initialization.
    
    Args:
        event: CloudFormation event object containing resource properties
        context: Lambda context object
    """
    print(f"Event: {json.dumps(event)}")
    
    try:
        if event['RequestType'] == 'Delete':
            # On stack deletion, we don't delete the database/user
            # to prevent data loss. They can be manually cleaned up if needed.
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
            return
        
        # Get master credentials from Secrets Manager
        master_secret_arn = event['ResourceProperties']['MasterSecretArn']
        master_secret = json.loads(
            secrets_client.get_secret_value(SecretId=master_secret_arn)['SecretString']
        )
        
        # Get service credentials from Secrets Manager
        service_secret_arn = event['ResourceProperties']['ServiceSecretArn']
        service_secret = json.loads(
            secrets_client.get_secret_value(SecretId=service_secret_arn)['SecretString']
        )
        
        # Get database endpoint from event properties
        db_host = event['ResourceProperties']['DatabaseHost']
        db_port = int(event['ResourceProperties'].get('DatabasePort', 5432))
        
        service_username = service_secret['username']
        service_password = service_secret['password']
        service_dbname = service_secret['dbname']
        
        print(f"Initializing PostgreSQL database: {service_dbname}")
        print(f"Creating user: {service_username}")
        
        # Connect as master user to the default postgres database
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=master_secret['username'],
            password=master_secret['password'],
            database='postgres',
            connect_timeout=30
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Create database if it doesn't exist
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (service_dbname,)
        )
        if not cursor.fetchone():
            cursor.execute(f'CREATE DATABASE {service_dbname}')
            print(f"✓ Created database: {service_dbname}")
        else:
            print(f"ℹ Database already exists: {service_dbname}")
        
        # Create user if it doesn't exist
        cursor.execute(
            "SELECT 1 FROM pg_user WHERE usename = %s",
            (service_username,)
        )
        if not cursor.fetchone():
            cursor.execute(
                f"CREATE USER {service_username} WITH PASSWORD %s",
                (service_password,)
            )
            print(f"✓ Created user: {service_username}")
        else:
            # Update password if user exists
            cursor.execute(
                f"ALTER USER {service_username} WITH PASSWORD %s",
                (service_password,)
            )
            print(f"✓ Updated password for user: {service_username}")
        
        # Grant privileges on database
        cursor.execute(
            f"GRANT ALL PRIVILEGES ON DATABASE {service_dbname} TO {service_username}"
        )
        print(f"✓ Granted database privileges to user")
        
        cursor.close()
        conn.close()
        
        # Connect to the service database to grant schema privileges
        conn = psycopg2.connect(
            host=db_host,
            port=db_port,
            user=master_secret['username'],
            password=master_secret['password'],
            database=service_dbname,
            connect_timeout=30
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Grant schema privileges
        cursor.execute(f"GRANT ALL ON SCHEMA public TO {service_username}")
        cursor.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {service_username}")
        cursor.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {service_username}")
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT ALL ON TABLES TO {service_username}"
        )
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT ALL ON SEQUENCES TO {service_username}"
        )
        print(f"✓ Granted schema privileges to user")
        
        cursor.close()
        conn.close()
        
        # Update the service secret with host information
        service_secret['host'] = db_host
        service_secret['port'] = db_port
        service_secret['engine'] = 'postgresql'
        
        secrets_client.update_secret(
            SecretId=service_secret_arn,
            SecretString=json.dumps(service_secret)
        )
        print("✓ Updated service secret with connection details")
        
        # Send success response to CloudFormation
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {
            'DatabaseName': service_dbname,
            'Username': service_username,
            'Message': 'PostgreSQL database and user initialized successfully'
        })
        
    except Exception as e:
        error_message = f"Error initializing PostgreSQL: {str(e)}"
        print(f"✗ {error_message}")
        import traceback
        traceback.print_exc()
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=error_message)
