#!/usr/bin/env python3
"""
Development environment setup script.
Installs the minimal dependencies needed for local linting that matches CI.
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
        print(f"✓ {description} - SUCCESS")
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
        print(f"❌ {description} - FAILED (command not found)")
        return False

def main():
    """Set up development environment."""
    
    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    print("🚀 Setting up development environment")
    print(f"Working directory: {project_root}")
    
    # Install ruff for linting (matches CI requirement)
    install_commands = [
        (
            [sys.executable, "-m", "pip", "install", "--user", "ruff>=0.1.0"],
            "Installing ruff (linter/formatter)"
        )
    ]
    
    all_passed = True
    
    for cmd, description in install_commands:
        success = run_command(cmd, description)
        if not success:
            all_passed = False
    
    print("\n" + "="*50)
    if all_passed:
        print("🎉 Development environment setup COMPLETED!")
        print()
        print("Next steps:")
        print("  1. Run linting: make ci-lint")
        print("  2. Auto-format: make ci-format") 
        print("  3. Full check:  make ci-check")
        print()
        print("Or use the scripts directly:")
        print("  python3 scripts/lint.py")
        print("  python3 scripts/format.py")
        return 0
    else:
        print("❌ Development environment setup FAILED!")
        print("Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(main())