#!/usr/bin/env python3
"""Compatibility entrypoint for the shared family checker."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zhiqu-shared/scripts'))
from family_check import *
if __name__ == '__main__':
    main()
