#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_command(cmd, cwd):
    print()
    print("$ " + " ".join(str(x) for x in cmd))

    completed = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        text=True,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with code {completed.returncode}: "
            + " ".join(str(x) for x in cmd)
        )


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_crop_path(crop_dir, image_path):
    expected = crop_dir / f"{image_path.stem}_crop.jpg"

    if expected.exists():
        return expected

    candidates = sorted(crop_dir.glob("*_crop.jpg"))

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise FileNotFoundError(
            f"Crop image not found in {crop_dir}"
        )

    raise RuntimeError(
        "Multiple crop candidates found, cannot choose automatically: "
        + ", ".join(str(p) for p in candidates)
    )


def build_summary(
    input_image,
    crop_path,
    raw_ocr_path,
    parsed_path,
    parsed,
):
    validation = parsed.get("validation") or {}
    validation_summary = validation.get("summary") or {}

    fields = {
        "last_name": parsed.get("last_name"),
        "first_name": parsed.get("first_name"),
        "middle_name": parsed.get("middle_name"),
        "birth_date": parsed.get("birth_date"),
        "sex": parsed.get("sex"),
        "birth_place": parsed.get("birth_place"),
        "issue_date": parsed.get("issue_date"),
        "department_code": parsed.get("department_code"),
        "issued_by": parsed.get("issued_by"),
        "document_number": parsed.get("document_number"),
    }

    return {
        "status": validation.get("status"),
        "input_image": str(input_image),
        "crop_image": str(crop_path),
        "raw_ocr_json": str(raw_ocr_path),
        "parsed_json": str(parsed_path),
        "fields": fields,
        "validation": {
            "status": validation.get("status"),
            "errors_count": validation_summary.get("errors_count"),
            "warnings_count": validation_summary.get("warnings_count"),
            "errors": validation.get("errors"),
            "warnings": validation.get("warnings"),
        },
    }


def print_summary(summary):
    print()
    print("=" * 80)
    print("PIPELINE SUMMARY")
    print("status:", summary.get("status"))
    print("input:", summary.get("input_image"))
    print("crop:", summary.get("crop_image"))
    print("raw_ocr:", summary.get("raw_ocr_json"))
    print("parsed:", summary.get("parsed_json"))

    print()
    print("FIELDS:")
    for key, value in summary["fields"].items():
        print(f"{key}: {value}")

    validation = summary.get("validation") or {}

    print()
    print("VALIDATION:")
    print("status:", validation.get("status"))
    print("errors_count:", validation.get("errors_count"))
    print("warnings_count:", validation.get("warnings_count"))

    if validation.get("errors"):
        print("errors:")
        for item in validation["errors"]:
            print(" ", item)

    if validation.get("warnings"):
        print("warnings:")
        for item in validation["warnings"]:
            print(" ", item)


def main():
    parser = argparse.ArgumentParser(
        description="Debug runner for full passport pipeline: crop -> OCR -> parse"
    )
    parser.add_argument(
        "input_image",
        help="Input passport spread image",
    )
    parser.add_argument(
        "--output-dir",
        default="debug/pipeline",
        help="Output directory for all intermediate files",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    input_image = Path(args.input_image)

    if not input_image.is_absolute():
        input_image = project_root / input_image

    input_image = input_image.resolve()

    if not input_image.exists():
        print(
            f"ERROR: input image not found: {input_image}",
            file=sys.stderr,
        )
        return 2

    output_dir = Path(args.output_dir)

    if not output_dir.is_absolute():
        output_dir = project_root / output_dir

    output_dir = output_dir.resolve()

    crop_dir = output_dir / "crop"
    ocr_dir = output_dir / "ocr"
    parse_dir = output_dir / "parse"

    crop_dir.mkdir(parents=True, exist_ok=True)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    parse_dir.mkdir(parents=True, exist_ok=True)

    image_stem = input_image.stem

    raw_ocr_path = ocr_dir / f"{image_stem}_raw_ocr.json"
    overlay_path = ocr_dir / f"{image_stem}_ocr_overlay.jpg"
    paddle_debug_dir = ocr_dir / image_stem
    parsed_path = parse_dir / f"{image_stem}_parsed.json"
    summary_path = output_dir / "summary.json"

    run_command(
        [
            sys.executable,
            "src/batch_test_crop.py",
            input_image,
            "--output-dir",
            crop_dir,
        ],
        cwd=project_root,
    )

    crop_path = find_crop_path(crop_dir, input_image)

    run_command(
        [
            sys.executable,
            "src/ocr_paddle.py",
            crop_path,
            "-o",
            raw_ocr_path,
            "--overlay",
            overlay_path,
            "--debug-dir",
            paddle_debug_dir,
        ],
        cwd=project_root,
    )

    run_command(
        [
            sys.executable,
            "src/parse_passport.py",
            raw_ocr_path,
            "-o",
            parsed_path,
        ],
        cwd=project_root,
    )

    parsed = load_json(parsed_path)

    summary = build_summary(
        input_image=input_image,
        crop_path=crop_path,
        raw_ocr_path=raw_ocr_path,
        parsed_path=parsed_path,
        parsed=parsed,
    )

    save_json(summary_path, summary)
    print_summary(summary)

    print()
    print(f"Saved summary: {summary_path}")

    if summary.get("status") == "error":
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())