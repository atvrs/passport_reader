#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path


FIELD_NAMES = [
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


LATIN_TO_CYRILLIC = str.maketrans({
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "T": "Т",
    "X": "Х",
    "Y": "У",
    "a": "А",
    "b": "В",
    "c": "С",
    "e": "Е",
    "h": "Н",
    "k": "К",
    "m": "М",
    "o": "О",
    "p": "Р",
    "t": "Т",
    "x": "Х",
    "y": "У",

    # Греческие символы, которые OCR иногда подмешивает в служебные подписи.
    "Δ": "Д",
    "δ": "Д",
    "Λ": "Л",
    "λ": "Л",
})


SERVICE_LABEL_PATTERNS = [
    r"\bРОССИЙСКАЯ\s*ФЕДЕРАЦИЯ\b",
    r"\bПАСПОРТ\s*ВЫДАН\b",
    r"\bДАТА\s*ВЫДАЧИ\b",
    r"\bКОД\s*ПОДРАЗДЕЛЕНИЯ\b",
    r"\bФАМИЛИЯ\b",
    r"\bИМЯ\b",
    r"\bОТЧЕСТВО\b",
    r"\bПОЛ\b",
    r"\bДАТА\s*РОЖДЕНИЯ\b",
    r"\bМЕСТО\s*РОЖДЕНИЯ\b",
    r"\bЛИЧНАЯ\s*ПОДПИСЬ\b",
]


DATE_RE = re.compile(r"\b(\d{2})[.\-/](\d{2})[.\-/](\d{4})\b")
DEPARTMENT_CODE_RE = re.compile(r"\b\d{3}[-\s]?\d{3}\b")


def normalize_text(text):
    if text is None:
        return ""

    text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("Ё", "Е").replace("ё", "е")
    text = text.translate(LATIN_TO_CYRILLIC)
    text = text.upper()

    text = text.replace("«", "").replace("»", "")
    text = text.replace('"', "")
    text = text.replace("`", "")
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = text.replace("–", "-").replace("—", "-")

    text = re.sub(r"\s+", " ", text).strip()

    # Типовая ошибка OCR на российских паспортах:
    # ГОР. часто читается как ФОП.
    text = re.sub(r"\bФОП\.", "ГОР.", text)
    text = re.sub(r"\bФОП\b", "ГОР.", text)

    # Частые варианты с лишними пробелами.
    text = re.sub(r"\bГ\s*О\s*Р\s*\.", "ГОР.", text)
    text = re.sub(r"\bГОР\.\s*", "ГОР. ", text)
    text = re.sub(r"\bР\s*О\s*В\s*Д\b", "РОВД", text)

    # Field-specific geographic OCR corrections should not live in global normalization.

    text = re.sub(r"\s+", " ", text).strip()

    return text

def compact_text(text):
    return re.sub(r"[^А-ЯA-Z0-9]+", "", normalize_text(text))


def is_service_label(text):
    norm = normalize_text(text)

    for pattern in SERVICE_LABEL_PATTERNS:
        if re.search(pattern, norm):
            return True

    return False


def to_float(value):
    try:
        return float(value)
    except Exception:
        return None


def normalize_bbox(raw_bbox):
    """
    Возвращает bbox в формате:
    {
      "points": [[x, y], ...],
      "x1": ...,
      "y1": ...,
      "x2": ...,
      "y2": ...,
      "cx": ...,
      "cy": ...,
      "w": ...,
      "h": ...
    }

    Поддерживает несколько возможных форматов:
    - [[x,y], [x,y], [x,y], [x,y]]
    - [x1,y1,x2,y2]
    - {"x":..., "y":..., "w":..., "h":...}
    - {"x1":..., "y1":..., "x2":..., "y2":...}
    """
    if raw_bbox is None:
        return None

    points = []

    if isinstance(raw_bbox, dict):
        if all(k in raw_bbox for k in ("x", "y", "w", "h")):
            x = to_float(raw_bbox.get("x"))
            y = to_float(raw_bbox.get("y"))
            w = to_float(raw_bbox.get("w"))
            h = to_float(raw_bbox.get("h"))
            if None not in (x, y, w, h):
                points = [
                    [x, y],
                    [x + w, y],
                    [x + w, y + h],
                    [x, y + h],
                ]

        elif all(k in raw_bbox for k in ("x1", "y1", "x2", "y2")):
            x1 = to_float(raw_bbox.get("x1"))
            y1 = to_float(raw_bbox.get("y1"))
            x2 = to_float(raw_bbox.get("x2"))
            y2 = to_float(raw_bbox.get("y2"))
            if None not in (x1, y1, x2, y2):
                points = [
                    [x1, y1],
                    [x2, y1],
                    [x2, y2],
                    [x1, y2],
                ]

    elif isinstance(raw_bbox, list):
        if len(raw_bbox) == 4 and all(
            isinstance(p, (int, float)) for p in raw_bbox
        ):
            x1, y1, x2, y2 = [float(v) for v in raw_bbox]
            points = [
                [x1, y1],
                [x2, y1],
                [x2, y2],
                [x1, y2],
            ]

        elif len(raw_bbox) >= 4 and all(
            isinstance(p, (list, tuple)) and len(p) >= 2
            for p in raw_bbox
        ):
            for p in raw_bbox:
                x = to_float(p[0])
                y = to_float(p[1])
                if x is not None and y is not None:
                    points.append([x, y])

    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    x1 = min(xs)
    y1 = min(ys)
    x2 = max(xs)
    y2 = max(ys)
    w = x2 - x1
    h = y2 - y1

    return {
        "points": points,
        "x1": round(x1, 2),
        "y1": round(y1, 2),
        "x2": round(x2, 2),
        "y2": round(y2, 2),
        "cx": round((x1 + x2) / 2.0, 2),
        "cy": round((y1 + y2) / 2.0, 2),
        "w": round(w, 2),
        "h": round(h, 2),
    }


def find_image_shape(data):
    candidates = [
        data.get("image_shape") if isinstance(data, dict) else None,
        data.get("shape") if isinstance(data, dict) else None,
        data.get("input_shape") if isinstance(data, dict) else None,
    ]

    if isinstance(data, dict):
        meta = data.get("metadata")
        if isinstance(meta, dict):
            candidates.extend([
                meta.get("image_shape"),
                meta.get("shape"),
                meta.get("input_shape"),
            ])

    for candidate in candidates:
        if (
            isinstance(candidate, list)
            and len(candidate) >= 2
            and isinstance(candidate[0], (int, float))
            and isinstance(candidate[1], (int, float))
        ):
            return int(candidate[0]), int(candidate[1])

    return None, None


def item_from_dict(obj):
    text = (
        obj.get("text")
        or obj.get("rec_text")
        or obj.get("label")
        or obj.get("value")
    )

    if text is None:
        return None

    bbox = (
        obj.get("bbox")
        or obj.get("box")
        or obj.get("poly")
        or obj.get("points")
        or obj.get("dt_poly")
    )

    norm_bbox = normalize_bbox(bbox)
    if norm_bbox is None:
        return None

    confidence = (
        obj.get("confidence")
        or obj.get("conf")
        or obj.get("score")
        or obj.get("rec_score")
    )

    return {
        "text": str(text),
        "norm_text": normalize_text(text),
        "compact_text": compact_text(text),
        "confidence": confidence,
        "bbox": norm_bbox,
    }


def extract_items_from_paddle_arrays(obj):
    if not isinstance(obj, dict):
        return []

    texts = obj.get("rec_texts")
    scores = obj.get("rec_scores")
    boxes = (
        obj.get("dt_polys")
        or obj.get("rec_polys")
        or obj.get("boxes")
        or obj.get("dt_boxes")
    )

    if not isinstance(texts, list) or not isinstance(boxes, list):
        return []

    result = []

    for idx, text in enumerate(texts):
        if idx >= len(boxes):
            continue

        bbox = normalize_bbox(boxes[idx])
        if bbox is None:
            continue

        confidence = None
        if isinstance(scores, list) and idx < len(scores):
            confidence = scores[idx]

        result.append({
            "text": str(text),
            "norm_text": normalize_text(text),
            "compact_text": compact_text(text),
            "confidence": confidence,
            "bbox": bbox,
        })

    return result


def extract_items_from_paddle_legacy(obj):
    """
    Поддержка старого формата PaddleOCR:
    [
      [
        [[x,y], [x,y], [x,y], [x,y]],
        ["TEXT", 0.99]
      ],
      ...
    ]
    """
    if not isinstance(obj, list):
        return []

    result = []

    for row in obj:
        if (
            isinstance(row, list)
            and len(row) >= 2
            and isinstance(row[1], (list, tuple))
            and len(row[1]) >= 1
        ):
            bbox = normalize_bbox(row[0])
            if bbox is None:
                continue

            text = row[1][0]
            confidence = row[1][1] if len(row[1]) >= 2 else None

            result.append({
                "text": str(text),
                "norm_text": normalize_text(text),
                "compact_text": compact_text(text),
                "confidence": confidence,
                "bbox": bbox,
            })

    return result


def recursive_extract_items(obj):
    items = []

    if isinstance(obj, dict):
        direct = item_from_dict(obj)
        if direct is not None:
            items.append(direct)

        items.extend(extract_items_from_paddle_arrays(obj))

        for value in obj.values():
            items.extend(recursive_extract_items(value))

    elif isinstance(obj, list):
        items.extend(extract_items_from_paddle_legacy(obj))

        for value in obj:
            items.extend(recursive_extract_items(value))

    return items


def deduplicate_items(items):
    seen = set()
    result = []

    for item in items:
        bbox = item["bbox"]
        key = (
            item["norm_text"],
            round(bbox["x1"], 1),
            round(bbox["y1"], 1),
            round(bbox["x2"], 1),
            round(bbox["y2"], 1),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def load_ocr_items(data):
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = []

        for raw_item in data["items"]:
            if isinstance(raw_item, dict):
                item = item_from_dict(raw_item)
                if item is not None:
                    items.append(item)

        if items:
            return deduplicate_items(items)

    items = recursive_extract_items(data)
    return deduplicate_items(items)


def is_right_vertical_item(item, image_width):
    if image_width is None:
        return False

    bbox = item["bbox"]
    cx = bbox["cx"]
    w = max(bbox["w"], 1.0)
    h = max(bbox["h"], 1.0)

    near_right_edge = cx >= image_width * 0.84
    tall_or_narrow = h >= w * 1.8 or w <= image_width * 0.035

    text = item["compact_text"]
    digit_heavy = len(re.sub(r"\D", "", text)) >= 4

    return near_right_edge and (tall_or_narrow or digit_heavy)


def assign_zones(items, image_height, image_width):
    split_y = image_height * 0.5 if image_height else None

    top_page_items = []
    bottom_page_items = []
    right_vertical_items = []

    enriched = []

    for item in items:
        item = dict(item)
        item["is_service_label"] = is_service_label(item["norm_text"])
        item["is_right_vertical"] = is_right_vertical_item(item, image_width)

        if item["is_right_vertical"]:
            item["page_zone"] = "right_vertical"
            right_vertical_items.append(item)
        elif split_y is not None and item["bbox"]["cy"] < split_y:
            item["page_zone"] = "top_page"
            top_page_items.append(item)
        else:
            item["page_zone"] = "bottom_page"
            bottom_page_items.append(item)

        enriched.append(item)

    return {
        "items": sort_items(enriched),
        "top_page_items": sort_items(top_page_items),
        "bottom_page_items": sort_items(bottom_page_items),
        "right_vertical_items": sort_items(right_vertical_items),
        "split_y": split_y,
    }


def sort_items(items):
    return sorted(
        items,
        key=lambda item: (
            item["bbox"]["cy"],
            item["bbox"]["cx"],
            item["norm_text"],
        ),
    )


def public_item(item):
    bbox = item["bbox"]

    return {
        "text": item["text"],
        "norm_text": item["norm_text"],
        "confidence": item.get("confidence"),
        "bbox": bbox,
        "page_zone": item.get("page_zone"),
        "is_service_label": bool(item.get("is_service_label")),
        "is_right_vertical": bool(item.get("is_right_vertical")),
    }


def group_lines(items):
    if not items:
        return []

    sorted_items = sort_items(items)
    heights = [
        max(1.0, item["bbox"]["h"])
        for item in sorted_items
    ]
    avg_h = sum(heights) / len(heights)
    y_tolerance = max(12.0, avg_h * 0.6)

    lines = []

    for item in sorted_items:
        cy = item["bbox"]["cy"]

        target_line = None
        for line in lines:
            if abs(line["cy"] - cy) <= y_tolerance:
                target_line = line
                break

        if target_line is None:
            target_line = {
                "cy": cy,
                "items": [],
            }
            lines.append(target_line)

        target_line["items"].append(item)

        count = len(target_line["items"])
        target_line["cy"] = (
            (target_line["cy"] * (count - 1)) + cy
        ) / count

    result = []

    for line in lines:
        line_items = sorted(
            line["items"],
            key=lambda item: item["bbox"]["cx"],
        )

        result.append({
            "cy": round(line["cy"], 2),
            "text": " ".join(item["norm_text"] for item in line_items),
            "items": [public_item(item) for item in line_items],
        })

    return result


def find_dates(items):
    result = []

    for item in items:
        for match in DATE_RE.finditer(item["norm_text"]):
            dd, mm, yyyy = match.groups()
            result.append({
                "value": f"{yyyy}-{mm}-{dd}",
                "source_text": item["text"],
                "norm_text": item["norm_text"],
                "bbox": item["bbox"],
                "page_zone": item.get("page_zone"),
            })

    return result


def find_department_codes(items):
    result = []

    for item in items:
        for match in DEPARTMENT_CODE_RE.finditer(item["norm_text"]):
            value = match.group(0).replace(" ", "-")
            if "-" not in value and len(value) == 6:
                value = value[:3] + "-" + value[3:]

            result.append({
                "value": value,
                "source_text": item["text"],
                "norm_text": item["norm_text"],
                "bbox": item["bbox"],
                "page_zone": item.get("page_zone"),
            })

    return result

def clean_issued_by_line(text):
    norm = normalize_text(text)

    # В issued_by не должны попадать даты и код подразделения.
    norm = DATE_RE.sub(" ", norm)
    norm = DEPARTMENT_CODE_RE.sub(" ", norm)

    cleanup_patterns = [
        r"\bРОССИЙСКАЯ\s*ФЕДЕРАЦИЯ\b",
        r"\bПАСПОРТ\s*ВЫДАН\b",
        r"\bПАСПОРТ\b",
        r"\bВЫДАН\b",
        r"\bДАТА\s*ВЫДАЧИ\b",
        r"\bДАТА\b",
        r"\bВЫДАЧИ\b",
        r"\bКОД\s*ПОДРАЗДЕЛЕНИЯ\b",
        r"\bКОД\b",
        r"\bПОДРАЗДЕЛЕНИЯ\b",
    ]

    for pattern in cleanup_patterns:
        norm = re.sub(pattern, " ", norm)

    norm = re.sub(r"\s+", " ", norm)
    norm = norm.strip(" .,-;:")

    return norm


def is_empty_or_noise_issued_by_line(text):
    norm = normalize_text(text)
    compact = compact_text(norm)

    if not compact:
        return True

    if len(compact) < 3:
        return True

    noise_values = {
        "РОССИЙСКАЯФЕДЕРАЦИЯ",
        "ПАСПОРТ",
        "ВЫДАН",
        "ПАСПОРТВЫДАН",
        "ДАТА",
        "ВЫДАЧИ",
        "ДАТАВЫДАЧИ",
        "КОД",
        "ПОДРАЗДЕЛЕНИЯ",
        "КОДПОДРАЗДЕЛЕНИЯ",
    }

    if compact in noise_values:
        return True

    if compact.isdigit():
        return True

    return False


def first_geo_candidate_value(candidates):
    if not candidates:
        return None

    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            item["bbox"]["cy"],
            item["bbox"]["cx"],
        ),
    )

    return sorted_candidates[0]["value"]

