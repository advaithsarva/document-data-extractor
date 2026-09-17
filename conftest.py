"""Put backend/ on sys.path so pytest can collect backend/test_extract.py.

The suite is a standalone script -- `python backend/test_extract.py` -- which
imports its module as `data_extractor`, relying on the script's own directory
being on sys.path. pytest imports the file from the repo root instead, where
that is not true, so collection failed with an ImportError. Two lines here
means both entry points work; the script one stays the documented way to run it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))
