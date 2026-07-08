#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from .batch_test_crop import run_one as run_crop_one
    from .ocr_paddle import PassportOcrEngine, run_ocr_on_image
    from .parse_passport import build_output
except ImportError:
    from batch_test_crop import run_one as run_crop_one
    from ocr_paddle import PassportOcrEngine, run_ocr_on_image
    from parse_passport import build_output


OUTPUT_FIELDS = [
    "last_name",
    "first_name",
    "middle_name",
    "birth_date",
    "sex",
    "birth_place",
    "issue_date",
    "department_code",
    "issued_by",
    "document_number",
]


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


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def delete_file_if_exists(path):
    if path is None:
        return False

    path = Path(path)

    if not path.exists():
        return False

    if not path.is_file():
        return False

    path.unlink()
    return True

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


def empty_result_error(message, stage=None):
    result = {
        field: None
        for field in OUTPUT_FIELDS
    }

    result["validation"] = {
        "status": "error",
        "errors": [
            {
                "field": "__pipeline__",
                "code": "pipeline_failed",
                "message": message,
                "value": stage,
            }
        ],
        "warnings": [],
        "summary": {
            "errors_count": 1,
            "warnings_count": 0,
        },
    }

    result["pipeline"] = {
        "status": "error",
        "failed_stage": stage,
    }

    return result


def build_summary(
    input_image,
    output_json,
    crop_path=None,
    raw_ocr_path=None,
    parsed_path=None,
    result=None,
    status=None,
    failed_stage=None,
    error_message=None,
    input_deleted=False,
    timing_sec=None,
):
    validation = {}
    validation_summary = {}

    if isinstance(result, dict):
        validation = result.get("validation") or {}
        validation_summary = validation.get("summary") or {}

    return {
        "status": status,
        "failed_stage": failed_stage,
        "error_message": error_message,
        "input_image": str(input_image),
        "input_image_exists": (
            input_image.exists()
            if input_image else False
        ),
        "input_deleted": bool(input_deleted),
        "timing_sec": timing_sec or {},
        "output_json": str(output_json),
        "crop_image": str(crop_path) if crop_path else None,
        "raw_ocr_json": str(raw_ocr_path) if raw_ocr_path else None,
        "parsed_json": str(parsed_path) if parsed_path else None,
        "validation": {
            "status": validation.get("status"),
            "errors_count": validation_summary.get("errors_count"),
            "warnings_count": validation_summary.get("warnings_count"),
            "errors": validation.get("errors"),
            "warnings": validation.get("warnings"),
        },
        "fields": {
            field: result.get(field)
            for field in OUTPUT_FIELDS
        } if isinstance(result, dict) else {},
    }


def print_result_summary(summary):
    print()
    print("=" * 80)
    print("PROCESS PHOTO SUMMARY")
    print("status:", summary.get("status"))
    print("input:", summary.get("input_image"))
    print("input_exists:", summary.get("input_image_exists"))
    print("input_deleted:", summary.get("input_deleted"))
    print("output:", summary.get("output_json"))

    timing_sec = summary.get("timing_sec") or {}

    if timing_sec:
        print()
        print("TIMING_SEC:")
        for key in (
            "crop_sec",
            "ocr_sec",
            "parse_sec",
            "save_result_sec",
            "total_sec",
        ):
            if key in timing_sec:
                print(f"{key}: {timing_sec[key]}")

    if summary.get("failed_stage"):
        print("failed_stage:", summary.get("failed_stage"))
        print("error:", summary.get("error_message"))

    print()
    print("FIELDS:")
    for key, value in summary.get("fields", {}).items():
        print(f"{key}: {value}")

    validation = summary.get("validation") or {}

    print()
    print("VALIDATION:")
    print("status:", validation.get("status"))
    print("errors_count:", validation.get("errors_count"))
    print("warnings_count:", validation.get("warnings_count"))


def resolve_path(project_root, path_value):
    path = Path(path_value)

    if not path.is_absolute():
        path = project_root / path

    return path.resolve()


