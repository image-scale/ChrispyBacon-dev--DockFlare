"""Pytest configuration and fixtures."""

import pytest
import os
import sys

# Add source directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
