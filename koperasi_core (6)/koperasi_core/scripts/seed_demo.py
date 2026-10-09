#!/usr/bin/env python3
"""
Seed demo data for development and demonstration testing.
DO NOT RUN IN PRODUCTION.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.seed_data import seed_all

if __name__ == "__main__":
    seed_all()