def line_issued_by_text_from_layout_items(line):
    """
    Для верхней страницы берёт issued_by только из value_candidate items.

    Если подпись и значение OCR разделил на разные items:
      [ПАСПОРТ ВЫДАН] [ТЕСТОВЫМ ОТДЕЛОМ МВД]

    вернёт только:
      ТЕСТОВЫМ ОТДЕЛОМ МВД

    Если OCR склеил подпись и значение в один item,
    здесь вернётся пусто, а extract_top_page_fields использует fallback
    через clean_issued_by_line(line["text"]).
    """
    layout_line = annotate_layout_lines_from_grouped_line(line)

    parts = []
    item_debug = []

    for item in layout_line["items"]:
        raw_text = item.get("norm_text") or item.get("text") or ""

        if item.get("value_candidate"):
            cleaned = clean_issued_by_line(raw_text)
            used = bool(cleaned) and not is_empty_or_noise_issued_by_line(cleaned)
        else:
            cleaned = ""
            used = False

        if used:
            parts.append(cleaned)

        item_debug.append({
            "raw_text": raw_text,
            "cleaned_text": cleaned,
            "used": used,
            "label_types": item.get("label_types"),
            "value_candidate": item.get("value_candidate"),
            "combined_label_candidate": item.get("combined_label_candidate"),
            "bbox": item.get("bbox"),
        })

    value = " ".join(parts)
    value = normalize_text(value)
    value = re.sub(r"\s+", " ", value).strip(" .,-;:")

    if is_empty_or_noise_issued_by_line(value):
        value = ""

    return value, item_debug

