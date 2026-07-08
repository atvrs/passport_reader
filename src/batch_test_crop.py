#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
}


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        return {
            "read_error": str(exc),
        }


def collect_images(inputs: list[str]) -> list[Path]:
    result = []

    for item in inputs:
        path = Path(item)

        if path.is_file():
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                result.append(path)
            continue

        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS:
                    result.append(child)

    unique = []
    seen = set()

    for path in result:
        resolved = path.resolve()

        if resolved in seen:
            continue

        seen.add(resolved)
        unique.append(path)

    return unique


def image_shape(path: Path) -> list[int] | None:
    img = cv2.imread(str(path))

    if img is None:
        return None

    h, w = img.shape[:2]

    return [
        int(h),
        int(w),
    ]


def run_one(
    crop_script: Path,
    image_path: Path,
    output_dir: Path,
) -> dict:
    stem = image_path.stem

    crop_path = output_dir / f"{stem}_crop.jpg"
    debug_dir = output_dir / stem

    debug_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(crop_script),
        str(image_path),
        "-o",
        str(crop_path),
        "--debug-dir",
        str(debug_dir),
    ]

    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    red_markers_info = read_json(debug_dir / "red_markers_info.json")
    crop_refine_info = read_json(debug_dir / "crop_refine_info.json")
    orientation_scores = read_json(debug_dir / "orientation_scores.json")
    red_fold_info = read_json(debug_dir / "red_fold_info.json")

    marker_info = red_markers_info.get("marker_info", {})
    refine_info = crop_refine_info

    if not refine_info:
        refine_info = red_markers_info.get("refine_info", {})

    item = {
        "input": str(image_path),
        "status": "ok" if completed.returncode == 0 else "error",
        "returncode": int(completed.returncode),
        "crop": str(crop_path),
        "debug_dir": str(debug_dir),
        "input_shape": image_shape(image_path),
        "crop_shape": image_shape(crop_path),
        "marker_found": bool(marker_info.get("found", False)),
        "marker_rotation": marker_info.get("rotation"),
        "fold_bbox": (
            marker_info.get("fold", {}).get("bbox")
            if marker_info.get("fold")
            else None
        ),
        "photo_marker_bbox": (
            marker_info.get("photo_marker", {}).get("bbox")
            if marker_info.get("photo_marker")
            else None
        ),
        "refine_applied": bool(refine_info.get("applied", False)),
        "refine_reason": refine_info.get("reason"),
        "refine_source_bbox": refine_info.get("source_bbox"),
        "red_fold_found_after_crop": bool(red_fold_info.get("found", False)),
        "orientation_scores_count": (
            len(orientation_scores)
            if isinstance(orientation_scores, list)
            else 0
        ),
        "stderr_tail": completed.stderr[-1200:],
        "stdout_tail": completed.stdout[-1200:],
    }

    return item


def main():
    parser = argparse.ArgumentParser(
        description="Batch regression runner for passport cropper.",
    )

    parser.add_argument(
        "inputs",
        nargs="+",
        help="Файлы изображений или папки с изображениями.",
    )

    parser.add_argument(
        "--output-dir",
        default="debug/batch_crop",
        help="Куда сохранять crop/debug/summary.",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    crop_script = project_root / "src" / "crop_passport.py"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    images = collect_images(args.inputs)

    if not images:
        raise RuntimeError("Не найдено изображений для обработки.")

    summary = []

    print(f"Найдено изображений: {len(images)}")

    for image_path in images:
        print(f"Обработка: {image_path}")

        item = run_one(
            crop_script=crop_script,
            image_path=image_path,
            output_dir=output_dir,
        )

        summary.append(item)

        print(
            "  "
            f"status={item['status']} "
            f"marker={item['marker_found']} "
            f"rotation={item['marker_rotation']} "
            f"refine={item['refine_applied']} "
            f"crop_shape={item['crop_shape']}"
        )

        if item["status"] != "ok":
            print("  ERROR:")
            print(item["stderr_tail"])

    summary_path = output_dir / "summary.json"

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            summary,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print(f"Готово: {summary_path}")


if __name__ == "__main__":
    main()