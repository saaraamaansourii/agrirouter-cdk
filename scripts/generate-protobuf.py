#!/usr/bin/env python3
"""
Protobuf Code Generation Script

This script generates Python protobuf files from the .proto definitions
in the api/proto/ directory for use in Kafka message simulation.

Usage:
    python3 generate-protobuf.py [--clean] [--verbose]

Generated files will be placed in scripts/generated_pb/
"""

import os
import sys
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List, Set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ProtobufGenerator:
    """Generates Python protobuf files from .proto definitions"""
    
    def __init__(self, proto_dir: Path, output_dir: Path):
        self.proto_dir = proto_dir
        self.output_dir = output_dir
        self.proto_files: List[Path] = []
        
    def discover_proto_files(self) -> None:
        """Discover all .proto files in the proto directory"""
        logger.info(f"🔍 Discovering .proto files in {self.proto_dir}")
        
        self.proto_files = list(self.proto_dir.rglob("*.proto"))
        logger.info(f"✓ Found {len(self.proto_files)} .proto files")
        
        for proto_file in self.proto_files:
            relative_path = proto_file.relative_to(self.proto_dir)
            logger.info(f"  📄 {relative_path}")
    
    def prepare_output_directory(self, clean: bool = False) -> None:
        """Prepare the output directory for generated files"""
        if clean and self.output_dir.exists():
            logger.info(f"🧹 Cleaning existing output directory: {self.output_dir}")
            shutil.rmtree(self.output_dir)
        
        logger.info(f"📁 Creating output directory: {self.output_dir}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create __init__.py files for Python package structure
        self._create_init_files()
    
    def _create_init_files(self) -> None:
        """Create __init__.py files in all subdirectories"""
        # Main __init__.py
        (self.output_dir / "__init__.py").touch()
        
        # Create __init__.py for each service subdirectory
        service_dirs: Set[Path] = set()
        
        for proto_file in self.proto_files:
            relative_path = proto_file.relative_to(self.proto_dir)
            if len(relative_path.parts) > 1:  # Has subdirectory
                service_dir = self.output_dir / relative_path.parts[0]
                service_dirs.add(service_dir)
        
        for service_dir in service_dirs:
            service_dir.mkdir(exist_ok=True)
            (service_dir / "__init__.py").touch()
            logger.info(f"📦 Created package: {service_dir.relative_to(self.output_dir)}")
    
    def generate_python_files(self, verbose: bool = False) -> bool:
        """Generate Python files from .proto definitions"""
        logger.info("🔨 Generating Python protobuf files...")
        
        success_count = 0
        error_count = 0
        
        for proto_file in self.proto_files:
            try:
                if self._compile_proto_file(proto_file, verbose):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"✗ Failed to compile {proto_file.name}: {e}")
                error_count += 1
        
        logger.info(f"📊 Compilation complete: {success_count} success, {error_count} errors")
        
        if error_count == 0:
            logger.info("🎉 All protobuf files compiled successfully!")
            return True
        else:
            logger.warning(f"⚠️  {error_count} files failed to compile")
            return False
    
    def _compile_proto_file(self, proto_file: Path, verbose: bool = False) -> bool:
        """Compile a single .proto file to Python"""
        relative_path = proto_file.relative_to(self.proto_dir)
        logger.info(f"🔨 Compiling: {relative_path}")
        
        # Build protoc command
        cmd = [
            "python3", "-m", "grpc_tools.protoc",
            f"--proto_path={self.proto_dir.resolve()}",  # Absolute source directory
            f"--python_out={self.output_dir.resolve()}",  # Absolute output directory
            str(proto_file.resolve())  # Absolute proto file path
        ]
        
        if verbose:
            logger.info(f"💻 Command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=Path.cwd()  # Run from current working directory
            )
            
            if verbose and result.stdout:
                logger.info(f"📤 stdout: {result.stdout}")
            
            logger.info(f"✓ Successfully compiled: {relative_path}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"✗ Failed to compile {relative_path}")
            logger.error(f"   Exit code: {e.returncode}")
            if e.stdout:
                logger.error(f"   stdout: {e.stdout}")
            if e.stderr:
                logger.error(f"   stderr: {e.stderr}")
            return False
        except FileNotFoundError:
            logger.error("✗ protoc compiler not found!")
            logger.error("   Install with: pip install grpcio-tools")
            return False
    
    def create_convenience_imports(self) -> None:
        """Create convenience import file for easy access to generated classes"""
        import_file = self.output_dir / "imports.py"
        
        logger.info("📝 Creating convenience imports file...")
        
        imports = []
        imports.append('"""')
        imports.append('Convenience imports for generated protobuf classes')
        imports.append('')
        imports.append('This file provides easy access to all generated protobuf message classes')
        imports.append('for use in Kafka message simulation.')
        imports.append('"""')
        imports.append('')
        
        # Scan for generated _pb2.py files
        pb_files = list(self.output_dir.rglob("*_pb2.py"))
        
        for pb_file in sorted(pb_files):
            relative_path = pb_file.relative_to(self.output_dir)
            module_path = str(relative_path).replace("/", ".").replace("\\", ".")[:-3]  # Remove .py
            
            # Try to determine class names by parsing the file
            try:
                with open(pb_file, 'r') as f:
                    content = f.read()
                    
                # Look for class definitions (simplified parsing)
                class_names = []
                for line in content.split('\n'):
                    if line.startswith('class ') and 'Message' in line:
                        class_name = line.split('(')[0].replace('class ', '')
                        if not class_name.startswith('_'):
                            class_names.append(class_name)
                
                if class_names:
                    imports.append(f"# {relative_path}")
                    for class_name in class_names:
                        imports.append(f"from {module_path} import {class_name}")
                    imports.append("")
                    
            except Exception as e:
                logger.warning(f"⚠️  Could not parse {pb_file}: {e}")
        
        # Write the imports file
        with open(import_file, 'w') as f:
            f.write('\n'.join(imports))
        
        logger.info(f"✓ Created convenience imports: {import_file}")
    
    def verify_installation(self) -> bool:
        """Verify that protobuf tools are installed"""
        logger.info("🔍 Verifying protobuf tools installation...")
        
        try:
            # Check if grpc_tools.protoc is available
            result = subprocess.run(
                ["python3", "-m", "grpc_tools.protoc", "--version"],
                capture_output=True,
                text=True,
                check=True
            )
            
            version = result.stdout.strip()
            logger.info(f"✓ protoc version: {version}")
            return True
            
        except subprocess.CalledProcessError:
            logger.error("✗ protoc compiler not working properly")
            return False
        except FileNotFoundError:
            logger.error("✗ grpc_tools.protoc not found")
            logger.error("   Install with: pip install grpcio-tools protobuf")
            return False
    
    def generate_summary_report(self) -> None:
        """Generate a summary report of generated files"""
        logger.info("📊 Generating summary report...")
        
        pb_files = list(self.output_dir.rglob("*_pb2.py"))
        logger.info(f"📈 Generated {len(pb_files)} Python protobuf files:")
        
        for pb_file in sorted(pb_files):
            relative_path = pb_file.relative_to(self.output_dir)
            file_size = pb_file.stat().st_size
            logger.info(f"  📄 {relative_path} ({file_size:,} bytes)")
        
        # List available message classes
        total_classes = 0
        for pb_file in pb_files:
            try:
                with open(pb_file, 'r') as f:
                    content = f.read()
                    class_count = len([line for line in content.split('\n') 
                                     if line.startswith('class ') and 'Message' in line 
                                     and not line.split('(')[0].replace('class ', '').startswith('_')])
                    total_classes += class_count
            except Exception:
                pass
        
        logger.info(f"🎯 Total message classes: {total_classes}")
        logger.info(f"📁 Output directory: {self.output_dir}")


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate Python protobuf files from .proto definitions')
    parser.add_argument('--clean', action='store_true', 
                       help='Clean output directory before generation')
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--proto-dir', type=str,
                       help='Path to proto files directory (default: api/proto)')
    parser.add_argument('--output-dir', type=str,
                       help='Output directory for generated files (default: scripts/generated_pb)')
    
    args = parser.parse_args()
    
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    proto_dir = Path(args.proto_dir) if args.proto_dir else project_root / "api" / "proto"
    output_dir = Path(args.output_dir) if args.output_dir else script_dir / "generated_pb"
    
    # Validate proto directory exists
    if not proto_dir.exists():
        logger.error(f"✗ Proto directory not found: {proto_dir}")
        return 1
    
    try:
        # Initialize generator
        generator = ProtobufGenerator(proto_dir, output_dir)
        
        # Verify installation
        if not generator.verify_installation():
            logger.error("✗ Protobuf tools not properly installed")
            logger.info("Install with: pip install grpcio-tools protobuf")
            return 1
        
        # Discover proto files
        generator.discover_proto_files()
        
        if not generator.proto_files:
            logger.warning("⚠️  No .proto files found")
            return 0
        
        # Prepare output directory
        generator.prepare_output_directory(clean=args.clean)
        
        # Generate Python files
        success = generator.generate_python_files(verbose=args.verbose)
        
        if success:
            # Create convenience imports
            generator.create_convenience_imports()
            
            # Generate summary
            generator.generate_summary_report()
            
            logger.info("🎉 Protobuf generation completed successfully!")
            return 0
        else:
            logger.error("✗ Protobuf generation failed")
            return 1
            
    except KeyboardInterrupt:
        logger.info("🛑 Generation interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"✗ Unexpected error: {e}")
        return 1


if __name__ == '__main__':
    exit(main())