#!/usr/bin/env python3
"""
Version validation script for nwp500-python.

This script checks for common version-related mistakes:
1. Verifies that setup.cfg [pyscaffold] version hasn't been changed
2. Ensures no hardcoded version strings exist in source code
3. Validates that pyproject.toml takes the version from git tags
   (setuptools_scm)

Run this as part of CI/CD or pre-commit hooks.
"""

import re
import sys
import tomllib
from pathlib import Path


def check_pyscaffold_version() -> bool:
    """Check that the PyScaffold version in setup.cfg hasn't been modified."""
    setup_cfg = Path("setup.cfg")

    if not setup_cfg.exists():
        print("Error: setup.cfg not found", file=sys.stderr)
        return False

    content = setup_cfg.read_text()

    # Look for the [pyscaffold] section
    pyscaffold_section = re.search(
        r"\[pyscaffold\].*?^version\s*=\s*(.+?)$",
        content,
        re.MULTILINE | re.DOTALL,
    )

    if not pyscaffold_section:
        print(
            "Warning: [pyscaffold] version not found in setup.cfg",
            file=sys.stderr,
        )
        return True  # Not a failure, just unexpected

    version = pyscaffold_section.group(1).strip()

    # PyScaffold version should be 4.6 (the version that created this project)
    if version != "4.6":
        print(
            f"setup.cfg [pyscaffold] version has been modified to {version}",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print(
            "The [pyscaffold] version field should always be 4.6",
            file=sys.stderr,
        )
        print(
            "This is the PyScaffold TOOL version, NOT the package version!",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print(
            "Package version is managed by setuptools_scm from git tags.",
            file=sys.stderr,
        )
        print(
            "Use 'make version-bump BUMP=patch' to create new versions.",
            file=sys.stderr,
        )
        print("", file=sys.stderr)
        print(
            "To fix: Change version back to 4.6 in [pyscaffold] section",
            file=sys.stderr,
        )
        return False

    return True


def check_hardcoded_versions() -> bool:
    """Check for hardcoded version strings in source code."""
    src_dir = Path("src/nwp500")

    if not src_dir.exists():
        print("Error: src/nwp500 directory not found", file=sys.stderr)
        return False

    # Version patterns to look for (excluding valid patterns)
    version_pattern = re.compile(
        r'__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']|'
        r'version\s*=\s*["\'](\d+\.\d+\.\d+)["\']'
    )

    found_issues = []

    for py_file in src_dir.rglob("*.py"):
        # Skip __init__.py which might import version from setuptools_scm
        if py_file.name == "__init__.py":
            continue

        content = py_file.read_text()
        matches = version_pattern.finditer(content)

        for match in matches:
            found_issues.append((py_file, match.group(0)))

    if found_issues:
        print("Hardcoded version strings found:", file=sys.stderr)
        for file_path, version_string in found_issues:
            print(f"  {file_path}: {version_string}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "Version should be derived from git tags via setuptools_scm.",
            file=sys.stderr,
        )
        print(
            "Remove hardcoded version strings from source code.",
            file=sys.stderr,
        )
        return False

    return True


def check_scm_version() -> bool:
    """Verify pyproject.toml takes the version from setuptools_scm."""
    pyproject = Path("pyproject.toml")

    if not pyproject.exists():
        print("Error: pyproject.toml not found", file=sys.stderr)
        return False

    config = tomllib.loads(pyproject.read_text())
    project = config.get("project", {})

    if "version" in project:
        print("pyproject.toml hardcodes [project] version", file=sys.stderr)
        return False

    if "version" not in project.get("dynamic", []) or (
        "setuptools_scm" not in config.get("tool", {})
    ):
        print(
            "pyproject.toml should list version in [project] dynamic and "
            "have a [tool.setuptools_scm] table",
            file=sys.stderr,
        )
        return False

    return True


def main() -> int:
    """Main entry point."""
    print("Running version validation checks...")
    print("")

    all_checks = [
        ("PyScaffold version", check_pyscaffold_version),
        ("Hardcoded versions", check_hardcoded_versions),
        ("setuptools_scm configuration", check_scm_version),
    ]

    results = []
    for check_name, check_func in all_checks:
        print(f"Checking {check_name}...", end=" ")
        result = check_func()
        results.append(result)
        if result:
            print("[OK]")
        else:
            print("✗")

    print("")

    if all(results):
        print("[OK] All version validation checks passed!")
        return 0
    else:
        print("[ERROR] Version validation failed!")
        print("")
        print("Common fixes:")
        print("  - Revert setup.cfg [pyscaffold] version to 4.6")
        print("  - Remove hardcoded __version__ strings from source code")
        print("  - Use 'make version-bump BUMP=patch' for version bumps")
        return 1


if __name__ == "__main__":
    sys.exit(main())