def process_photo(
    project_root,
    input_image,
    output_json,
    work_dir,
    debug_artifacts=False,
    delete_input=False,
    ocr_engine: PassportOcrEngine | None = None,
    ocr_max_side: int = 0,
):
    """
    Production pipeline for one passport photo.

    Обычный режим:
    - crop временно пишется во временную папку;
    - OCR результат остаётся в памяти;
    - parser работает в памяти;
    - на диске остаётся только output_json.

    Debug режим:
    - сохраняет crop;
    - сохраняет raw OCR JSON;
    - сохраняет OCR overlay;
    - сохраняет официальный Paddle debug;
    - сохраняет parsed debug JSON;
    - сохраняет summary.json.
    """
    total_started_at = time.perf_counter()
    timing_sec = {}
    crop_dir = work_dir / "crop"
    ocr_dir = work_dir / "ocr"
    parse_dir = work_dir / "parse"

    crop_dir.mkdir(parents=True, exist_ok=True)

    image_stem = input_image.stem

    raw_ocr_path = ocr_dir / f"{image_stem}_raw_ocr.json"
    overlay_path = ocr_dir / f"{image_stem}_ocr_overlay.jpg"
    paddle_debug_dir = ocr_dir / image_stem
    parsed_debug_path = parse_dir / f"{image_stem}_parsed_debug.json"
    summary_path = work_dir / "summary.json"

    crop_started_at = time.perf_counter()

    crop_result = run_crop_one(
        crop_script=project_root / "src" / "crop_passport.py",
        image_path=Path(input_image),
        output_dir=crop_dir,
    )

    if crop_result.get("status") != "ok":
        raise RuntimeError(
            "Crop failed: "
            f"returncode={crop_result.get('returncode')}; "
            f"stderr={crop_result.get('stderr_tail')}"
        )

    crop_path = Path(crop_result["crop"])

    if not crop_path.exists():
        raise RuntimeError(f"Crop output was not created: {crop_path}")

    timing_sec["crop_sec"] = round(
        time.perf_counter() - crop_started_at,
        3,
    )

    if debug_artifacts:
        ocr_dir.mkdir(parents=True, exist_ok=True)

        ocr_started_at = time.perf_counter()

        raw_ocr = run_ocr_on_image(
            image_path=crop_path,
            lang="ru",
            overlay_path=overlay_path,
            debug_dir=paddle_debug_dir,
            include_paddle_result=True,
            engine=ocr_engine,
            ocr_max_side=ocr_max_side,
        )

        timing_sec["ocr_sec"] = round(
            time.perf_counter() - ocr_started_at,
            3,
        )

        save_json(raw_ocr_path, raw_ocr)

        parse_started_at = time.perf_counter()

        debug_result = build_output(
            raw_ocr,
            include_debug=True,
        )

        save_json(parsed_debug_path, debug_result)

        result = build_output(
            raw_ocr,
            include_debug=False,
        )

        timing_sec["parse_sec"] = round(
            time.perf_counter() - parse_started_at,
            3,
        )

    else:
        ocr_started_at = time.perf_counter()

        raw_ocr = run_ocr_on_image(
            image_path=crop_path,
            lang="ru",
            overlay_path=None,
            debug_dir=None,
            include_paddle_result=False,
            engine=ocr_engine,
            ocr_max_side=ocr_max_side,
        )

        timing_sec["ocr_sec"] = round(
            time.perf_counter() - ocr_started_at,
            3,
        )

        parse_started_at = time.perf_counter()

        result = build_output(
            raw_ocr,
            include_debug=False,
        )

        timing_sec["parse_sec"] = round(
            time.perf_counter() - parse_started_at,
            3,
        )

        raw_ocr_path = None
        parsed_debug_path = None

    save_started_at = time.perf_counter()

    save_json(output_json, result)

    timing_sec["save_result_sec"] = round(
        time.perf_counter() - save_started_at,
        3,
    )
    timing_sec["total_sec"] = round(
        time.perf_counter() - total_started_at,
        3,
    )

    validation = result.get("validation") or {}
    validation_status = validation.get("status")

    status = "ok"
    exit_code = 0

    if validation_status == "error":
        status = "validation_error"
        exit_code = 1

    input_deleted = False

    if status == "ok" and delete_input:
        input_deleted = delete_file_if_exists(input_image)

    summary = build_summary(
        input_image=input_image,
        output_json=output_json,
        crop_path=crop_path if debug_artifacts else None,
        raw_ocr_path=raw_ocr_path if debug_artifacts else None,
        parsed_path=parsed_debug_path if debug_artifacts else None,
        result=result,
        status=status,
        input_deleted=input_deleted,
        timing_sec=timing_sec,
    )

    if debug_artifacts:
        save_json(summary_path, summary)

    return result, summary, exit_code


