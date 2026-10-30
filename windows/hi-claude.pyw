"""Lanzador de Hi Claude! (pythonw hi-claude.pyw [--voice | --snip | --atajos | carpeta])."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hi_claude.launch import run  # noqa: E402

run()
