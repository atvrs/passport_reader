#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import fcntl
import json
import logging
import shutil
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ocr_paddle import PassportOcrEngine
from process_photo import process_photo


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
}

DEFAULT_LOG_TOTAL_MAX_MB = 100
DEFAULT_LOG_FILES_COUNT = 5
OUT_CLEANUP_INTERVAL_SEC = 3600

def acquire_service_lock(lock_file):
    lock_file = Path(lock_file)
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    handle = lock_file.open("w", encoding="utf-8")

    try:
        fcntl.flock(
            handle.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
    except BlockingIOError:
        handle.close()
        raise RuntimeError(
            f"Another passport service instance is already running. Lock file: {lock_file}"
        )

    handle.seek(0)
    handle.truncate()
    handle.write(
        f"pid={os_getpid_safe()}\n"
        f"locked_at={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    handle.flush()

    return handle


def os_getpid_safe():
    try:
        import os

        return os.getpid()
    except Exception:
        return "unknown"

def configure_logging(
    log_file,
    log_total_max_mb=DEFAULT_LOG_TOTAL_MAX_MB,
    log_files_count=DEFAULT_LOG_FILES_COUNT,
):
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    log_files_count = max(1, int(log_files_count))
    total_bytes = max(1, int(log_total_max_mb)) * 1024 * 1024
    max_bytes = max(1024 * 1024, total_bytes // log_files_count)
    backup_count = max(0, log_files_count - 1)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logging.info(
        "Logging configured: file=%s, total_max_mb=%s, files_count=%s, file_max_mb=%.2f",
        log_file,
        log_total_max_mb,
        log_files_count,
        max_bytes / 1024 / 1024,
    )

def load_json(path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    tmp_path.replace(path)

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_service_status(status_file, status_data):
    status_data = dict(status_data)
    status_data["last_heartbeat_at"] = now_iso()

    save_json_atomic(status_file, status_data)

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


def move_file_to_dir(path, target_dir):
    path = Path(path)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        return None

    target_path = target_dir / path.name

    if target_path.exists():
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target_path = target_dir / f"{path.stem}_{stamp}{path.suffix}"

    shutil.move(str(path), str(target_path))

    return target_path

def sanitize_archive_name(value):
    text = str(value or "").strip()

    safe_chars = []
    for char in text:
        if char.isalnum() or char in ("-", "_", "."):
            safe_chars.append(char)
        else:
            safe_chars.append("_")

    safe = "".join(safe_chars).strip("._")

    if not safe:
        return "request"

    return safe[:120]


def get_dir_size_bytes(path):
    path = Path(path)

    if not path.exists():
        return 0

    total = 0

    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue

    return total


def remove_empty_archive_month_dirs(archive_dir):
    archive_dir = Path(archive_dir)

    if not archive_dir.exists():
        return

    for month_dir in sorted(archive_dir.iterdir()):
        if not month_dir.is_dir():
            continue

        try:
            next(month_dir.iterdir())
        except StopIteration:
            month_dir.rmdir()
        except OSError:
            continue


def cleanup_archive_by_retention_days(archive_dir, retention_days):
    archive_dir = Path(archive_dir)

    if retention_days is None or retention_days <= 0:
        return []

    if not archive_dir.exists():
        return []

    cutoff_date = (
        datetime.now().date() - timedelta(days=int(retention_days))
    )

    removed = []

    for month_dir in sorted(archive_dir.iterdir()):
        if not month_dir.is_dir():
            continue

        for day_dir in sorted(month_dir.iterdir()):
            if not day_dir.is_dir():
                continue

            try:
                day_value = datetime.strptime(
                    day_dir.name,
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                continue

            if day_value < cutoff_date:
                shutil.rmtree(day_dir)
                removed.append(day_dir)

    remove_empty_archive_month_dirs(archive_dir)

    return removed


def list_archive_request_dirs(archive_dir):
    archive_dir = Path(archive_dir)

    if not archive_dir.exists():
        return []

    request_dirs = []

    for month_dir in archive_dir.iterdir():
        if not month_dir.is_dir():
            continue

        for day_dir in month_dir.iterdir():
            if not day_dir.is_dir():
                continue

            try:
                day_value = datetime.strptime(
                    day_dir.name,
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                continue

            for request_dir in day_dir.iterdir():
                if request_dir.is_dir():
                    request_dirs.append(
                        (
                            day_value,
                            request_dir.stat().st_mtime,
                            request_dir,
                        )
                    )

    request_dirs.sort(key=lambda item: (item[0], item[1], str(item[2])))

    return request_dirs


def cleanup_archive_by_max_gb(archive_dir, archive_max_gb):
    archive_dir = Path(archive_dir)

    if archive_max_gb is None or archive_max_gb <= 0:
        return []

    if not archive_dir.exists():
        return []

    max_bytes = int(float(archive_max_gb) * 1024 * 1024 * 1024)
    removed = []

    while get_dir_size_bytes(archive_dir) > max_bytes:
        request_dirs = list_archive_request_dirs(archive_dir)

        if not request_dirs:
            break

        _, _, request_dir = request_dirs[0]

        shutil.rmtree(request_dir)
        removed.append(request_dir)

    remove_empty_archive_month_dirs(archive_dir)

    return removed


def cleanup_archive(archive_dir, retention_days, archive_max_gb):
    removed_by_days = cleanup_archive_by_retention_days(
        archive_dir=archive_dir,
        retention_days=retention_days,
    )

    removed_by_size = cleanup_archive_by_max_gb(
        archive_dir=archive_dir,
        archive_max_gb=archive_max_gb,
    )

    return {
        "removed_by_days": [str(path) for path in removed_by_days],
        "removed_by_size": [str(path) for path in removed_by_size],
    }


def archive_successful_case(
    request_id,
    image_path,
    command_path,
    result_path,
    archive_dir,
    retention_days=30,
    archive_max_gb=5,
):
    archive_dir = Path(archive_dir).resolve()
    image_path = Path(image_path).resolve()
    command_path = Path(command_path).resolve()
    result_path = Path(result_path).resolve()

    now_value = datetime.now()
    month_name = now_value.strftime("%Y-%m")
    day_name = now_value.strftime("%Y-%m-%d")
    request_name = sanitize_archive_name(request_id)

    day_dir = archive_dir / month_name / day_name
    final_dir = day_dir / request_name

    if final_dir.exists():
        stamp = now_value.strftime("%H%M%S")
        final_dir = day_dir / f"{request_name}_{stamp}"

    tmp_dir = day_dir / f".{final_dir.name}.tmp"

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    tmp_dir.mkdir(parents=True, exist_ok=False)

    try:
        shutil.copy2(image_path, tmp_dir / "input.jpg")
        shutil.copy2(command_path, tmp_dir / "command.json")
        shutil.copy2(result_path, tmp_dir / "result.json")

        tmp_dir.rename(final_dir)

        cleanup_info = cleanup_archive(
            archive_dir=archive_dir,
            retention_days=retention_days,
            archive_max_gb=archive_max_gb,
        )

        return {
            "archive_path": final_dir,
            "cleanup": cleanup_info,
        }

    except Exception:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

        raise

def cleanup_old_output_results(output_dir, out_retention_days):
    output_dir = Path(output_dir)

    if out_retention_days is None or out_retention_days <= 0:
        return []

    if not output_dir.exists():
        return []

    cutoff_ts = time.time() - int(out_retention_days) * 24 * 60 * 60
    removed = []

    for path in sorted(output_dir.glob("*.json")):
        if not path.is_file():
            continue

        if path.name.endswith(".tmp"):
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        if stat.st_mtime >= cutoff_ts:
            continue

        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            print_service_event(
                f"Cannot remove old output result {path}: {exc}",
                level="warning",
            )

    return removed

def command_sort_key(path):
    try:
        stat = path.stat()
        return (
            stat.st_mtime,
            path.name,
        )
    except FileNotFoundError:
        return (
            0,
            path.name,
        )


def list_command_files(commands_dir):
    commands_dir = Path(commands_dir)

    if not commands_dir.exists():
        return []

    result = []

    for path in commands_dir.glob("*.json"):
        if path.name.endswith(".tmp"):
            continue

        if not path.is_file():
            continue

        result.append(path)

    return sorted(result, key=command_sort_key)

def claim_command_for_processing(command_path, processing_dir):
    command_path = Path(command_path)
    processing_dir = Path(processing_dir)
    processing_dir.mkdir(parents=True, exist_ok=True)

    if not command_path.exists():
        return None

    target_path = processing_dir / command_path.name

    if target_path.exists():
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target_path = processing_dir / f"{command_path.stem}_{stamp}{command_path.suffix}"

    command_path.replace(target_path)

    return target_path


def move_stale_processing_commands(processing_dir, error_dir):
    processing_dir = Path(processing_dir)
    error_dir = Path(error_dir)

    if not processing_dir.exists():
        return []

    stale_dir = error_dir / "stale_processing"
    moved = []

    for path in sorted(processing_dir.glob("*.json"), key=command_sort_key):
        if not path.is_file():
            continue

        moved_path = move_file_to_dir(path, stale_dir)
        moved.append(moved_path)

        print_service_event(
            f"Stale processing command moved to {moved_path}",
            level="warning",
        )

    return moved

def normalize_request_id(value, command_path):
    if value:
        return str(value)

    return command_path.stem


def resolve_image_path(command, command_path, input_dir):
    image_path = command.get("image_path")
    image_file = command.get("image_file")

    if image_path:
        path = Path(str(image_path))

        if not path.is_absolute():
            path = input_dir / path

        return path.resolve()

    if image_file:
        return (input_dir / str(image_file)).resolve()

    # fallback: REQ001.json -> REQ001.jpg / jpeg / png
    for ext in IMAGE_EXTENSIONS:
        candidate = input_dir / f"{command_path.stem}{ext}"
        if candidate.exists():
            return candidate.resolve()

    return None


def build_pipeline_error_result(message, request_id=None, stage=None):
    return {
        "request_id": request_id,
        "last_name": None,
        "first_name": None,
        "middle_name": None,
        "birth_date": None,
        "sex": None,
        "birth_place": None,
        "issue_date": None,
        "department_code": None,
        "issued_by": None,
        "document_number": None,
        "validation": {
            "status": "error",
            "errors": [
                {
                    "field": "__service__",
                    "code": "service_failed",
                    "message": message,
                    "value": stage,
                }
            ],
            "warnings": [],
            "summary": {
                "errors_count": 1,
                "warnings_count": 0,
            },
        },
        "pipeline": {
            "status": "error",
            "failed_stage": stage,
        },
    }


def add_request_id(result, request_id):
    if isinstance(result, dict):
        result["request_id"] = request_id

    return result


def print_service_event(message, level="info"):
    if level == "error":
        logging.error(message)
    elif level == "warning":
        logging.warning(message)
    else:
        logging.info(message)


def process_command(
    project_root,
    command_path,
    input_dir,
    output_dir,
    error_dir,
    work_dir,
    ocr_engine,
    debug_artifacts=False,
    keep_input=False,
    archive_dir=None,
    archive_retention_days=30,
    archive_max_gb=5,
    ocr_max_side=0,
):
    command_path = Path(command_path)

    print_service_event(f"Command detected: {command_path}")

    try:
        command = load_json(command_path)
    except Exception as exc:
        request_id = command_path.stem
        output_path = output_dir / f"{request_id}.json"

        result = build_pipeline_error_result(
            message=f"Cannot read command JSON: {exc}",
            request_id=request_id,
            stage="command",
        )

        save_json_atomic(output_path, result)
        moved_path = move_file_to_dir(command_path, error_dir)

        print_service_event(
            f"Command JSON error: {command_path}; moved to {moved_path}"
        )

        return {
            "status": "command_error",
            "request_id": request_id,
            "output_path": output_path,
        }

    request_id = normalize_request_id(
        command.get("request_id"),
        command_path,
    )

    image_path = resolve_image_path(
        command=command,
        command_path=command_path,
        input_dir=input_dir,
    )

    output_file = command.get("output_file")
    output_path_value = command.get("output_path")

    if output_path_value:
        output_path = Path(str(output_path_value))
        if not output_path.is_absolute():
            output_path = output_dir / output_path
        output_path = output_path.resolve()
    elif output_file:
        output_path = (output_dir / str(output_file)).resolve()
    else:
        output_path = (output_dir / f"{request_id}.json").resolve()

    tmp_output_path = output_path.with_suffix(output_path.suffix + ".tmp")

    if image_path is None:
        result = build_pipeline_error_result(
            message="Command does not contain image_path or image_file, and fallback image was not found",
            request_id=request_id,
            stage="command",
        )

        save_json_atomic(output_path, result)
        moved_path = move_file_to_dir(command_path, error_dir)

        print_service_event(
            f"Missing image in command {request_id}; moved command to {moved_path}"
        )

        return {
            "status": "command_error",
            "request_id": request_id,
            "output_path": output_path,
        }

    if not image_path.exists():
        result = build_pipeline_error_result(
            message=f"Input image not found: {image_path}",
            request_id=request_id,
            stage="input",
        )

        save_json_atomic(output_path, result)
        moved_path = move_file_to_dir(command_path, error_dir)

        print_service_event(
            f"Input image not found for {request_id}: {image_path}; moved command to {moved_path}"
        )

        return {
            "status": "input_error",
            "request_id": request_id,
            "output_path": output_path,
        }

    request_work_dir = work_dir / request_id

    try:
        result, summary, exit_code = process_photo(
            project_root=project_root,
            input_image=image_path,
            output_json=tmp_output_path,
            work_dir=request_work_dir,
            debug_artifacts=debug_artifacts,
            delete_input=False,
            ocr_engine=ocr_engine,
            ocr_max_side=ocr_max_side,
        )
        timing_sec = summary.get("timing_sec") or {}

        if timing_sec:
            print_service_event(
                "Timing "
                f"{request_id}: "
                f"total={timing_sec.get('total_sec')} "
                f"crop={timing_sec.get('crop_sec')} "
                f"ocr={timing_sec.get('ocr_sec')} "
                f"parse={timing_sec.get('parse_sec')} "
                f"save={timing_sec.get('save_result_sec')}"
            )

        result = add_request_id(result, request_id)

        save_json_atomic(tmp_output_path, result)
        tmp_output_path.replace(output_path)

        validation = result.get("validation") or {}
        validation_status = validation.get("status")

        if exit_code == 0 and validation_status == "ok":
            archive_info = None
            archive_path = None

            if archive_dir is not None:
                archive_info = archive_successful_case(
                    request_id=request_id,
                    image_path=image_path,
                    command_path=command_path,
                    result_path=output_path,
                    archive_dir=archive_dir,
                    retention_days=archive_retention_days,
                    archive_max_gb=archive_max_gb,
                )
                archive_path = archive_info["archive_path"]

            if not keep_input:
                delete_file_if_exists(image_path)

            delete_file_if_exists(command_path)

            print_service_event(
                f"OK {request_id}: output={output_path}"
            )

            return {
                "status": "ok",
                "request_id": request_id,
                "output_path": output_path,
                "archive_path": archive_path,
                "archive_cleanup": (
                    archive_info.get("cleanup") if archive_info else None
                ),
                "timing_sec": timing_sec,
            }

        moved_path = move_file_to_dir(command_path, error_dir)

        print_service_event(
            f"Validation error {request_id}: output={output_path}; command moved to {moved_path}"
        )

        return {
            "status": "validation_error",
            "request_id": request_id,
            "output_path": output_path,
            "timing_sec": timing_sec,
        }

    except Exception as exc:
        result = build_pipeline_error_result(
            message=str(exc),
            request_id=request_id,
            stage="pipeline",
        )

        save_json_atomic(output_path, result)
        moved_path = move_file_to_dir(command_path, error_dir)

        print_service_event(
            f"Pipeline error {request_id}: {exc}; command moved to {moved_path}"
        )

        return {
            "status": "pipeline_error",
            "request_id": request_id,
            "output_path": output_path,
        }


def run_service(
    commands_dir,
    input_dir,
    output_dir,
    error_dir,
    work_dir,
    poll_sec,
    once=False,
    debug_artifacts=False,
    keep_input=False,
    archive_dir=None,
    archive_retention_days=30,
    archive_max_gb=5,
    out_retention_days=7,
    ocr_max_side=0,
    log_file=None,
    log_total_max_mb=DEFAULT_LOG_TOTAL_MAX_MB,
    log_files_count=DEFAULT_LOG_FILES_COUNT,
    processing_dir=None,
    lock_file=None,
    status_file=None,
    heartbeat_sec=10.0,
):
    project_root = Path(__file__).resolve().parents[1]

    commands_dir = Path(commands_dir).resolve()
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    error_dir = Path(error_dir).resolve()
    if archive_dir is None:
        archive_dir = output_dir.parent / "archive"
    else:
        archive_dir = Path(archive_dir).resolve()
    work_dir = Path(work_dir).resolve()

    if processing_dir is None:
        processing_dir = commands_dir.parent / "processing"
    else:
        processing_dir = Path(processing_dir).resolve()

    if lock_file is None:
        lock_file = output_dir.parent / "passport_service.lock"
    else:
        lock_file = Path(lock_file).resolve()

    if status_file is None:
        status_file = output_dir.parent / "status" / "service_status.json"
    else:
        status_file = Path(status_file).resolve()

    heartbeat_sec = max(1.0, float(heartbeat_sec))

    if log_file is None:
        log_file = output_dir.parent / "logs" / "passport_service.log"
    else:
        log_file = Path(log_file).resolve()

    configure_logging(
        log_file=log_file,
        log_total_max_mb=log_total_max_mb,
        log_files_count=log_files_count,
    )

    commands_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    error_dir.mkdir(parents=True, exist_ok=True)
    processing_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    try:
        service_lock_handle = acquire_service_lock(lock_file)
    except RuntimeError as exc:
        print_service_event(str(exc), level="error")
        return 2

    if debug_artifacts:
        work_dir.mkdir(parents=True, exist_ok=True)

    print_service_event("Starting passport service")
    print_service_event(f"commands_dir={commands_dir}")
    print_service_event(f"processing_dir={processing_dir}")
    print_service_event(f"input_dir={input_dir}")
    print_service_event(f"output_dir={output_dir}")
    print_service_event(f"error_dir={error_dir}")
    print_service_event(f"archive_dir={archive_dir}")
    print_service_event(f"archive_retention_days={archive_retention_days}")
    print_service_event(f"archive_max_gb={archive_max_gb}")
    print_service_event(f"out_retention_days={out_retention_days}")
    print_service_event(f"ocr_max_side={ocr_max_side}")
    print_service_event(f"lock_file={lock_file}")
    print_service_event(f"log_file={log_file}")
    print_service_event(f"status_file={status_file}")
    print_service_event(f"heartbeat_sec={heartbeat_sec}")
    print_service_event("Service lock acquired")
    print_service_event(f"log_total_max_mb={log_total_max_mb}")
    print_service_event(f"log_files_count={log_files_count}")
    print_service_event(f"debug_artifacts={debug_artifacts}")
    moved_stale = move_stale_processing_commands(
        processing_dir=processing_dir,
        error_dir=error_dir,
    )

    if moved_stale:
        print_service_event(
            f"Moved stale processing commands: {len(moved_stale)}",
            level="warning",
        )
    print_service_event("Initializing PaddleOCR once...")

    ocr_engine = PassportOcrEngine(lang="ru")

    print_service_event(
        f"PaddleOCR initialized in {ocr_engine.init_sec:.3f} sec"
    )

    started_at = now_iso()

    service_status = {
        "status": "running",
        "started_at": started_at,
        "last_heartbeat_at": started_at,
        "last_command_at": None,
        "last_success_at": None,
        "last_error_at": None,
        "processed_count": 0,
        "error_count": 0,
        "current_request_id": None,
        "last_request_id": None,
        "last_result_status": None,
        "last_output_path": None,
        "last_error_status": None,
        "last_timing_sec": None,
        "ocr_engine_init_sec": float(ocr_engine.init_sec),
        "commands_dir": str(commands_dir),
        "processing_dir": str(processing_dir),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "error_dir": str(error_dir),
        "work_dir": str(work_dir),
        "archive_dir": str(archive_dir),
        "archive_retention_days": archive_retention_days,
        "archive_max_gb": archive_max_gb,
        "last_archive_path": None,
        "last_archive_cleanup": None,
        "out_retention_days": out_retention_days,
        "ocr_max_side": int(ocr_max_side or 0),
        "last_out_cleanup_at": None,
        "last_out_cleanup_removed": 0,
        "log_file": str(log_file),
        "lock_file": str(lock_file),
        "debug_artifacts": bool(debug_artifacts),
        "keep_input": bool(keep_input),
        "poll_sec": float(poll_sec),
        "heartbeat_sec": float(heartbeat_sec),
    }

    write_service_status(status_file, service_status)
    last_status_write_ts = time.time()
    last_out_cleanup_ts = 0

    while True:
        now_ts = time.time()

        if (
            out_retention_days
            and out_retention_days > 0
            and now_ts - last_out_cleanup_ts >= OUT_CLEANUP_INTERVAL_SEC
        ):
            removed_outputs = cleanup_old_output_results(
                output_dir=output_dir,
                out_retention_days=out_retention_days,
            )
            last_out_cleanup_ts = now_ts
            service_status["last_out_cleanup_at"] = now_iso()
            service_status["last_out_cleanup_removed"] = len(removed_outputs)

            if removed_outputs:
                print_service_event(
                    f"Removed old output result JSON files: {len(removed_outputs)}"
                )

            write_service_status(status_file, service_status)
            last_status_write_ts = time.time()

        commands = list_command_files(commands_dir)

        if not commands:
            now_ts = time.time()

            if now_ts - last_status_write_ts >= heartbeat_sec:
                write_service_status(status_file, service_status)
                last_status_write_ts = now_ts

            if once:
                print_service_event("No commands found, exiting because --once is set")
                write_service_status(status_file, service_status)
                return 0

            time.sleep(poll_sec)
            continue

        for command_path in commands:
            try:
                processing_path = claim_command_for_processing(
                    command_path=command_path,
                    processing_dir=processing_dir,
                )
            except Exception as exc:
                print_service_event(
                    f"Cannot move command to processing: {command_path}; error={exc}",
                    level="error",
                )
                continue

            if processing_path is None:
                continue

            service_status["current_request_id"] = processing_path.stem
            service_status["last_command_at"] = now_iso()
            write_service_status(status_file, service_status)
            last_status_write_ts = time.time()

            command_result = process_command(
                project_root=project_root,
                command_path=processing_path,
                input_dir=input_dir,
                output_dir=output_dir,
                error_dir=error_dir,
                work_dir=work_dir,
                ocr_engine=ocr_engine,
                debug_artifacts=debug_artifacts,
                keep_input=keep_input,
                archive_dir=archive_dir,
                archive_retention_days=archive_retention_days,
                archive_max_gb=archive_max_gb,
                ocr_max_side=ocr_max_side,
            )

            result_status = command_result.get("status")
            request_id = command_result.get("request_id")
            output_path = command_result.get("output_path")
            archive_path = command_result.get("archive_path")
            archive_cleanup = command_result.get("archive_cleanup")
            timing_sec = command_result.get("timing_sec")

            service_status["current_request_id"] = None
            service_status["last_request_id"] = request_id
            service_status["last_result_status"] = result_status
            service_status["last_output_path"] = (
                str(output_path) if output_path else None
            )
            service_status["last_archive_path"] = (
                str(archive_path) if archive_path else None
            )
            service_status["last_archive_cleanup"] = archive_cleanup
            service_status["last_timing_sec"] = timing_sec
            
            if result_status == "ok":
                service_status["processed_count"] += 1
                service_status["last_success_at"] = now_iso()
            else:
                service_status["error_count"] += 1
                service_status["last_error_at"] = now_iso()
                service_status["last_error_status"] = result_status

            write_service_status(status_file, service_status)
            last_status_write_ts = time.time()

        if once:
            print_service_event("Processed available commands, exiting because --once is set")
            return 0


def main():
    parser = argparse.ArgumentParser(
        description="File-based production service for RF passport recognition"
    )

    parser.add_argument(
        "--commands-dir",
        required=True,
        help="Directory with command JSON files",
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Directory with input passport images",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for output result JSON files",
    )
    parser.add_argument(
        "--error-dir",
        default=None,
        help="Directory for failed command JSON files. Default: <commands-dir>/error",
    )
    parser.add_argument(
        "--processing-dir",
        default=None,
        help=(
            "Directory for commands currently being processed. "
            "Default: <commands-dir parent>/processing"
        ),
    )
    parser.add_argument(
        "--lock-file",
        default=None,
        help=(
            "Service lock file. "
            "Default: <output-dir parent>/passport_service.lock"
        ),
    )
    parser.add_argument(
        "--status-file",
        default=None,
        help=(
            "Service status JSON file. "
            "Default: <output-dir parent>/status/service_status.json"
        ),
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        help=(
            "Directory for archived successful cases. "
            "Default: <output-dir parent>/archive"
        ),
    )
    parser.add_argument(
        "--archive-retention-days",
        type=int,
        default=30,
        help="How many days to keep successful case archive. Default: 30",
    )
    parser.add_argument(
        "--archive-max-gb",
        type=float,
        default=5,
        help="Maximum successful case archive size in GB. Default: 5",
    )
    parser.add_argument(
        "--out-retention-days",
        type=int,
        default=7,
        help=(
            "How many days to keep output result JSON files. "
            "Use 0 to disable cleanup. Default: 7"
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
        "--heartbeat-sec",
        type=float,
        default=10.0,
        help="How often to update service_status.json while idle. Default: 10",
    )
    parser.add_argument(
        "--work-dir",
        default="debug/passport_service",
        help="Directory for debug artifacts when --debug-artifacts is enabled",
    )
    parser.add_argument(
        "--poll-sec",
        type=float,
        default=1.0,
        help="Polling interval in seconds",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process currently available commands and exit",
    )
    parser.add_argument(
        "--debug-artifacts",
        action="store_true",
        help="Save crop/raw OCR/overlay/Paddle debug/parsed debug artifacts",
    )
    parser.add_argument(
        "--keep-input",
        action="store_true",
        help="Do not delete input image after successful processing",
    )

    parser.add_argument(
        "--log-file",
        default=None,
        help=(
            "Service log file. "
            "Default: <output-dir parent>/logs/passport_service.log"
        ),
    )
    parser.add_argument(
        "--log-total-max-mb",
        type=int,
        default=DEFAULT_LOG_TOTAL_MAX_MB,
        help="Approximate total log size limit in MB. Default: 100",
    )
    parser.add_argument(
        "--log-files-count",
        type=int,
        default=DEFAULT_LOG_FILES_COUNT,
        help="Number of rotated log files including active file. Default: 5",
    )

    args = parser.parse_args()

    commands_dir = Path(args.commands_dir)

    if args.error_dir:
        error_dir = Path(args.error_dir)
    else:
        error_dir = commands_dir / "error"

    return run_service(
        commands_dir=commands_dir,
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        error_dir=error_dir,
        work_dir=Path(args.work_dir),
        poll_sec=args.poll_sec,
        once=args.once,
        debug_artifacts=args.debug_artifacts,
        keep_input=args.keep_input,
        archive_dir=Path(args.archive_dir) if args.archive_dir else None,
        archive_retention_days=args.archive_retention_days,
        archive_max_gb=args.archive_max_gb,
        out_retention_days=args.out_retention_days,
        ocr_max_side=args.ocr_max_side,
        log_file=args.log_file,
        log_total_max_mb=args.log_total_max_mb,
        log_files_count=args.log_files_count,
        processing_dir=Path(args.processing_dir) if args.processing_dir else None,
        lock_file=Path(args.lock_file) if args.lock_file else None,
        status_file=Path(args.status_file) if args.status_file else None,
        heartbeat_sec=args.heartbeat_sec,
    )


if __name__ == "__main__":
    raise SystemExit(main())