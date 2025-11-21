#!/usr/bin/env python3
"""Extract release notes from CHANGELOG.rst for a specific version."""

import re
import sys


def extract_version_notes(changelog_path: str, version: str) -> str:
    """
    Extract the changelog section for a specific version.
    
    Args:
        changelog_path: Path to CHANGELOG.rst
        version: Version string (e.g., "6.0.4")
    
    Returns:
        The changelog content for that version
    """
    with open(changelog_path, "r") as f:
        content = f.read()
    
    # Match the version header and capture everything until the next version
    # Pattern: "Version X.Y.Z (DATE)" followed by "===" line
    version_pattern = rf"Version {re.escape(version)} \([^)]+\)\n=+\n(.*?)(?=\nVersion \d+\.\d+\.\d+ \([^)]+\)\n=+|$)"
    
    match = re.search(version_pattern, content, re.DOTALL)
    if not match:
        return f"Release {version}"
    
    notes = match.group(1).strip()
    return notes


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: extract_changelog.py <changelog_path> <version>")
        sys.exit(1)
    
    changelog_path = sys.argv[1]
    version = sys.argv[2].lstrip("v")  # Remove 'v' prefix if present
    
    notes = extract_version_notes(changelog_path, version)
    print(notes)
