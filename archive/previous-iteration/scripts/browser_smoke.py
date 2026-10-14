"""Compatibility entry point for the current Rider/Driver turn UI."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name('browser_rounds.py')),run_name='__main__')
