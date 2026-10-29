"""Wipe the database and reload the synthetic demo data.

    python -m scripts.reset_demo
"""
import sys

from scripts.seed_demo import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--reset"]
    main()
