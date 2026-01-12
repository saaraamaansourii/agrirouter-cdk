#!/usr/bin/env python3
"""
Quick dependency check for Kafka message simulation

This script verifies that all required Python packages are installed
in the virtual environment before running simulations.
"""

import sys
import importlib
from pathlib import Path

def check_dependency(package_name, import_name=None):
    """Check if a package can be imported"""
    if import_name is None:
        import_name = package_name
    
    try:
        importlib.import_module(import_name)
        print(f"✓ {package_name}")
        return True
    except ImportError:
        print(f"✗ {package_name} - MISSING")
        return False

def main():
    """Check all required dependencies"""
    print("🔍 Checking dependencies for Kafka message simulation...")
    print("=" * 60)
    
    dependencies = [
        ("boto3", "boto3"),
        ("kafka-python", "kafka"),
        ("psycopg2-binary", "psycopg2"),
        ("pymssql", "pymssql"),
    ]
    
    all_good = True
    for package, import_name in dependencies:
        if not check_dependency(package, import_name):
            all_good = False
    
    print("=" * 60)
    
    if all_good:
        print("🎉 All dependencies are installed!")
        print("\nReady to run simulations:")
        print("  python3 scripts/simulate-kafka-messages.py --help")
        print("  python3 scripts/example-simulations.py")
        return 0
    else:
        print("❌ Some dependencies are missing!")
        print("\nTo install missing dependencies:")
        print("  pip install -r scripts/requirements.txt")
        print("\nOr activate the virtual environment first:")
        print("  source scripts/venv/bin/activate")
        print("  pip install -r scripts/requirements.txt")
        return 1

if __name__ == '__main__':
    exit(main())