"""
SQL Server Database Initialization Lambda Function

This Lambda function is invoked by a CloudFormation Custom Resource to:
1. Create a service-level database
2. Create a service-level login and user with restricted permissions
3. Grant appropriate privileges (db_owner role)
4. Create the EventMetricsDev table
5. Update the service secret with connection details
"""

import json
import boto3
import pymssql
import cfnresponse

secrets_client = boto3.client('secretsmanager')


def handler(event, context):
    """
    CloudFormation Custom Resource handler for SQL Server initialization.
    
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
        db_port = int(event['ResourceProperties'].get('DatabasePort', 1433))
        
        # Extract master credentials
        master_username = master_secret['username']
        master_password = master_secret['password']
        
        # Extract service credentials
        service_username = service_secret['username']
        service_password = service_secret['password']
        service_dbname = service_secret['dbname']
        table_name = service_secret.get('tablename', 'EventMetricsDev')
        
        print(f"Initializing SQL Server database: {service_dbname}")
        print(f"Creating login/user: {service_username}")
        print(f"Creating table: {table_name}")
        
        # Connect to master database using master credentials
        # Use autocommit=True because CREATE DATABASE must run outside a transaction
        conn = pymssql.connect(
            server=db_host,
            port=int(db_port),
            user=master_username,
            password=master_password,
            database='master',
            autocommit=True
        )
        cursor = conn.cursor()
        
        # Check if database exists
        cursor.execute(
            "SELECT database_id FROM sys.databases WHERE name = %s",
            (service_dbname,)
        )
        db_exists = cursor.fetchone() is not None
        
        # Create service database if it doesn't exist
        if not db_exists:
            cursor.execute(f"CREATE DATABASE [{service_dbname}]")
            print(f"✓ Created database: {service_dbname}")
        else:
            print(f"ℹ Database already exists: {service_dbname}")
        
        # Create login if it doesn't exist
        cursor.execute(
            f"SELECT name FROM sys.server_principals WHERE name = '{service_username}'"
        )
        if not cursor.fetchone():
            cursor.execute(
                f"CREATE LOGIN [{service_username}] WITH PASSWORD = '{service_password}'"
            )
            conn.commit()
            print(f"✓ Created login: {service_username}")
        else:
            # Update password if login exists
            cursor.execute(
                f"ALTER LOGIN [{service_username}] WITH PASSWORD = '{service_password}'"
            )
            conn.commit()
            print(f"✓ Updated password for login: {service_username}")
        
        cursor.close()
        conn.close()
        
        # Connect to the service database to create user and grant permissions
        conn = pymssql.connect(
            server=db_host,
            port=db_port,
            user=master_secret['username'],
            password=master_secret['password'],
            database=service_dbname,
            timeout=30
        )
        cursor = conn.cursor()
        
        # Create user for the login if it doesn't exist
        cursor.execute(
            f"SELECT name FROM sys.database_principals WHERE name = '{service_username}'"
        )
        if not cursor.fetchone():
            cursor.execute(f"CREATE USER [{service_username}] FOR LOGIN [{service_username}]")
            conn.commit()
            print(f"✓ Created user: {service_username}")
        
        # Grant db_owner role
        cursor.execute(f"ALTER ROLE db_owner ADD MEMBER [{service_username}]")
        conn.commit()
        print(f"✓ Granted db_owner role to user")
        
        # Create EventMetricsDev table if it doesn't exist
        cursor.execute(f"""
            IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = '{table_name}')
            BEGIN
                CREATE TABLE [{table_name}] (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    event_name NVARCHAR(255) NOT NULL,
                    metric_value DECIMAL(18,2),
                    timestamp DATETIME2 DEFAULT GETDATE(),
                    metadata NVARCHAR(MAX)
                )
            END
        """)
        conn.commit()
        print(f"✓ Created or verified table: {table_name}")
        
        cursor.close()
        conn.close()
        
        # Update the service secret with host information
        service_secret['host'] = db_host
        service_secret['port'] = db_port
        service_secret['engine'] = 'sqlserver'
        
        secrets_client.update_secret(
            SecretId=service_secret_arn,
            SecretString=json.dumps(service_secret)
        )
        print("✓ Updated service secret with connection details")
        
        # Send success response to CloudFormation
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {
            'DatabaseName': service_dbname,
            'Username': service_username,
            'TableName': table_name,
            'Message': 'SQL Server database, user, and table initialized successfully'
        })
        
    except Exception as e:
        error_message = f"Error initializing SQL Server: {str(e)}"
        print(f"✗ {error_message}")
        import traceback
        traceback.print_exc()
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, reason=error_message)