def extract_top_page_fields(top_items):
    """
    Извлекает только верхнюю страницу:
    - issued_by
    - issue_date
    - department_code

    Нижнюю страницу и ФИО здесь намеренно не трогаем.
    """
    lines = group_lines(top_items)

    date_candidates = find_dates(top_items)
    department_code_candidates = find_department_codes(top_items)

    issue_date = first_geo_candidate_value(date_candidates)
    department_code = first_geo_candidate_value(department_code_candidates)

    boundary_candidates_y = []

    for item in date_candidates:
        boundary_candidates_y.append(item["bbox"]["cy"])

    for item in department_code_candidates:
        boundary_candidates_y.append(item["bbox"]["cy"])

    date_code_y = min(boundary_candidates_y) if boundary_candidates_y else None

    issued_by_lines = []
    issued_by_debug_lines = []

    for line in lines:
        raw_text = line["text"]
        cy = line["cy"]

        # issued_by находится выше строки с датой выдачи и кодом подразделения.
        if date_code_y is not None and cy >= date_code_y - 10:
            issued_by_debug_lines.append({
                "cy": cy,
                "raw_text": raw_text,
                "cleaned_text": "",
                "used": False,
                "reason": "below_or_near_issue_date_code_row",
            })
            continue

        layout_cleaned, item_debug = line_issued_by_text_from_layout_items(line)

        if layout_cleaned:
            cleaned = layout_cleaned
            layout_used = True
            reason = "issued_by_layout_value_candidate"
        else:
            # Fallback для случая, когда OCR склеил подпись и значение
            # в один item/строку.
            cleaned = clean_issued_by_line(raw_text)
            layout_used = False
            reason = "issued_by_fallback_clean_line"

        if is_empty_or_noise_issued_by_line(cleaned):
            issued_by_debug_lines.append({
                "cy": cy,
                "raw_text": raw_text,
                "cleaned_text": cleaned,
                "used": False,
                "layout_used": layout_used,
                "reason": "empty_or_service_label",
                "item_debug": item_debug,
            })
            continue

        issued_by_lines.append(cleaned)

        issued_by_debug_lines.append({
            "cy": cy,
            "raw_text": raw_text,
            "cleaned_text": cleaned,
            "used": True,
            "layout_used": layout_used,
            "reason": reason,
            "item_debug": item_debug,
        })

    issued_by = " ".join(issued_by_lines)
    issued_by = normalize_text(issued_by)
    issued_by = re.sub(r"\s+", " ", issued_by).strip(" .,-;:")

    if not issued_by:
        issued_by = None

    return {
        "fields": {
            "issued_by": issued_by,
            "issue_date": issue_date,
            "department_code": department_code,
        },
        "debug": {
            "date_code_y": date_code_y,
            "issue_date_candidates": date_candidates,
            "department_code_candidates": department_code_candidates,
            "issued_by_lines": issued_by_debug_lines,
            "result": {
                "issued_by": issued_by,
                "issue_date": issue_date,
                "department_code": department_code,
            },
        },
    }
def line_has_word(line_text, word):
    norm = normalize_text(line_text)
    return re.search(rf"\b{word}\b", norm) is not None


def line_has_date(line_text):
    return DATE_RE.search(normalize_text(line_text)) is not None


