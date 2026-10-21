#!/usr/bin/env python3
"""Publish: commit any pending data changes and push to origin (GitHub).

Idempotent: if the tree is clean, it pushes nothing and exits 0 silently
(a no-op tick). If the push fails (network, auth) it exits non-zero with a
diagnostic so the cron agent can report the failure.

Usage: python3 publish.py [--no-push]
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*args, check=True):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{args[0]} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


def main():
    no_push = "--no-push" in sys.argv
    st = run("git", "status", "--porcelain").stdout.strip()
    if st:
        run("git", "add", "-A")
        run("git", "commit", "-m", "Nightly data refresh (auto)")
        print("committed pending data changes")
    else:
        print("tree clean, nothing to commit")

    if no_push:
        print("skipped push (--no-push)")
        return

    # Push; verify the remote actually received our HEAD.
    r = run("git", "push", "origin", "main")
    print(r.stdout.strip() or "pushed")
    local = run("git", "rev-parse", "HEAD").stdout.strip()
    remote = run("git", "ls-remote", "origin", "refs/heads/main").stdout.split()[0]
    if local != remote:
        raise RuntimeError(f"remote mismatch: local {local} != remote {remote}")
    print(f"published {local[:10]} to GitHub")


if __name__ == "__main__":
    main()