def main():
    parser = argparse.ArgumentParser(
        description="Production runner for one passport photo: crop -> OCR -> parse"
    )
    parser.add_argument(
        "input_image",
        help="Input passport spread image",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output JSON path for 1C",
    )
    parser.add_argument(
        "--work-dir",
        default="debug/process_photo",
        help=(
            "Directory for debug artifacts. "
            "Used only with --debug-artifacts."
        ),
    )
    parser.add_argument(
        "--ocr-max-side",
        type=int,
        default=0,
        help=(
            "Resize OCR input so the longest side is not larger than this value. "
            "Use 0 to disable. Default: 0"
        ),
    )
    parser.add_argument(
        "--debug-artifacts",
        action="store_true",
        help=(
            "Save intermediate artifacts: crop, raw OCR JSON, "
            "OCR overlay, PaddleOCR debug, parsed debug JSON and summary"
        ),
    )

    parser.add_argument(
        "--keep-input",
        action="store_true",
        help="Do not delete input image after successful processing",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]

    input_image = resolve_path(project_root, args.input_image)
    output_json = resolve_path(project_root, args.output)
    configured_work_dir = resolve_path(project_root, args.work_dir)

    try:
        if not input_image.exists():
            raise FileNotFoundError(
                f"Input image not found: {input_image}"
            )

        if args.debug_artifacts:
            work_dir = configured_work_dir
            work_dir.mkdir(parents=True, exist_ok=True)

            result, summary, exit_code = process_photo(
                project_root=project_root,
                input_image=input_image,
                output_json=output_json,
                work_dir=work_dir,
                debug_artifacts=True,
                delete_input=not args.keep_input,
            )

            print_result_summary(summary)

            print()
            print(f"Saved output: {output_json}")
            print(f"Saved debug work dir: {work_dir}")
            print(f"Saved summary: {work_dir / 'summary.json'}")

            return exit_code

        with tempfile.TemporaryDirectory(
            prefix="passport_reader_"
        ) as temp_dir:
            work_dir = Path(temp_dir)

            result, summary, exit_code = process_photo(
                project_root=project_root,
                input_image=input_image,
                output_json=output_json,
                work_dir=work_dir,
                ocr_max_side=args.ocr_max_side,
                debug_artifacts=False,
                delete_input=not args.keep_input,
            )

            print_result_summary(summary)

            print()
            print(f"Saved output: {output_json}")

            return exit_code

    except Exception as exc:
        error_result = empty_result_error(
            message=str(exc),
            stage="pipeline",
        )

        save_json(output_json, error_result)

        summary = build_summary(
            input_image=input_image,
            output_json=output_json,
            result=error_result,
            status="error",
            failed_stage="pipeline",
            error_message=str(exc),
        )

        if args.debug_artifacts:
            configured_work_dir.mkdir(parents=True, exist_ok=True)
            save_json(configured_work_dir / "summary.json", summary)

        print_result_summary(summary)

        print()
        print(f"Saved error output: {output_json}")

        if args.debug_artifacts:
            print(f"Saved summary: {configured_work_dir / 'summary.json'}")

        return 2


if __name__ == "__main__":
    raise SystemExit(main())