def clean_person_line(text):
    norm = normalize_text(text)

    remove_patterns = [
        r"\bФАМИЛИЯ\b",
        r"\bИМЯ\b",
        r"\bОТЧЕСТВО\b",
        r"\bПОЛ\b",
        r"\bДАТА\s*РОЖДЕНИЯ\b",
        r"\bДАТА\b",
        r"\bРОЖДЕНИЯ\b",
        r"\bМЕСТО\s*РОЖДЕНИЯ\b",
        r"\bМЕСТО\b",
        r"\bРОЖДЕНИЯ\b",
        r"\bЛИЧНАЯ\s*ПОДПИСЬ\b",
        r"\b[АЛ]ИЧНАЯ\s*ПОД[ПН]ИСЬ\b",
        r"\bПОДПИСЬ\b",
        r"\bПОДНИСЬ\b",
        r"\bМУЖ\.?\b",
        r"\bЖЕН\.?\b",
    ]

    norm = DATE_RE.sub(" ", norm)
    norm = DEPARTMENT_CODE_RE.sub(" ", norm)

    for pattern in remove_patterns:
        norm = re.sub(pattern, " ", norm)

    # Для ФИО оставляем только кириллицу, пробел и дефис.
    norm = re.sub(r"[^А-Я \-]", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip(" -")

    return norm


def normalize_birth_place_value(text):
    """
    Field-specific normalization for RF passport birth_place.

    Не применять глобально: исправления вроде ГОП. -> ГОР.
    безопасны для места рождения, но не обязаны быть безопасными
    для всех строк паспорта.
    """
    norm = normalize_text(text)

    # Типовые OCR-варианты сокращения "ГОР.":
    # - ФОП. уже встречался в тестах;
    # - ГОП. появляется, если OCR увидел кириллическую П вместо Р;
    # - Г0Р. появляется из-за нуля вместо О;
    # - Г О Р / Г О П — варианты с разрывами по символам.
    norm = re.sub(
        r"\b(?:ФОП|ГОП|Г0Р|ГОР)\s*\.\s*",
        "ГОР. ",
        norm,
    )
    norm = re.sub(
        r"\b(?:ФОП|ГОП|Г0Р)\b",
        "ГОР.",
        norm,
    )
    norm = re.sub(
        r"\bГ\s*[О0]\s*[РП]\s*\.\s*",
        "ГОР. ",
        norm,
    )

    norm = re.sub(r"\bГОР\.\s*", "ГОР. ", norm)
    norm = re.sub(r"\s+", " ", norm).strip(" .,-")

    return norm


def clean_birth_place_line(text):
    norm = normalize_text(text)

    remove_patterns = [
        r"\bМЕСТО\s*РОЖДЕНИЯ\b",
        r"\bМЕС\s*Т?\s*О\b",
        r"\bМЕСТ\s*О\b",
        r"\bМЕСТО\b",
        r"\bРОЖДЕНИЯ\b",
        r"\bДАТА\s*РОЖДЕНИЯ\b",
        r"\bДАТА\b",
        r"\bПОЛ\b",
        r"\bМУЖ\.?\b",
        r"\bЖЕН\.?\b",
        r"\bЛИЧНАЯ\s*ПОДПИСЬ\b",
        r"\b[АЛ]ИЧНАЯ\s*ПОД[ПН]ИСЬ\b",
        r"\bПОДПИСЬ\b",
        r"\bПОДНИСЬ\b",
    ]

    norm = DATE_RE.sub(" ", norm)
    norm = DEPARTMENT_CODE_RE.sub(" ", norm)

    for pattern in remove_patterns:
        norm = re.sub(pattern, " ", norm)

    # Для места рождения сохраняем точки/дефисы:
    # ГОР. ТЕСТОВСКА, С. НОВОЕ, Р-Н и т.п.
    norm = re.sub(r"[^А-Я0-9 .\-]", " ", norm)
    norm = normalize_birth_place_value(norm)
    norm = re.sub(r"\s+", " ", norm).strip(" .,-")

    return norm


def is_empty_birth_place_value(text):
    compact = compact_text(text)

    if not compact:
        return True

    noise_values = {
        "МЕСТО",
        "РОЖДЕНИЯ",
        "МЕСТОРОЖДЕНИЯ",
        "ДАТА",
        "ДАТАРОЖДЕНИЯ",
        "ПОЛ",
        "ЛИЧНАЯПОДПИСЬ",
        "АИЧНАЯПОДНИСЬ",
        "ПОДПИСЬ",
        "ПОДНИСЬ",
        "МУЖ",
        "ЖЕН",
    }

    if compact in noise_values:
        return True

    if compact.isdigit():
        return True

    return False


def is_empty_person_value(text):
    compact = compact_text(text)

    if not compact:
        return True

    if len(compact) < 2:
        return True

    noise_values = {
        "ФАМИЛИЯ",
        "ИМЯ",
        "ОТЧЕСТВО",
        "ПОЛ",
        "ДАТА",
        "РОЖДЕНИЯ",
        "ДАТАРОЖДЕНИЯ",
        "МЕСТО",
        "МЕСТОРОЖДЕНИЯ",
        "ЛИЧНАЯПОДПИСЬ",
        "АИЧНАЯПОДНИСЬ",
        "ПОДПИСЬ",
        "ПОДНИСЬ",
        "МУЖ",
        "ЖЕН",
    }

    if compact in noise_values:
        return True

    if compact.isdigit():
        return True

    return False


def join_person_parts(parts):
    cleaned = []

    for part in parts:
        part = clean_person_line(part)
        if not is_empty_person_value(part):
            cleaned.append(part)

    if not cleaned:
        return None

    value = " ".join(cleaned)
    value = re.sub(r"\s+", " ", value).strip(" -")

    return value or None


def find_first_line_index(lines, predicate):
    for idx, line in enumerate(lines):
        if predicate(line):
            return idx

    return None


def find_birth_date_and_line(lines, bottom_items):
    candidates = find_dates(bottom_items)

    if not candidates:
        return None, None, []

    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            item["bbox"]["cy"],
            item["bbox"]["cx"],
        ),
    )

    birth_date = sorted_candidates[0]["value"]
    candidate_y = sorted_candidates[0]["bbox"]["cy"]

    best_idx = None
    best_dist = None

    for idx, line in enumerate(lines):
        dist = abs(line["cy"] - candidate_y)

        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_idx = idx

    return birth_date, best_idx, sorted_candidates


def extract_sex_from_line(text):
    norm = normalize_text(text)
    no_date = DATE_RE.sub(" ", norm)
    compact = compact_text(no_date)

    if "ЖЕН" in compact:
        return "ЖЕН"

    if "МУЖ" in compact:
        return "МУЖ"

    # Осторожный fallback для одиночных букв.
    tokens = re.findall(r"\b[МЖ]\b", no_date)
    if tokens:
        if tokens[0] == "Ж":
            return "Ж"
        if tokens[0] == "М":
            return "М"

    return None


def collect_clean_line_range(lines, start_idx, end_idx, cleaner):
    result = []
    debug = []

    if start_idx is None:
        return result, debug

    if end_idx is None:
        end_idx = len(lines)

    for idx in range(start_idx, max(start_idx, end_idx)):
        if idx < 0 or idx >= len(lines):
            continue

        line = lines[idx]
        raw_text = line["text"]
        cleaned = cleaner(raw_text)

        used = not is_empty_person_value(cleaned)

        if used:
            result.append(cleaned)

        debug.append({
            "idx": idx,
            "cy": line["cy"],
            "raw_text": raw_text,
            "cleaned_text": cleaned,
            "used": used,
        })

    return result, debug

