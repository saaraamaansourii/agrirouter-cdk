#!/usr/bin/env python3
"""Validation script to test SQL Server connectivity using service credentials.

Run this after the CDK stack has been deployed.
"""

import boto3
import json
import sys

try:
    import pymssql
except ImportError:
    print("Warning: pymssql not installed. Install with: pip install pymssql")
    pymssql = None


def test_sqlserver_connection():
    """Test SQL Server connection using service credentials."""
    print("\n=== Testing SQL Server Connection ===")

    if not pymssql:
        print("Skipping SQL Server test (pymssql not installed)")
        return False

    try:
        secrets_client = boto3.client('secretsmanager')
        secret = json.loads(
            secrets_client.get_secret_value(SecretId='sqlserver-analytics-credentials')['SecretString']
        )

        print(f"Connecting to {secret['host']}:{secret['port']}/{secret['dbname']} as {secret['username']}")

        conn = pymssql.connect(
            server=secret['host'],
            port=secret['port'],
            user=secret['username'],
            password=secret['password'],
            database=secret['dbname'],
            timeout=10,
        )

        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION;")
        version = cursor.fetchone()[0]
        print("✓ Connected successfully!")
        print(f"  SQL Server version: {version[:80]}...")

        # Check if EventMetricsDev table exists
        table_name = secret.get('tablename', 'EventMetricsDev')
        cursor.execute(
            f"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = '{table_name}';"
        )
        table_exists = cursor.fetchone()[0]

        if table_exists:
            print(f"✓ Table '{table_name}' exists")

            # Test insert
            cursor.execute(
                f"""
                INSERT INTO [{table_name}] (event_name, metric_value, metadata)
                VALUES ('test_event', 123.45, '{{"test": true}}');
                """
            )
            conn.commit()

            # Test select
            cursor.execute(f"SELECT TOP 1 * FROM [{table_name}] ORDER BY id DESC;")
            _ = cursor.fetchone()
            print("✓ Service user has correct permissions (INSERT, SELECT)")

            # Clean up
            cursor.execute(f"DELETE FROM [{table_name}] WHERE event_name = 'test_event';")
            conn.commit()
        else:
            print(f"✗ Table '{table_name}' does not exist")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"✗ SQL Server connection failed: {e}")
        return False


def main():
    print("=" * 60)
    print("Database Service Credentials Validation")
    print("=" * 60)

    sqlserver_ok = test_sqlserver_connection()

    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  SQL Server: {'✓ PASS' if sqlserver_ok else '✗ FAIL'}")
    print("=" * 60)

    if sqlserver_ok:
        print("\n✓ SQL Server connection successful!")
        sys.exit(0)

    print("\n✗ SQL Server connection failed. Check the output above.")
    sys.exit(1)


if __name__ == '__main__':
    main()
