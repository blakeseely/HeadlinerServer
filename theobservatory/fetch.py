#!/usr/bin/env python3
"""Fetch this venue's shows from the shared Belly Up Presents calendar.
The Belly Up group promotes all six San Diego rooms from one TicketWeb
calendar; common/fetch_bellyup.py is the shared implementation (one GET,
keeps only this venue's rows, writes cache/events.json)."""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
from fetch_bellyup import run
sys.exit(run())
