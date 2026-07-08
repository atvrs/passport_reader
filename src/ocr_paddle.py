#!/usr/bin/env python3
import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from paddleocr import PaddleOCR


def make_json_safe(value: Any) -> Any:
    """Преобразует numpy/PaddleOCR объекты в JSON-сериализуемый вид."""
    if isinstance(value, np.ndarray):
        return value.tolist()

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return float(value)

    if isinstance(value, np.bool_):
        return bool(value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {
            str(k): make_json_safe(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            make_json_safe(item)
            for item in value
        ]

    if hasattr(value, "res"):
        return {
            "res": make_json_safe(value.res),
        }

    if hasattr(value, "to_dict"):
        try:
            return make_json_safe(value.to_dict())
        except Exception:
            pass

    if hasattr(value, "__dict__"):
        try:
            return make_json_safe(value.__dict__)
        except Exception:
            pass

    return value


def has_array_values(value: Any) -> bool:
    if value is None:
        return False

    if isinstance(value, np.ndarray):
        return value.size > 0

    try:
        return len(value) > 0
    except Exception:
        return True


def bbox_from_poly(poly: Any) -> list[int] | None:
    if not has_array_values(poly):
        return None

    try:
        points = np.array(poly, dtype=np.float32).reshape(-1, 2)

        if points.size == 0:
            return None

        x_min = int(np.min(points[:, 0]))
        y_min = int(np.min(points[:, 1]))
        x_max = int(np.max(points[:, 0]))
        y_max = int(np.max(points[:, 1]))

        return [
            x_min,
            y_min,
            x_max,
            y_max,
        ]
    except Exception:
        return None


def normalize_box(box: Any) -> list[int] | None:
    if not has_array_values(box):
        return None

    try:
        values = np.array(box).reshape(-1).tolist()

        if len(values) < 4:
            return None

        return [
            int(values[0]),
            int(values[1]),
            int(values[2]),
            int(values[3]),
        ]
    except Exception:
        return None

def image_shape(path: Path) -> list[int] | None:
    img = cv2.imread(str(path))

    if img is None:
        return None

    h, w = img.shape[:2]

    return [
        int(h),
        int(w),
    ]

def prepare_ocr_input_image(
    image_path: Path,
    ocr_max_side: int | None = None,
) -> tuple[Path, dict]:
    image_path = Path(image_path)

    resize_info = {
        "enabled": False,
        "max_side": int(ocr_max_side or 0),
        "source_path": str(image_path),
        "ocr_path": str(image_path),
        "source_shape": None,
        "ocr_shape": None,
        "scale": 1.0,
    }

    img = cv2.imread(str(image_path))

    if img is None:
        raise FileNotFoundError(
            f"Не удалось загрузить изображение для OCR: {image_path}"
        )

    h, w = img.shape[:2]
    resize_info["source_shape"] = [int(h), int(w)]
    resize_info["ocr_shape"] = [int(h), int(w)]

    max_side = int(ocr_max_side or 0)

    if max_side <= 0:
        return image_path, resize_info

    current_max_side = max(h, w)

    if current_max_side <= max_side:
        return image_path, resize_info

    scale = float(max_side) / float(current_max_side)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    resized = cv2.resize(
        img,
        (new_w, new_h),
        interpolation=cv2.INTER_AREA,
    )

    resized_path = (
        image_path.parent
        / f"{image_path.stem}_ocr_max_side_{max_side}{image_path.suffix}"
    )

    ok = cv2.imwrite(
        str(resized_path),
        resized,
        [int(cv2.IMWRITE_JPEG_QUALITY), 95],
    )

    if not ok:
        raise RuntimeError(
            f"Не удалось сохранить resized OCR image: {resized_path}"
        )

    resize_info.update(
        {
            "enabled": True,
            "ocr_path": str(resized_path),
            "ocr_shape": [int(new_h), int(new_w)],
            "scale": float(scale),
        }
    )

    return resized_path, resize_info

def page_res_from_plain(page: Any) -> dict:
    if not isinstance(page, dict):
        return {}

    if "res" in page and isinstance(page["res"], dict):
        return page["res"]

    return page


def page_res_from_ocr_page(page: Any) -> dict:
    if isinstance(page, dict):
        return page_res_from_plain(page)

    if hasattr(page, "res"):
        try:
            res = page.res
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    if hasattr(page, "to_dict"):
        try:
            return page_res_from_plain(page.to_dict())
        except Exception:
            pass

    return {}


def make_items_source(result: Any) -> list[dict]:
    if isinstance(result, list):
        pages = result
    else:
        pages = [result]

    source = []

    for page in pages:
        page_res = page_res_from_ocr_page(page)

        if page_res:
            source.append(page_res)

    return source


def sequence_get(values: Any, idx: int) -> Any:
    if values is None:
        return None

    try:
        if idx >= len(values):
            return None

        return values[idx]
    except Exception:
        return None


def normalize_text_sequence(values: Any) -> list:
    if values is None:
        return []

    if isinstance(values, list):
        return values

    if isinstance(values, tuple):
        return list(values)

    if isinstance(values, np.ndarray):
        return values.tolist()

    return []


def extract_items(plain_result: Any) -> list[dict]:
    """
    Достаёт распознанные строки из результата PaddleOCR 3.x.

    Основные поля PaddleOCR 3.x:
    - rec_texts
    - rec_scores
    - rec_polys
    - rec_boxes

    В production эта функция умеет работать напрямую с page.res,
    без полной рекурсивной make_json_safe(result).
    """
    if isinstance(plain_result, list):
        pages = plain_result
    else:
        pages = [plain_result]

    items = []

    for page_index, page in enumerate(pages):
        page_res = page_res_from_plain(page)

        if not page_res:
            continue

        texts = normalize_text_sequence(
            page_res.get("rec_texts", [])
        )
        scores = page_res.get("rec_scores", [])
        polys = page_res.get("rec_polys", [])
        boxes = page_res.get("rec_boxes", [])

        if not texts:
            continue

        for idx, text in enumerate(texts):
            score = sequence_get(scores, idx)
            poly = sequence_get(polys, idx)
            box = sequence_get(boxes, idx)

            bbox = normalize_box(box)

            if bbox is None:
                bbox = bbox_from_poly(poly)

            item = {
                "id": len(items),
                "page_index": int(page_index),
                "text": str(text),
                "score": (
                    float(score)
                    if score is not None
                    else None
                ),
                "bbox": bbox,
                "poly": make_json_safe(poly),
            }

            items.append(item)

    return items

def item_sort_key(item: dict) -> tuple[int, int, int]:
    bbox = item.get("bbox")

    if not bbox:
        return (
            10**9,
            10**9,
            int(item.get("id", 0)),
        )

    x1, y1, x2, y2 = bbox

    return (
        int((y1 + y2) / 2),
        int((x1 + x2) / 2),
        int(item.get("id", 0)),
    )


def draw_overlay(
    image_path: Path,
    items: list[dict],
    overlay_path: Path,
) -> None:
    img = cv2.imread(str(image_path))

    if img is None:
        raise FileNotFoundError(
            f"Не удалось загрузить изображение для overlay: {image_path}"
        )

    overlay = img.copy()

    for item in items:
        item_id = int(item["id"])

        poly = item.get("poly")
        bbox = item.get("bbox")

        if has_array_values(poly):
            try:
                pts = np.array(poly, dtype=np.int32).reshape(-1, 2)
                cv2.polylines(
                    overlay,
                    [pts],
                    isClosed=True,
                    color=(0, 255, 0),
                    thickness=2,
                )

                x = int(np.min(pts[:, 0]))
                y = int(np.min(pts[:, 1]))

            except Exception:
                x = 10
                y = 30

        elif bbox is not None:
            x1, y1, x2, y2 = bbox

            cv2.rectangle(
                overlay,
                (int(x1), int(y1)),
                (int(x2), int(y2)),
                (0, 255, 0),
                2,
            )

            x = int(x1)
            y = int(y1)

        else:
            continue

        label = str(item_id)

        cv2.putText(
            overlay,
            label,
            (x, max(25, y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

    overlay_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    cv2.imwrite(
        str(overlay_path),
        overlay,
    )


def save_official_debug(
    result: Any,
    debug_dir: Path,
) -> None:
    """
    Сохраняет официальный debug PaddleOCR, если методы доступны.
    """
    official_dir = debug_dir / "paddle_official"
    official_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not isinstance(result, list):
        result_items = [result]
    else:
        result_items = result

    for res in result_items:
        if hasattr(res, "save_to_img"):
            try:
                res.save_to_img(str(official_dir))
            except TypeError:
                try:
                    res.save_to_img(save_path=str(official_dir))
                except Exception:
                    pass
            except Exception:
                pass

        if hasattr(res, "save_to_json"):
            try:
                res.save_to_json(str(official_dir))
            except TypeError:
                try:
                    res.save_to_json(save_path=str(official_dir))
                except Exception:
                    pass
            except Exception:
                pass

class PassportOcrEngine:
    """
    Переиспользуемый OCR engine для service mode.

    PaddleOCR инициализируется один раз в __init__(),
    а затем predict() можно вызывать для многих crop изображений.
    """

    def __init__(self, lang: str = "ru"):
        self.lang = lang

        init_started = time.perf_counter()

        self.ocr = PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

        self.init_sec = float(
            time.perf_counter() - init_started
        )

    def predict(self, image_path: Path) -> tuple[Any, dict]:
        image_path = Path(image_path)

        predict_started = time.perf_counter()

        result = self.ocr.predict(str(image_path))

        predict_sec = float(
            time.perf_counter() - predict_started
        )

        timing = {
            # Для service mode init_sec на конкретный документ = 0,
            # потому что OCR engine уже создан ранее.
            "init_sec": 0.0,

            # Отдельно сохраняем реальную стоимость инициализации engine.
            "engine_init_sec": float(self.init_sec),

            "predict_sec": predict_sec,
        }

        return result, timing

def run_ocr(
    image_path: Path,
    lang: str,
) -> tuple[Any, dict]:
    """
    Backward-compatible OCR runner.

    Используется CLI-режимом ocr_paddle.py.
    Для одного запуска по-прежнему создаёт PaddleOCR внутри функции.

    Для service mode использовать PassportOcrEngine напрямую,
    чтобы не инициализировать PaddleOCR на каждый паспорт.
    """
    engine = PassportOcrEngine(lang=lang)

    result, timing = engine.predict(image_path)

    # Для совместимости старого CLI init_sec остаётся временем создания OCR.
    timing["init_sec"] = float(engine.init_sec)

    return result, timing

def run_ocr_on_image(
    image_path: Path,
    lang: str = "ru",
    overlay_path: Path | None = None,
    debug_dir: Path | None = None,
    include_paddle_result: bool = True,
    engine: PassportOcrEngine | None = None,
    ocr_max_side: int | None = None,
) -> dict:
    """
    Запускает OCR и возвращает raw OCR JSON как dict в памяти.

    Важно:
    - сам по себе raw OCR JSON на диск не пишет;
    - overlay пишет только если передан overlay_path;
    - официальный Paddle debug пишет только если передан debug_dir;
    - include_paddle_result=False уменьшает размер результата для production,
      parser-у достаточно image_shape/items/raw_text/timing.
    """
    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Файл не найден: {image_path}"
        )

    ocr_image_path, resize_info = prepare_ocr_input_image(
        image_path=image_path,
        ocr_max_side=ocr_max_side,
    )

    total_started = time.perf_counter()

    if engine is None:
        result, timing = run_ocr(
            image_path=ocr_image_path,
            lang=lang,
        )
    else:
        result, timing = engine.predict(ocr_image_path)

    postprocess_started = time.perf_counter()

    items_source = make_items_source(result)

    items = extract_items(items_source)

    sorted_items = sorted(
        items,
        key=item_sort_key,
    )

    raw_text = "\n".join(
        item["text"]
        for item in sorted_items
        if item.get("text")
    )

    timing["postprocess_sec"] = float(
        time.perf_counter() - postprocess_started
    )

    output = {
        "input": str(image_path),
        "ocr_input": str(ocr_image_path),
        "image_shape": image_shape(ocr_image_path),
        "ocr_resize": resize_info,
        "lang": lang,

        # Для обратной совместимости оставляем старое поле.
        # Теперь оно означает именно predict, а не весь запуск.
        "elapsed_sec": float(timing["predict_sec"]),

        "timing": {},
        "items_count": int(len(items)),
        "raw_text": raw_text,
        "items": sorted_items,
    }

    if include_paddle_result:
        output["paddle_result"] = make_json_safe(result)

    save_debug_started = time.perf_counter()

    if overlay_path:
        draw_overlay(
            image_path=ocr_image_path,
            items=items,
            overlay_path=Path(overlay_path),
        )

    if debug_dir:
        save_official_debug(
            result=result,
            debug_dir=Path(debug_dir),
        )

    timing["save_debug_sec"] = float(
        time.perf_counter() - save_debug_started
    )

    timing["total_sec"] = float(
        time.perf_counter() - total_started
    )

    output["timing"] = timing

    return output

def main():
    parser = argparse.ArgumentParser(
        description="Raw PaddleOCR diagnostic runner for passport crop.",
    )

    parser.add_argument(
        "input",
        help="Путь к crop изображения паспорта.",
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Путь к raw OCR JSON.",
    )

    parser.add_argument(
        "--overlay",
        help="Путь к overlay изображению с OCR bbox.",
    )

    parser.add_argument(
        "--debug-dir",
        help="Папка для debug PaddleOCR.",
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
        "--lang",
        default="ru",
        help="Язык PaddleOCR. По умолчанию ru.",
    )

    args = parser.parse_args()

    image_path = Path(args.input)
    output_path = Path(args.output)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Файл не найден: {image_path}"
        )

    output = run_ocr_on_image(
        image_path=image_path,
        lang=args.lang,
        ocr_max_side=args.ocr_max_side,
        overlay_path=Path(args.overlay) if args.overlay else None,
        debug_dir=Path(args.debug_dir) if args.debug_dir else None,
        include_paddle_result=True,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    timing = output["timing"]
    raw_text = output.get("raw_text", "")

    print(f"OCR items: {output['items_count']}")
    print(f"Init: {timing['init_sec']:.3f} sec")
    print(f"Predict: {timing['predict_sec']:.3f} sec")
    print(f"Postprocess: {timing['postprocess_sec']:.3f} sec")
    print(f"Save debug: {timing['save_debug_sec']:.3f} sec")
    print(f"Total: {timing['total_sec']:.3f} sec")
    print(f"JSON: {output_path}")

    if args.overlay:
        print(f"Overlay: {args.overlay}")

    if raw_text:
        print()
        print("RAW TEXT:")
        print(raw_text)


if __name__ == "__main__":
    main()