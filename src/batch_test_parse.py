#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import sys
from pathlib import Path

from parse_passport import build_output


DEFAULT_CASES = {
    "test1": {
        "input": "debug/ocr/test1_raw_ocr.json",
        "expected": {
            "last_name": "ТЕСТОВ",
            "first_name": "ТЕСТ",
            "middle_name": "ТЕСТОВИЧ",
            "sex": "МУЖ",
            "birth_date": "2099-01-31",
            "birth_place": "ГОР. ТЕСТОВСК",
            "issue_date": "2099-02-28",
            "department_code": "999-999",
            "issued_by": "ТЕСТОВЫМ ОТДЕЛОМ МВД ГОР. ТЕСТОВСКА",
        },
        "expected_format": {
            "document_number": r"^\d{4} \d{6}$",
        },
        "expected_validation": {
            "status": "ok",
            "errors_count": 0,
            "warnings_count": 0,
        },
    },
    "test2": {
        "input": "debug/ocr/test2_raw_ocr.json",
        "expected": {
            "last_name": "ТЕСТОВ",
            "first_name": "ТЕСТ",
            "middle_name": "ТЕСТОВИЧ",
            "sex": "МУЖ",
            "birth_date": "2099-01-31",
            "birth_place": "ГОР. ТЕСТОВСК",
            "issue_date": "2099-02-28",
            "department_code": "999-999",
            "issued_by": "ТЕСТОВЫМ ОТДЕЛОМ МВД ГОР. ТЕСТОВСКА",
        },
        "expected_format": {
            "document_number": r"^\d{4} \d{6}$",
        },
        "expected_validation": {
            "status": "ok",
            "errors_count": 0,
            "warnings_count": 0,
        },
    },
}


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def compare_validation(parsed, expected_validation):
    errors = []

    if not expected_validation:
        return errors

    validation = parsed.get("validation")

    if not isinstance(validation, dict):
        errors.append({
            "field": "validation",
            "expected": expected_validation,
            "actual": validation,
        })
        return errors

    expected_status = expected_validation.get("status")
    actual_status = validation.get("status")

    if expected_status is not None and actual_status != expected_status:
        errors.append({
            "field": "validation.status",
            "expected": expected_status,
            "actual": actual_status,
        })

    summary = validation.get("summary")
    if not isinstance(summary, dict):
        summary = {}

    expected_errors_count = expected_validation.get("errors_count")
    actual_errors_count = summary.get("errors_count")

    if (
        expected_errors_count is not None
        and actual_errors_count != expected_errors_count
    ):
        errors.append({
            "field": "validation.summary.errors_count",
            "expected": expected_errors_count,
            "actual": actual_errors_count,
        })

    expected_warnings_count = expected_validation.get("warnings_count")
    actual_warnings_count = summary.get("warnings_count")

    if (
        expected_warnings_count is not None
        and actual_warnings_count != expected_warnings_count
    ):
        errors.append({
            "field": "validation.summary.warnings_count",
            "expected": expected_warnings_count,
            "actual": actual_warnings_count,
        })

    return errors

def compare_fields(case_name, parsed, expected, expected_format=None):
    errors = []

    for field, expected_value in expected.items():
        actual_value = parsed.get(field)

        if actual_value != expected_value:
            errors.append({
                "field": field,
                "expected": expected_value,
                "actual": actual_value,
            })

    expected_format = expected_format or {}

    for field, pattern in expected_format.items():
        actual_value = parsed.get(field)

        if not isinstance(actual_value, str):
            errors.append({
                "field": field,
                "expected": f"format {pattern}",
                "actual": actual_value,
            })
            continue

        if re.fullmatch(pattern, actual_value) is None:
            errors.append({
                "field": field,
                "expected": f"format {pattern}",
                "actual": actual_value,
            })

    return errors


def print_case_result(
    case_name,
    parsed,
    expected,
    expected_format,
    expected_validation,
    errors,
):
    print()
    print("=" * 80)
    print(case_name)

    error_fields = {
        err["field"]
        for err in errors
    }

    for field in expected.keys():
        actual_value = parsed.get(field)

        if field in error_fields:
            status = "FAIL"
        else:
            status = "OK"

        print(f"{status:4} {field}: {actual_value!r}")

    for field, pattern in expected_format.items():
        actual_value = parsed.get(field)

        if field in error_fields:
            status = "FAIL"
        else:
            status = "OK"

        print(f"{status:4} {field}: {actual_value!r} / {pattern}")

    if expected_validation:
        validation = parsed.get("validation") or {}
        summary = validation.get("summary") or {}

        validation_checks = {
            "validation.status": validation.get("status"),
            "validation.summary.errors_count": summary.get("errors_count"),
            "validation.summary.warnings_count": summary.get("warnings_count"),
        }

        for field, actual_value in validation_checks.items():
            if field in error_fields:
                status = "FAIL"
            else:
                status = "OK"

            print(f"{status:4} {field}: {actual_value!r}")

    if errors:
        print()
        print("Errors:")
        for err in errors:
            print(
                f"  {err['field']}: "
                f"expected={err['expected']!r}, "
                f"actual={err['actual']!r}"
            )


def run_case(case_name, case_config, output_dir):
    input_path = Path(case_config["input"])
    expected = case_config["expected"]
    expected_format = case_config.get("expected_format", {})
    expected_validation = case_config.get("expected_validation", {})

    if not input_path.exists():
        return {
            "case": case_name,
            "status": "missing_input",
            "input": str(input_path),
            "errors": [{
                "field": "__input__",
                "expected": "file exists",
                "actual": "file not found",
            }],
        }

    raw_ocr = load_json(input_path)
    parsed = build_output(raw_ocr)

    output_path = output_dir / f"{case_name}_parsed.json"
    save_json(output_path, parsed)

    errors = compare_fields(
        case_name,
        parsed,
        expected,
        expected_format,
    )
    errors.extend(
        compare_validation(
            parsed,
            expected_validation,
        )
    )

    print_case_result(
        case_name,
        parsed,
        expected,
        expected_format,
        expected_validation,
        errors,
    )

    return {
        "case": case_name,
        "status": "ok" if not errors else "failed",
        "input": str(input_path),
        "output": str(output_path),
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Batch regression test for RF passport parser"
    )
    parser.add_argument(
        "--output-dir",
        default="debug/parse_regression",
        help="Directory for parsed JSON outputs and summary.json",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for case_name, case_config in DEFAULT_CASES.items():
        result = run_case(case_name, case_config, output_dir)
        results.append(result)

    summary = {
        "total": len(results),
        "ok": len([r for r in results if r["status"] == "ok"]),
        "failed": len([r for r in results if r["status"] != "ok"]),
        "results": results,
    }

    save_json(output_dir / "summary.json", summary)

    print()
    print("=" * 80)
    print("SUMMARY")
    print(f"total:  {summary['total']}")
    print(f"ok:     {summary['ok']}")
    print(f"failed: {summary['failed']}")
    print(f"saved:  {output_dir / 'summary.json'}")

    if summary["failed"] > 0:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())