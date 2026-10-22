#!/usr/bin/env python3
"""Build this venue's shows.json from cache/events.json (shared build in
common/build_bellyup.py; the bill grammar lives in common/bill.py)."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
from build_bellyup import run_build
run_build()
