"""Benchmark SQL validation tests."""
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.benchmark import validate_readonly_sql


def test_validate_select_ok():
    assert validate_readonly_sql("SELECT 1").startswith("SELECT")


def test_validate_rejects_insert():
    with pytest.raises(ValueError, match="SELECT"):
        validate_readonly_sql("INSERT INTO runs VALUES (1)")


def test_validate_rejects_multi_statement():
    with pytest.raises(ValueError, match="multi-statement"):
        validate_readonly_sql("SELECT 1; SELECT 2")