def line_value_text_from_layout_items(
    line,
    cleaner,
    empty_checker=is_empty_person_value,
):
    """
    Возвращает текст строки только из value_candidate items.

    Если layout_analysis ещё не отработал на этой строке,
    используем fallback на полный текст строки.
    """
    layout_line = annotate_layout_lines_from_grouped_line(line)
    parts = []
    item_debug = []

    for item in layout_line["items"]:
        raw_text = item.get("norm_text") or item.get("text") or ""

        if item.get("value_candidate"):
            cleaned = cleaner(raw_text)
            used = bool(cleaned) and not empty_checker(cleaned)
        else:
            cleaned = ""
            used = False

        if used:
            parts.append(cleaned)

        item_debug.append({
            "raw_text": raw_text,
            "cleaned_text": cleaned,
            "used": used,
            "label_types": item.get("label_types"),
            "value_candidate": item.get("value_candidate"),
            "combined_label_candidate": item.get("combined_label_candidate"),
            "bbox": item.get("bbox"),
        })

    value = " ".join(parts)
    value = normalize_text(value)
    value = re.sub(r"\s+", " ", value).strip(" .,-")

    return value, item_debug

def annotate_layout_lines_from_grouped_line(line, line_id=None):
    """
    Аннотирует одну уже сгруппированную OCR-строку.

    Эту функцию используют:
    - debug/layout_analysis;
    - extraction через value_candidate items.

    Поэтому вся логика label/value classification должна жить здесь,
    а не дублироваться в нескольких местах.
    """
    line_items = line.get("items", [])

    heights = []
    for item in line_items:
        bbox = item.get("bbox") or {}
        h = bbox.get("h")
        if isinstance(h, (int, float)) and h > 0:
            heights.append(float(h))

    max_item_height = max(heights) if heights else None
    avg_item_height = (
        sum(heights) / len(heights)
        if heights else None
    )

    sorted_items = sorted(
        line_items,
        key=lambda item: (
            item.get("bbox", {}).get("x1", 0),
            item.get("bbox", {}).get("cx", 0),
        ),
    )

    annotated_items = []

    for item_idx, item in enumerate(sorted_items):
        bbox = item.get("bbox") or {}
        h = bbox.get("h")

        if (
            isinstance(h, (int, float))
            and h > 0
            and max_item_height
            and max_item_height > 0
        ):
            height_ratio = float(h) / float(max_item_height)
        else:
            height_ratio = None

        font_class = classify_font_by_ratio(height_ratio)

        item_text = item.get("norm_text") or item.get("text") or ""
        label_types = detect_label_types(item_text)
        label_types = refine_label_types_by_line_context(
            label_types,
            item_text,
            line.get("text") or "",
        )

        text_label_candidate = bool(label_types)

        font_label_candidate = (
            font_class == "small"
            and item_idx == 0
            and len(sorted_items) >= 2
        )

        combined_label_candidate = (
            text_label_candidate
            or font_label_candidate
        )

        value_candidate = not combined_label_candidate

        annotated_items.append({
            "item_idx": item_idx,
            "text": item.get("text"),
            "norm_text": item.get("norm_text"),
            "confidence": item.get("confidence"),
            "bbox": bbox,
            "height": round(float(h), 2)
            if isinstance(h, (int, float)) else None,
            "height_ratio": round(height_ratio, 3)
            if height_ratio is not None else None,
            "font_class": font_class,
            "label_types": label_types,
            "text_label_candidate": text_label_candidate,
            "font_label_candidate": font_label_candidate,
            "combined_label_candidate": combined_label_candidate,
            "value_candidate": value_candidate,
        })

    return {
        "line_id": line_id,
        "cy": line.get("cy"),
        "text": line.get("text"),
        "max_item_height": round(max_item_height, 2)
        if max_item_height is not None else None,
        "avg_item_height": round(avg_item_height, 2)
        if avg_item_height is not None else None,
        "items": annotated_items,
    }

def collect_value_line_range(lines, start_idx, end_idx, cleaner):
    result = []
    debug = []

    if start_idx is None:
        return result, debug

    if end_idx is None:
        end_idx = len(lines)

    for idx in range(start_idx, max(start_idx, end_idx)):
        if idx < 0 or idx >= len(lines):
            continue

        line = lines[idx]
        value, item_debug = line_value_text_from_layout_items(line, cleaner)

        used = bool(value)

        if used:
            result.append(value)

        debug.append({
            "idx": idx,
            "cy": line["cy"],
            "raw_text": line["text"],
            "cleaned_text": value,
            "used": used,
            "item_debug": item_debug,
        })

    return result, debug

