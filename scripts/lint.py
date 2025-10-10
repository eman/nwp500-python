#!/usr/bin/env python3
"""
Local linting script that mirrors the exact CI environment.
This ensures local and CI linting results are identical.
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n🔍 {description}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✓ {description} - PASSED")
        if result.stdout.strip():
            print(f"Output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} - FAILED")
        if e.stdout:
            print(f"STDOUT:\n{e.stdout}")
        if e.stderr:
            print(f"STDERR:\n{e.stderr}")
        return False
    except FileNotFoundError:
        print(f"❌ {description} - FAILED (ruff not found)")
        print("Install ruff with: python3 -m pip install ruff>=0.1.0")
        return False

def main():
    """Main linting function that mirrors tox lint environment."""
    
    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    print("🚀 Running local linting (mirroring CI environment)")
    print(f"Working directory: {project_root}")
    
    # Define the same commands used in tox.ini
    lint_commands = [
        (
            ["python3", "-m", "ruff", "check", "src/", "tests/", "examples/"],
            "Ruff linting check"
        ),
        (
            ["python3", "-m", "ruff", "format", "--check", "src/", "tests/", "examples/"],
            "Ruff format check"
        )
    ]
    
    all_passed = True
    
    for cmd, description in lint_commands:
        success = run_command(cmd, description)
        if not success:
            all_passed = False
    
    print("\n" + "="*50)
    if all_passed:
        print("🎉 All linting checks PASSED!")
        print("Your code matches the CI environment requirements.")
        return 0
    else:
        print("❌ Some linting checks FAILED!")
        print("Run the following commands to fix issues:")
        print("  python3 -m ruff check --fix src/ tests/ examples/")
        print("  python3 -m ruff format src/ tests/ examples/")
        return 1

if __name__ == "__main__":
    sys.exit(main())