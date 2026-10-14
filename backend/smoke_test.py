"""Compatibility entry point for the repaired demo's real uvicorn/HTTP smoke."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'http_smoke.py'), run_name='__main__')