def extract_bottom_page_fields(bottom_items):
    """
    Извлекает нижнюю страницу паспорта по геометрическим строкам:
    - last_name
    - first_name
    - middle_name, только если явно найдено ОТЧЕСТВО
    - sex
    - birth_date
    - birth_place
    """
    lines = group_lines(bottom_items)

    birth_date, birth_date_line_idx, birth_date_candidates = (
        find_birth_date_and_line(lines, bottom_items)
    )

    fam_idx = find_first_line_index(
        lines,
        lambda line: line_has_word(line["text"], "ФАМИЛИЯ"),
    )
    first_name_idx = find_first_line_index(
        lines,
        lambda line: line_has_word(line["text"], "ИМЯ"),
    )
    middle_name_idx = find_first_line_index(
        lines,
        lambda line: line_has_word(line["text"], "ОТЧЕСТВО"),
    )

    # Если меток нет или OCR их плохо прочитал, используем осторожный fallback:
    # строки выше даты рождения считаем зоной ФИО.
    if birth_date_line_idx is not None:
        before_birth_date_idx = birth_date_line_idx
    else:
        before_birth_date_idx = len(lines)

    name_fallback_indices = []
    for idx, line in enumerate(lines[:before_birth_date_idx]):
        cleaned = clean_person_line(line["text"])
        if not is_empty_person_value(cleaned):
            name_fallback_indices.append(idx)

    # Фамилия:
    # от строки ФАМИЛИЯ до строки ИМЯ.
    if fam_idx is not None:
        last_name_end = first_name_idx
        if last_name_end is None:
            last_name_end = before_birth_date_idx

        last_parts, last_debug = collect_value_line_range(
            lines,
            fam_idx,
            last_name_end,
            clean_person_line,
        )
    else:
        last_parts = []
        last_debug = []

        if len(name_fallback_indices) >= 1:
            idx = name_fallback_indices[0]
            cleaned = clean_person_line(lines[idx]["text"])
            last_parts = [cleaned]
            last_debug = [{
                "idx": idx,
                "cy": lines[idx]["cy"],
                "raw_text": lines[idx]["text"],
                "cleaned_text": cleaned,
                "used": True,
                "fallback": True,
            }]

    # Имя:
    # от строки ИМЯ до ОТЧЕСТВО или даты рождения.
    if first_name_idx is not None:
        first_name_end = middle_name_idx
        if first_name_end is None:
            first_name_end = before_birth_date_idx

        first_parts, first_debug = collect_value_line_range(
            lines,
            first_name_idx,
            first_name_end,
            clean_person_line,
        )
    else:
        first_parts = []
        first_debug = []

        if len(name_fallback_indices) >= 2:
            idx = name_fallback_indices[1]
            cleaned = clean_person_line(lines[idx]["text"])
            first_parts = [cleaned]
            first_debug = [{
                "idx": idx,
                "cy": lines[idx]["cy"],
                "raw_text": lines[idx]["text"],
                "cleaned_text": cleaned,
                "used": True,
                "fallback": True,
            }]

    # Отчество пока извлекаем только при явной метке.
    if middle_name_idx is not None:
        middle_parts, middle_debug = collect_value_line_range(
            lines,
            middle_name_idx,
            before_birth_date_idx,
            clean_person_line,
        )
    else:
        middle_parts = []
        middle_debug = []

    last_name = join_person_parts(last_parts)
    first_name = join_person_parts(first_parts)
    middle_name = join_person_parts(middle_parts)

    sex = None
    sex_debug = None

    if birth_date_line_idx is not None:
        date_line = lines[birth_date_line_idx]
        sex = extract_sex_from_line(date_line["text"])
        sex_debug = {
            "idx": birth_date_line_idx,
            "cy": date_line["cy"],
            "raw_text": date_line["text"],
            "sex": sex,
        }

    birth_place_parts = []
    birth_place_debug = []

    if birth_date_line_idx is not None:
        birth_place_start_idx = birth_date_line_idx + 1
    else:
        birth_place_start_idx = before_birth_date_idx

    for idx in range(birth_place_start_idx, len(lines)):
        line = lines[idx]
        raw_text = line["text"]

        cleaned, item_debug = line_value_text_from_layout_items(
            line,
            clean_birth_place_line,
            empty_checker=is_empty_birth_place_value,
        )

        used = bool(cleaned)

        if used:
            birth_place_parts.append(cleaned)

        birth_place_debug.append({
            "idx": idx,
            "cy": line["cy"],
            "raw_text": raw_text,
            "cleaned_text": cleaned,
            "used": used,
            "item_debug": item_debug,
        })

    birth_place = None
    if birth_place_parts:
        birth_place = " ".join(birth_place_parts)
        birth_place = normalize_birth_place_value(birth_place)
        birth_place = re.sub(r"\s+", " ", birth_place).strip(" .,-")
        if not birth_place:
            birth_place = None

    return {
        "fields": {
            "last_name": last_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "birth_date": birth_date,
            "sex": sex,
            "birth_place": birth_place,
        },
        "debug": {
            "line_count": len(lines),
            "lines": lines,
            "indexes": {
                "fam_idx": fam_idx,
                "first_name_idx": first_name_idx,
                "middle_name_idx": middle_name_idx,
                "birth_date_line_idx": birth_date_line_idx,
                "name_fallback_indices": name_fallback_indices,
            },
            "birth_date_candidates": birth_date_candidates,
            "last_name_lines": last_debug,
            "first_name_lines": first_debug,
            "middle_name_lines": middle_debug,
            "sex_line": sex_debug,
            "birth_place_lines": birth_place_debug,
            "result": {
                "last_name": last_name,
                "first_name": first_name,
                "middle_name": middle_name,
                "birth_date": birth_date,
                "sex": sex,
                "birth_place": birth_place,
            },
        },
    }
def detect_label_types(text):
    """
    Диагностическая классификация служебных подписей паспорта
    на уровне отдельного OCR item.

    Важно:
    - это пока не меняет итоговые поля;
    - используется только для debug/layout_analysis;
    - часть подписей уточняется позже на уровне строки.
    """
    compact = compact_text(text)

    if not compact:
        return []

    label_types = []

    def add(label_type):
        if label_type not in label_types:
            label_types.append(label_type)

    if "РОССИЙСКАЯФЕДЕРАЦИЯ" in compact:
        add("service_header")

    if "ПАСПОРТВЫДАН" in compact:
        add("issued_by_label")
    elif compact in {"ПАСПОРТ", "ВЫДАН"}:
        add("issued_by_label")

    if "ДАТАВЫДАЧИ" in compact:
        add("issue_date_label")

    if "КОДПОДРАЗДЕЛЕНИЯ" in compact:
        add("department_code_label")

    if "ФАМИЛИЯ" in compact:
        add("last_name_label")

    # Осторожно: слово ИМЯ может встречаться как часть другого OCR-мусора,
    # поэтому пока только точное компактное совпадение.
    if compact == "ИМЯ":
        add("first_name_label")

    if "ОТЧЕСТВО" in compact:
        add("middle_name_label")

    # ПОЛ иногда читается странно: ILОΛ / IЛОЛ / 1ЛОЛ.
    # Это используем только как label-кандидат, не как значение.
    if compact in {
        "ПОЛ",
        "ILОЛ",
        "IЛОЛ",
        "1ЛОЛ",
        "IОΛ",
        "ILОΛ",
    }:
        add("sex_label")

    # Отдельное слово ДАТА само по себе ещё не говорит,
    # дата выдачи это или дата рождения.
    # Уточним на уровне строки.
    if compact == "ДАТА":
        add("date_label_fragment")

    if "ДАТАРОЖДЕНИЯ" in compact:
        add("birth_date_label")

    # Отдельное слово РОЖДЕНИЯ неоднозначно:
    # - ДАТА РОЖДЕНИЯ
    # - МЕСТО РОЖДЕНИЯ
    # Поэтому на item-level это только общий фрагмент.
    if compact in {"РОЖДЕНИЯ", "РОЖДЕН"}:
        add("birth_related_label_fragment")

    if (
        "МЕСТОРОЖДЕНИЯ" in compact
        or compact in {
            "МЕС",
            "МЕСО",
            "МЕСТ",
            "МЕСТО",
            "МЕСТОРОЖДЕН",
        }
        or re.fullmatch(r"МЕС.?О", compact)
        or re.fullmatch(r"МЕСТ.?О", compact)
    ):
        add("birth_place_label")

    if (
        "ЛИЧНАЯПОДПИСЬ" in compact
        or "АИЧНАЯПОДНИСЬ" in compact
        or compact in {"ПОДПИСЬ", "ПОДНИСЬ"}
    ):
        add("signature_label")

    return label_types

def refine_label_types_by_line_context(item_label_types, item_text, line_text):
    """
    Уточняет неоднозначные фрагменты подписи по всей строке.

    Пример:
      ДАТА + РОЖДЕНИЯ      → birth_date_label
      МЕСRО + РОЖДЕНИЯ     → birth_place_label
    """
    result = list(item_label_types)

    def add(label_type):
        if label_type not in result:
            result.append(label_type)

    item_compact = compact_text(item_text)
    line_compact = compact_text(line_text)

    has_birth_word = (
        "РОЖДЕНИЯ" in line_compact
        or "РОЖДЕН" in line_compact
    )

    has_date_word = (
        "ДАТА" in line_compact
        or "ДАТАРОЖДЕНИЯ" in line_compact
    )

    has_birth_place_word = (
        "МЕСТО" in line_compact
        or "МЕСТ" in line_compact
        or "МЕС" in line_compact
        or re.search(r"МЕС.?О", line_compact) is not None
        or re.search(r"МЕСТ.?О", line_compact) is not None
    )

    # ДАТА РОЖДЕНИЯ: оба фрагмента строки считаем label-якорями даты рождения.
    if has_date_word and has_birth_word:
        if item_compact in {"ДАТА", "РОЖДЕНИЯ", "РОЖДЕН"}:
            add("birth_date_label")

    # МЕСТО РОЖДЕНИЯ: оба фрагмента строки считаем label-якорями места рождения.
    if has_birth_place_word and has_birth_word:
        if (
            item_compact in {
                "МЕС",
                "МЕСО",
                "МЕСТ",
                "МЕСТО",
                "РОЖДЕНИЯ",
                "РОЖДЕН",
            }
            or re.fullmatch(r"МЕС.?О", item_compact)
            or re.fullmatch(r"МЕСТ.?О", item_compact)
        ):
            add("birth_place_label")

    # Если уточнили конкретный тип, общий фрагмент можно оставить в debug,
    # но value_candidate всё равно будет false из-за наличия label_types.
    return result

