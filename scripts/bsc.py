#!/usr/bin/env python3
"""Run from any directory after cloning the complete repository."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bsc.cli import main
raise SystemExit(main())
