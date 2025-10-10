#!/usr/bin/env python3
"""
Local formatting script that mirrors the tox format environment.
Auto-fixes linting issues and formats code consistently with CI.
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n🔧 {description}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✓ {description} - COMPLETED")
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
    """Main formatting function that mirrors tox format environment."""
    
    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    print("🚀 Running local formatting (mirroring tox format environment)")
    print(f"Working directory: {project_root}")
    
    # Define the same commands used in tox.ini format environment
    format_commands = [
        (
            ["python3", "-m", "ruff", "check", "--fix", "src/", "tests/", "examples/"],
            "Auto-fixing linting issues"
        ),
        (
            ["python3", "-m", "ruff", "format", "src/", "tests/", "examples/"],
            "Formatting code"
        )
    ]
    
    all_passed = True
    
    for cmd, description in format_commands:
        success = run_command(cmd, description)
        if not success:
            all_passed = False
    
    print("\n" + "="*50)
    if all_passed:
        print("🎉 All formatting COMPLETED successfully!")
        print("Your code is now formatted consistently with CI requirements.")
        return 0
    else:
        print("❌ Some formatting operations FAILED!")
        print("Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())