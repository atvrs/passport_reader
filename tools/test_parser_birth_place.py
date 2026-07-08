#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression tests for RF passport birth_place normalization.

Run from repository root:

    cd /opt/passport_reader
    python3 tools/test_parser_birth_place.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from parse_passport import (  # noqa: E402
    clean_birth_place_line,
    is_empty_birth_place_value,
    normalize_birth_place_value,
    normalize_text,
)


def assert_equal(raw, got, expected):
    print(f"{raw!r} -> {got!r}")
    if got != expected:
        raise AssertionError(
            f"expected {expected!r}, got {got!r} for raw {raw!r}"
        )


def main():
    cases = {
        "ГОР.ТЕСТОВСК": "ГОР. ТЕСТОВСК",
        "ГОР. ТЕСТОВСК": "ГОР. ТЕСТОВСК",
        "ГОP.ТЕСТОВСК": "ГОР. ТЕСТОВСК",   # Latin P
        "ГОП.ТЕСТОВСК": "ГОР. ТЕСТОВСК",   # Cyrillic П
        "ФОП.ТЕСТОВСК": "ГОР. ТЕСТОВСК",
        "Г0Р.ТЕСТОВСК": "ГОР. ТЕСТОВСК",   # zero instead of О
        "Г О Р. ТЕСТОВСК": "ГОР. ТЕСТОВСК",
        "Г О П. ТЕСТОВСК": "ГОР. ТЕСТОВСК",
        "МЕСТО РОЖДЕНИЯ ГОП.ТЕСТОВСК": "ГОР. ТЕСТОВСК",
        "С. НОВОЕ": "С. НОВОЕ",
        "Р-Н ТЕСТОВСКИЙ": "Р-Н ТЕСТОВСКИЙ",
    }

    print("=== normalize_text diagnostic ===")
    for raw in ["ГОP.ТЕСТОВСК", "ГОП.ТЕСТОВСК", "ФОП.ТЕСТОВСК"]:
        print(f"normalize_text({raw!r}) -> {normalize_text(raw)!r}")

    print()
    print("=== normalize_birth_place_value ===")
    for raw, expected in cases.items():
        # For label-containing input normalize_birth_place_value intentionally
        # does not remove labels; clean_birth_place_line does.
        if raw.startswith("МЕСТО"):
            continue
        assert_equal(raw, normalize_birth_place_value(raw), expected)

    print()
    print("=== clean_birth_place_line ===")
    for raw, expected in cases.items():
        assert_equal(raw, clean_birth_place_line(raw), expected)

    print()
    print("=== empty checks ===")
    empty_cases = [
        "",
        "МЕСТО РОЖДЕНИЯ",
        "ДАТА РОЖДЕНИЯ",
        "ПОЛ",
        "МУЖ",
    ]
    for raw in empty_cases:
        cleaned = clean_birth_place_line(raw)
        result = is_empty_birth_place_value(cleaned)
        print(f"{raw!r} -> cleaned={cleaned!r}, empty={result}")
        if not result:
            raise AssertionError(f"expected empty birth_place for {raw!r}")

    print()
    print("OK: birth_place parser regression tests passed")


if __name__ == "__main__":
    raise SystemExit(main())
