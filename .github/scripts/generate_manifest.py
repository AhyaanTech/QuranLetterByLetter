#!/usr/bin/env python3
"""Generate manifest.json for a DB release."""
import json
import os
import sys


def main():
    version = os.environ["VERSION"]
    sha256 = os.environ["SHA256"]
    size_bytes = os.environ["SIZE_BYTES"]
    built_at = os.environ["BUILT_AT"]
    source_commit_sha = os.environ["GITHUB_SHA"]
    repo = os.environ["REPO"]

    tag = f"v{version}-merged"

    manifest = {
        "version": version,
        "sqlite_url": f"https://github.com/{repo}/releases/download/{tag}/quran_offline.db",
        "sha256": sha256,
        "size_bytes": int(size_bytes),
        "built_at": built_at,
        "source_commit_sha": source_commit_sha,
    }

    with open("manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Set GITHUB_OUTPUT for the release step
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"tag={tag}\n")


if __name__ == "__main__":
    main()