def classify_font_by_ratio(height_ratio):
    if height_ratio is None:
        return "unknown"

    if height_ratio <= 0.45:
        return "small"

    if height_ratio >= 0.80:
        return "large"

    return "normal"

def annotate_layout_lines(items):
    """
    Строит диагностическую разметку строк/items.

    Ничего не удаляет и не меняет в итоговых полях.
    Только добавляет debug-информацию для следующего шага.
    """
    lines = group_lines(items)
    annotated_lines = []

    for line_id, line in enumerate(lines):
        annotated_lines.append(
            annotate_layout_lines_from_grouped_line(
                line,
                line_id=line_id,
            )
        )

    return annotated_lines

def build_layout_analysis(top_items, bottom_items, right_items):
    return {
        "description": (
            "Diagnostic OCR layout annotation. "
            "Does not affect extracted fields yet."
        ),
        "font_rules": {
            "small": "height_ratio <= 0.45",
            "normal": "0.45 < height_ratio < 0.80",
            "large": "height_ratio >= 0.80",
            "height_ratio": "item bbox height / max item bbox height in same line",
        },
        "top_page_lines": annotate_layout_lines(top_items),
        "bottom_page_lines": annotate_layout_lines(bottom_items),
        "right_vertical_lines": annotate_layout_lines(right_items),
    }

def normalize_document_number_digits(text):
    """
    Нормализует OCR-текст вертикального номера паспорта к цифрам.

    Осторожно исправляем только типовые похожие символы,
    которые часто встречаются в цифровых OCR-блоках.
    """
    if text is None:
        return ""

    raw = unicodedata.normalize("NFKC", str(text)).upper()

    replacements = {
        "O": "0",
        "О": "0",
        "Q": "0",
        "I": "1",
        "L": "1",
        "|": "1",
        "!": "1",
        "З": "3",
        "S": "5",
        "Б": "6",
        "B": "8",
        "В": "8",
    }

    chars = []
    for ch in raw:
        chars.append(replacements.get(ch, ch))

    normalized = "".join(chars)

    return "".join(re.findall(r"\d", normalized))


def format_document_number(digits):
    """
    Для паспорта РФ ожидаем 10 цифр:
    4 цифры серии + 6 цифр номера.

    Возвращаем в читаемом виде:
      9999 999999
    """
    if not digits or len(digits) != 10:
        return None

    return f"{digits[:4]} {digits[4:]}"


def collect_document_number_candidate(page_name, items):
    sorted_items = sorted(
        items,
        key=lambda item: (
            item["bbox"]["cy"],
            item["bbox"]["cx"],
        ),
    )

    item_debug = []
    joined_digits_parts = []

    for item in sorted_items:
        norm_text = item.get("norm_text") or item.get("text") or ""
        digits = normalize_document_number_digits(norm_text)

        if digits:
            joined_digits_parts.append(digits)

        item_debug.append({
            "text": item.get("text"),
            "norm_text": norm_text,
            "digits": digits,
            "bbox": item.get("bbox"),
            "confidence": item.get("confidence"),
        })

    joined_digits = "".join(joined_digits_parts)

    exact_10 = None
    formatted = None

    if len(joined_digits) == 10:
        exact_10 = joined_digits
        formatted = format_document_number(exact_10)
    elif len(joined_digits) > 10:
        # Диагностический fallback:
        # если OCR склеил лишнее, сохраняем первое 10-значное окно.
        # Для production это лучше позже заменить на более строгую проверку
        # совпадения верх/низ.
        exact_10 = joined_digits[:10]
        formatted = format_document_number(exact_10)

    return {
        "page_name": page_name,
        "digits_joined": joined_digits,
        "digits_10": exact_10,
        "formatted": formatted,
        "items": item_debug,
    }


def extract_document_number(right_items, image_height):
    """
    Извлекает вертикальный номер паспорта с правого края.

    На российском паспорте номер обычно дублируется:
    - на верхней странице;
    - на нижней странице.

    Сейчас это debug/validation-поле:
    - если верх и низ совпали, считаем confident;
    - если найден только один 10-значный кандидат, сохраняем его осторожно;
    - если кандидаты конфликтуют, document_number не заполняем,
      но всё пишем в debug.
    """
    if not right_items:
        return {
            "value": None,
            "debug": {
                "status": "no_right_vertical_items",
                "top_candidate": None,
                "bottom_candidate": None,
                "all_right_items_count": 0,
            },
        }

    split_y = image_height * 0.5 if image_height else None

    if split_y is None:
        top_right_items = []
        bottom_right_items = []
        unknown_items = list(right_items)
    else:
        top_right_items = [
            item for item in right_items
            if item["bbox"]["cy"] < split_y
        ]
        bottom_right_items = [
            item for item in right_items
            if item["bbox"]["cy"] >= split_y
        ]
        unknown_items = []

    top_candidate = collect_document_number_candidate(
        "top_page",
        top_right_items,
    )
    bottom_candidate = collect_document_number_candidate(
        "bottom_page",
        bottom_right_items,
    )
    unknown_candidate = collect_document_number_candidate(
        "unknown_page",
        unknown_items,
    )

    candidates = []

    for candidate in [top_candidate, bottom_candidate, unknown_candidate]:
        if candidate["digits_10"]:
            candidates.append(candidate)

    value = None
    status = "not_found"

    top_digits = top_candidate.get("digits_10")
    bottom_digits = bottom_candidate.get("digits_10")

    if top_digits and bottom_digits:
        if top_digits == bottom_digits:
            value = format_document_number(top_digits)
            status = "matched_top_bottom"
        else:
            value = None
            status = "conflict_top_bottom"

    elif len(candidates) == 1:
        value = candidates[0]["formatted"]
        status = "single_candidate"

    elif len(candidates) > 1:
        unique_digits = sorted({
            candidate["digits_10"]
            for candidate in candidates
            if candidate["digits_10"]
        })

        if len(unique_digits) == 1:
            value = format_document_number(unique_digits[0])
            status = "matched_multiple_candidates"
        else:
            value = None
            status = "conflict_multiple_candidates"

    return {
        "value": value,
        "debug": {
            "status": status,
            "all_right_items_count": len(right_items),
            "split_y": split_y,
            "top_candidate": top_candidate,
            "bottom_candidate": bottom_candidate,
            "unknown_candidate": unknown_candidate,
            "selected_value": value,
        },
    }

