#!/usr/bin/env python3
"""
Version bump script for nwp500-python.

This script helps create new releases by:
1. Getting the current version from git tags
2. Computing the next version based on bump type (major, minor, patch)
3. Validating the new version
4. Creating a new git tag

Usage:
    python scripts/bump_version.py patch   # 3.1.4 -> 3.1.5
    python scripts/bump_version.py minor   # 3.1.4 -> 3.2.0
    python scripts/bump_version.py major   # 3.1.4 -> 4.0.0
    python scripts/bump_version.py 3.1.5   # Explicit version

The script uses setuptools_scm to derive versions from git tags.
DO NOT manually edit version numbers in setup.cfg - the [pyscaffold] version
field is for the PyScaffold tool version, not the package version!
"""

import re
import subprocess
import sys


def run_git_command(args: list) -> str:
    """Run a git command and return the output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running git command: {e}", file=sys.stderr)
        print(f"stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def get_current_version() -> str:
    """Get the current version from git tags."""
    # Get all tags sorted by version
    tags_output = run_git_command(
        ["tag", "-l", "v*", "--sort=-version:refname"]
    )

    if not tags_output:
        print("No version tags found. Starting from v0.0.0")
        return "0.0.0"

    # Get the most recent tag
    latest_tag = tags_output.split("\n")[0]

    # Remove the 'v' prefix
    version = latest_tag[1:] if latest_tag.startswith("v") else latest_tag

    return version


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse a version string into (major, minor, patch) tuple."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version_str)
    if not match:
        print(f"Error: Invalid version format: {version_str}", file=sys.stderr)
        print("Version must be in format: X.Y.Z", file=sys.stderr)
        sys.exit(1)

    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_version(version_str: str, bump_type: str) -> str:
    """Bump a version string according to the bump type."""
    major, minor, patch = parse_version(version_str)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        # Assume it's an explicit version number
        parse_version(bump_type)  # Validate format
        return bump_type


def validate_version_progression(current: str, new: str) -> None:
    """Validate that the new version is a proper progression from current."""
    curr_major, curr_minor, curr_patch = parse_version(current)
    new_major, new_minor, new_patch = parse_version(new)

    # Check if new version is greater than current
    curr_tuple = (curr_major, curr_minor, curr_patch)
    new_tuple = (new_major, new_minor, new_patch)

    if new_tuple <= curr_tuple:
        print(
            f"Error: New version {new} is not greater than current version "
            f"{current}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Check for unreasonable jumps
    major_jump = new_major - curr_major
    minor_jump = new_minor - curr_minor
    patch_jump = new_patch - curr_patch

    if major_jump > 1:
        print(
            f"Warning: Large major version jump detected ({current} -> {new})"
        )
        print(f"This will jump from {curr_major}.x.x to {new_major}.x.x")

    if major_jump == 0 and minor_jump > 5:
        print(
            f"Warning: Large minor version jump detected ({current} -> {new})"
        )
        print(f"This will jump from x.{curr_minor}.x to x.{new_minor}.x")

    if major_jump == 0 and minor_jump == 0 and patch_jump > 10:
        print(
            f"Warning: Large patch version jump detected ({current} -> {new})"
        )
        print(f"This will jump from x.x.{curr_patch} to x.x.{new_patch}")


def check_working_directory_clean() -> None:
    """Check if the git working directory is clean."""
    status = run_git_command(["status", "--porcelain"])
    if status:
        print("Error: Working directory is not clean.", file=sys.stderr)
        print(
            "Please commit or stash your changes before bumping version.",
            file=sys.stderr,
        )
        sys.exit(1)


def create_tag(version: str, message: str = None) -> None:
    """Create a git tag for the version."""
    tag_name = f"v{version}"

    # Check if tag already exists
    try:
        subprocess.run(
            ["git", "rev-parse", tag_name],
            capture_output=True,
            check=True,
        )
        print(f"Error: Tag {tag_name} already exists.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError:
        # Tag doesn't exist, which is what we want
        pass

    # Create the tag
    if message:
        run_git_command(["tag", "-a", tag_name, "-m", message])
    else:
        run_git_command(
            ["tag", "-a", tag_name, "-m", f"Release version {version}"]
        )

    print(f"[OK] Created tag: {tag_name}")


def main() -> None:
    """Main entry point."""
    if len(sys.argv) != 2:
        print(
            "Usage: python scripts/bump_version.py [major|minor|patch|X.Y.Z]",
            file=sys.stderr,
        )
        print("\nExamples:", file=sys.stderr)
        print(
            "  python scripts/bump_version.py patch   # Bump patch version",
            file=sys.stderr,
        )
        print(
            "  python scripts/bump_version.py minor   # Bump minor version",
            file=sys.stderr,
        )
        print(
            "  python scripts/bump_version.py major   # Bump major version",
            file=sys.stderr,
        )
        print(
            "  python scripts/bump_version.py 3.1.5   # Set explicit version",
            file=sys.stderr,
        )
        sys.exit(1)

    bump_type = sys.argv[1]

    # Validate bump type
    if bump_type not in ["major", "minor", "patch"]:
        # Check if it's a valid version number
        try:
            parse_version(bump_type)
        except SystemExit:
            print(f"Error: Invalid bump type: {bump_type}", file=sys.stderr)
            print(
                "Must be one of: major, minor, patch, or X.Y.Z",
                file=sys.stderr,
            )
            sys.exit(1)

    # Check working directory is clean
    check_working_directory_clean()

    # Get current version
    current_version = get_current_version()
    print(f"Current version: {current_version}")

    # Calculate new version
    new_version = bump_version(current_version, bump_type)
    print(f"New version:     {new_version}")

    # Validate version progression
    validate_version_progression(current_version, new_version)

    # Create the tag
    print(f"\nCreating tag v{new_version}...")
    create_tag(new_version)

    print("\n[OK] Version bump complete!")
    print("\nNext steps:")
    print(f"  1. Push the tag:    git push origin v{new_version}")
    print("  2. Build release:   make build")
    print("  3. Test on TestPyPI: make publish-test")
    print("  4. Publish to PyPI:  make publish")


if __name__ == "__main__":
    main()