def add_validation_issue(issues, field, code, message, value=None):
    issues.append({
        "field": field,
        "code": code,
        "message": message,
        "value": value,
    })


def is_iso_date(value):
    if not isinstance(value, str):
        return False

    return re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None


def validate_parsed_output(output):
    """
    Production validation layer.

    Не меняет извлечённые поля.
    Только сообщает, насколько результат пригоден для передачи в 1С.
    """
    errors = []
    warnings = []

    required_fields = [
        "last_name",
        "first_name",
        "birth_date",
        "sex",
        "birth_place",
        "issue_date",
        "department_code",
        "issued_by",
    ]

    for field in required_fields:
        value = output.get(field)

        if value is None or str(value).strip() == "":
            add_validation_issue(
                errors,
                field,
                "missing_required_field",
                "Required field is missing",
                value,
            )

    name_fields = [
        "last_name",
        "first_name",
        "middle_name",
    ]

    for field in name_fields:
        value = output.get(field)

        if value is None:
            continue

        if re.fullmatch(r"[А-Я][А-Я \-]*", value) is None:
            add_validation_issue(
                warnings,
                field,
                "suspicious_name_format",
                "Name field contains unexpected characters",
                value,
            )

    birth_date = output.get("birth_date")
    if birth_date is not None and not is_iso_date(birth_date):
        add_validation_issue(
            errors,
            "birth_date",
            "invalid_date_format",
            "Expected YYYY-MM-DD",
            birth_date,
        )

    issue_date = output.get("issue_date")
    if issue_date is not None and not is_iso_date(issue_date):
        add_validation_issue(
            errors,
            "issue_date",
            "invalid_date_format",
            "Expected YYYY-MM-DD",
            issue_date,
        )

    department_code = output.get("department_code")
    if department_code is not None:
        if re.fullmatch(r"\d{3}-\d{3}", department_code) is None:
            add_validation_issue(
                errors,
                "department_code",
                "invalid_department_code_format",
                "Expected 000-000",
                department_code,
            )

    sex = output.get("sex")
    if sex is not None and sex not in {"МУЖ", "ЖЕН", "М", "Ж"}:
        add_validation_issue(
            errors,
            "sex",
            "invalid_sex_value",
            "Expected МУЖ, ЖЕН, М or Ж",
            sex,
        )

    document_number = output.get("document_number")
    if document_number is None or str(document_number).strip() == "":
        add_validation_issue(
            warnings,
            "document_number",
            "missing_document_number",
            "Document number is missing; field is currently debug/validation only",
            document_number,
        )
    elif re.fullmatch(r"\d{4} \d{6}", document_number) is None:
        add_validation_issue(
            warnings,
            "document_number",
            "invalid_document_number_format",
            "Expected 0000 000000",
            document_number,
        )

    if errors:
        status = "error"
    elif warnings:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "errors_count": len(errors),
            "warnings_count": len(warnings),
        },
    }

def empty_fields():
    return {name: None for name in FIELD_NAMES}


def build_output(data, include_debug=False):
    image_height, image_width = find_image_shape(data)
    raw_items = load_ocr_items(data)

    zones = assign_zones(raw_items, image_height, image_width)

    all_items = zones["items"]
    top_items = zones["top_page_items"]
    bottom_items = zones["bottom_page_items"]
    right_items = zones["right_vertical_items"]

    non_right_items = [
        item for item in all_items
        if not item.get("is_right_vertical")
    ]

    top_page_extraction = extract_top_page_fields(top_items)
    bottom_page_extraction = extract_bottom_page_fields(bottom_items)
    document_number_extraction = extract_document_number(
        right_items,
        image_height,
    )

    output = empty_fields()

    for key, value in top_page_extraction["fields"].items():
        output[key] = value

    for key, value in bottom_page_extraction["fields"].items():
        output[key] = value

    output["document_number"] = document_number_extraction["value"]

    output["validation"] = validate_parsed_output(output)

    if include_debug:
        output["debug"] = {
            "parser_version": "geometry_validation_v1",
            "top_page_extraction": top_page_extraction["debug"],
            "bottom_page_extraction": bottom_page_extraction["debug"],
            "document_number_extraction": document_number_extraction["debug"],
            "layout_analysis": build_layout_analysis(
                top_items,
                bottom_items,
                right_items,
            ),
            "image_shape": {
                "height": image_height,
                "width": image_width,
            },
            "geometry": {
                "split_y": zones["split_y"],
                "zones": {
                    "top_page": {
                        "x1": 0,
                        "y1": 0,
                        "x2": image_width,
                        "y2": zones["split_y"],
                    },
                    "bottom_page": {
                        "x1": 0,
                        "y1": zones["split_y"],
                        "x2": image_width,
                        "y2": image_height,
                    },
                    "right_vertical_filter": {
                        "description": (
                            "items with cx >= 84% image width and "
                            "vertical/narrow or digit-heavy text"
                        ),
                        "min_cx": (
                            round(image_width * 0.84, 2)
                            if image_width else None
                        ),
                    },
                },
                "counts": {
                    "all_items": len(all_items),
                    "top_page_items": len(top_items),
                    "bottom_page_items": len(bottom_items),
                    "right_vertical_items": len(right_items),
                    "non_right_items": len(non_right_items),
                    "service_label_items": len([
                        item for item in all_items
                        if item.get("is_service_label")
                    ]),
                },
                "items": {
                    "top_page_items": [public_item(item) for item in top_items],
                    "bottom_page_items": [public_item(item) for item in bottom_items],
                    "right_vertical_items": [public_item(item) for item in right_items],
                },
                "lines": {
                    "top_page_lines": group_lines(top_items),
                    "bottom_page_lines": group_lines(bottom_items),
                    "right_vertical_lines": group_lines(right_items),
                },
            },
            "diagnostic_candidates": {
                "dates": find_dates(non_right_items),
                "department_codes": find_department_codes(non_right_items),
            },
        }

    return output


def print_summary(output):
    debug = output.get("debug", {})
    geometry = debug.get("geometry", {})
    counts = geometry.get("counts", {})

    print("FIELDS:")
    for name in FIELD_NAMES:
        print(f"{name}: {output.get(name)}")

    print("")
    print("GEOMETRY:")
    print(f"all_items: {counts.get('all_items')}")
    print(f"top_page_items: {counts.get('top_page_items')}")
    print(f"bottom_page_items: {counts.get('bottom_page_items')}")
    print(f"right_vertical_items: {counts.get('right_vertical_items')}")
    print(f"service_label_items: {counts.get('service_label_items')}")


def main():
    parser = argparse.ArgumentParser(
        description="Geometry-first RF passport OCR parser"
    )
    parser.add_argument(
        "input_json",
        help="Path to raw OCR JSON from src/ocr_paddle.py",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Path to parsed output JSON",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Include large debug section in output JSON",
    )

    args = parser.parse_args()

    input_path = Path(args.input_json)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 2

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    output = build_output(
        data,
        include_debug=args.debug,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print_summary(output)
    print("")
    print(f"Saved: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())