#!/usr/bin/env python3
import argparse
import json
import os
import cv2
import numpy as np


def load_image(path: str) -> np.ndarray:
    """Загружает изображение. Выбрасывает ошибку, если файл поврежден."""
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(f"Не удалось загрузить изображение: {path}")
    return img


def resize_for_detection(img: np.ndarray, target_width: int = 1200) -> tuple[np.ndarray, float]:
    """Создает уменьшенную копию для детекции и возвращает коэффициент масштабирования."""
    h, w = img.shape[:2]
    scale = target_width / float(w)
    target_height = int(h * scale)
    resized = cv2.resize(img, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return resized, scale


def build_mask(gray: np.ndarray) -> np.ndarray:
    """Строит бинарную маску паспорта для матового черного фона."""
    _, mask = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )

    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)

    return mask


def analyze_components(mask: np.ndarray) -> list[dict]:
    """Находит связные компоненты и считает для них метрики."""
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    h, w = mask.shape
    total_area = h * w
    img_center = np.array([w / 2.0, h / 2.0])
    candidates = []

    # Пропускаем бэкграунд (label 0)
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        area_share = area / total_area

        # Отсекаем совсем мелкий шум
        if area_share < 0.05:
            continue

        bx, by, bw, bh = (
            stats[i, cv2.CC_STAT_LEFT],
            stats[i, cv2.CC_STAT_TOP],
            stats[i, cv2.CC_STAT_WIDTH],
            stats[i, cv2.CC_STAT_HEIGHT],
        )
        bbox_aspect_ratio = bw / float(bh) if bh > 0 else 0

        # Получаем minAreaRect для компоненты
        component_mask = (labels == i).astype(np.uint8) * 255
        contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(c)
        (rx, ry), (rw, rh), angle = rect

        min_w, min_h = min(rw, rh), max(rw, rh)
        minAreaRect_aspect_ratio = min_w / float(min_h) if min_h > 0 else 0
        rect_area = rw * rh
        rect_fill_ratio = area / float(rect_area) if rect_area > 0 else 0

        centroid = centroids[i]
        distance_from_center = float(np.linalg.norm(centroid - img_center) / np.linalg.norm(img_center))

        # Считаем скор (чем выше заполнение, ближе к центру и пропорциям паспорта ~0.7, тем лучше)
        aspect_error = abs(minAreaRect_aspect_ratio - 0.7)
        score = rect_fill_ratio * 2.0 - aspect_error - distance_from_center * 0.5

        candidates.append(
            {
                "label_id": i,
                "area": area,
                "area_share": area_share,
                "bbox_aspect_ratio": bbox_aspect_ratio,
                "minAreaRect_aspect_ratio": minAreaRect_aspect_ratio,
                "rect_fill_ratio": rect_fill_ratio,
                "distance_from_center": distance_from_center,
                "score": score,
                "rect_box": cv2.boxPoints(rect),
            }
        )

    return sorted(candidates, key=lambda x: x["score"], reverse=True)


def order_points(pts: np.ndarray) -> np.ndarray:
    """Сортирует 4 точки в порядке: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1).flatten()
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def warp_passport(orig_img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Вырезает и выравнивает паспорт по его 4 углам."""
    pts = order_points(pts)
    tl, tr, br, bl = pts

    width_a = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    width_b = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    max_width = max(int(width_a), int(width_b))

    height_a = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    height_b = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    max_height = max(int(height_a), int(height_b))

    dst = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]], dtype="float32"
    )

    m = cv2.getPerspectiveTransform(pts, dst)
    return cv2.warpPerspective(orig_img, m, (max_width, max_height))

def normalize_crop_orientation(crop: np.ndarray) -> np.ndarray:
    """
    Нормализует crop паспорта по двум красным машинно-читаемым ориентирам:

    1. Красная полоса сгиба должна быть горизонтальной.
    2. Красная рамка / уголок фотографии должен находиться ниже полосы.

    После выбора ориентации дополнительно уточняет crop:
    обрезает изображение по красной полосе с небольшим запасом.
    """
    variants = [
        ("rot0", crop),
        ("rot90_cw", cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)),
        ("rot180", cv2.rotate(crop, cv2.ROTATE_180)),
        ("rot90_ccw", cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)),
    ]

    def find_red_components(image: np.ndarray) -> list[dict]:
        mask = build_red_mask(image)

        # Для рамки фото полезно чуть сильнее соединить красные элементы.
        h, w = image.shape[:2]

        connect_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (
                max(7, int(w * 0.010)),
                max(7, int(h * 0.010)),
            ),
        )

        connected_mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            connect_kernel,
        )

        contours, _ = cv2.findContours(
            connected_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        components = []

        for contour in contours:
            area = float(cv2.contourArea(contour))

            if area < float(h * w) * 0.00005:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)

            if bw <= 0 or bh <= 0:
                continue

            width_ratio = float(bw) / float(w)
            height_ratio = float(bh) / float(h)
            center_x_ratio = float(x + bw / 2.0) / float(w)
            center_y_ratio = float(y + bh / 2.0) / float(h)
            aspect = float(bw) / float(max(1, bh))

            components.append(
                {
                    "bbox": [
                        int(x),
                        int(y),
                        int(bw),
                        int(bh),
                    ],
                    "area": float(area),
                    "width_ratio": float(width_ratio),
                    "height_ratio": float(height_ratio),
                    "center_x_ratio": float(center_x_ratio),
                    "center_y_ratio": float(center_y_ratio),
                    "aspect": float(aspect),
                }
            )

        return components

    def fold_candidate_score(component: dict) -> float:
        """
        Ищет именно широкую горизонтальную красную полосу сгиба.

        Не допускаем:
        - красные номера серии сверху/сбоку;
        - красные фрагменты рамки фото;
        - любые красные объекты далеко от середины crop.

        Настоящая полоса:
        - широкая;
        - горизонтальная;
        - находится примерно в средней зоне изображения.
        """
        width_ratio = component["width_ratio"]
        height_ratio = component["height_ratio"]
        center_y_ratio = component["center_y_ratio"]
        aspect = component["aspect"]

        # Красная полоса сгиба должна быть широкой.
        # Узкие красные серии паспорта отсекаем.
        if width_ratio < 0.30:
            return -100.0

        # Полоса должна быть около середины по высоте.
        # Это главный фильтр против ложного fold сверху.
        if center_y_ratio < 0.35 or center_y_ratio > 0.65:
            return -100.0

        # Полоса должна быть длинной горизонтальной областью.
        if aspect < 6.0:
            return -100.0

        # Слишком высокий объект — скорее не полоса.
        if height_ratio > 0.12:
            return -100.0

        center_score = 1.0 - min(
            abs(center_y_ratio - 0.5) / 0.15,
            1.0,
        )

        width_score = min(
            (width_ratio - 0.30) / 0.45,
            1.0,
        )

        aspect_score_local = min(
            (aspect - 6.0) / 12.0,
            1.0,
        )

        return (
            center_score * 4.0
            + width_score * 3.0
            + aspect_score_local * 2.0
            - height_ratio * 2.0
        )

    def photo_marker_score(
        component: dict,
        fold_center_y_ratio: float,
    ) -> float:
        """
        Ищет именно красную рамку / уголок фотографии.

        Важно:
        - это не должна быть красная серия паспорта;
        - это не должна быть красная полоса сгиба;
        - маркер должен быть ниже полосы;
        - маркер должен быть достаточно широким и высоким, как рамка фото.
        """
        width_ratio = component["width_ratio"]
        height_ratio = component["height_ratio"]
        center_x_ratio = component["center_x_ratio"]
        center_y_ratio = component["center_y_ratio"]
        aspect = component["aspect"]

        # Фото-маркер должен быть ниже красной полосы.
        if center_y_ratio <= fold_center_y_ratio + 0.06:
            return -100.0

        # Отсекаем красные номера серии: они узкие/маленькие.
        if width_ratio < 0.14:
            return -100.0

        if height_ratio < 0.10:
            return -100.0

        # Рамка фото не должна занимать почти весь документ.
        if width_ratio > 0.70:
            return -100.0

        if height_ratio > 0.60:
            return -100.0

        # Рамка фото ближе к прямоугольнику, а не к длинной линии.
        if aspect < 0.35:
            return -100.0

        if aspect > 4.50:
            return -100.0

        # В правильной ориентации фото находится в нижней левой части.
        # Центр рамки обычно левее середины.
        if center_x_ratio > 0.68:
            return -100.0

        below_score = min(
            (center_y_ratio - fold_center_y_ratio) * 4.0,
            2.0,
        )

        # Предпочитаем левую/лево-среднюю часть, но не требуем строго край.
        left_position_score = 1.0 - min(
            abs(center_x_ratio - 0.28) / 0.45,
            1.0,
        )

        size_score = min(
            (width_ratio + height_ratio) * 4.0,
            2.5,
        )

        aspect_score_local = 1.0 - min(
            abs(aspect - 1.2) / 3.0,
            1.0,
        )

        return (
            below_score * 3.0
            + left_position_score * 3.0
            + size_score * 2.0
            + aspect_score_local * 2.0
        )
    
    def find_marker_layout(
        image: np.ndarray,
        rotation_name: str,
    ) -> dict:
        h, w = image.shape[:2]

        # Rough crop может быть landscape из-за лишнего коврика.
        # Поэтому ориентацию нельзя отбрасывать только по h/w.
        # Правильность определяем по двум маркерам:
        # 1. широкая красная полоса сгиба;
        # 2. красная рамка фото ниже полосы.
        components = find_red_components(image)
        
        fold_candidates = []

        for component in components:
            score = fold_candidate_score(component)

            if score <= -50.0:
                continue

            item = dict(component)
            item["score"] = float(score)
            fold_candidates.append(item)

        fold_candidates.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        layouts = []

        for fold in fold_candidates[:5]:
            fold_x, fold_y, fold_w, fold_h = fold["bbox"]

            fold_center_y_ratio = fold["center_y_ratio"]

            photo_candidates = []

            for component in components:
                component_x, component_y, component_w, component_h = component["bbox"]

                # Не рассматриваем саму полосу как фото-маркер.
                same_as_fold = (
                    abs(component_x - fold_x) < 5
                    and abs(component_y - fold_y) < 5
                    and abs(component_w - fold_w) < 5
                    and abs(component_h - fold_h) < 5
                )

                if same_as_fold:
                    continue

                score = photo_marker_score(
                    component,
                    fold_center_y_ratio,
                )

                if score <= -50.0:
                    continue

                item = dict(component)
                item["score"] = float(score)
                photo_candidates.append(item)

            photo_candidates.sort(
                key=lambda item: item["score"],
                reverse=True,
            )

            if not photo_candidates:
                continue

            photo_marker = photo_candidates[0]
            photo_score = photo_marker["score"]

            # На этапе rough crop не штрафуем landscape:
            # лишний коврик может делать всё изображение широким.
            # Финальную ширину уточнит crop_by_fold_line().
            shape_score = 0.0
            
            total_score = (
                fold["score"] * 3.0
                + photo_score * 4.0
                + shape_score
            )

            layouts.append(
                {
                    "rotation": rotation_name,
                    "score": float(total_score),
                    "shape": [
                        int(h),
                        int(w),
                    ],
                    "fold": fold,
                    "photo_marker": photo_marker,
                    "fold_score": float(fold["score"]),
                    "photo_marker_score": float(photo_score),
                    "shape_score": float(shape_score),
                }
            )

        layouts.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        if not layouts:
            return {
                "rotation": rotation_name,
                "found": False,
                "score": -100.0,
                "shape": [
                    int(h),
                    int(w),
                ],
            }

        best_layout = layouts[0]
        best_layout["found"] = True

        return best_layout

    def crop_by_fold_line(
        image: np.ndarray,
        layout: dict,
    ) -> tuple[np.ndarray, dict]:
        """
        Уточняет crop только по ширине, строго от центра выбранной красной полосы.

        Важно:
        - fold берётся только из layout["fold"];
        - это тот fold, который уже выбрал normalize_crop_orientation();
        - detect_red_fold_line() здесь не используется;
        - по Y ничего не режем;
        - по X режем симметрично от центра bbox красной полосы:
          полная ширина линии + 5% слева + 5% справа.
        """
        if not layout.get("found"):
            return image, {
                "applied": False,
                "reason": "red marker layout not found",
            }

        fold = layout.get("fold")

        if not fold:
            return image, {
                "applied": False,
                "reason": "fold not found in marker layout",
            }

        h, w = image.shape[:2]

        x, y, bw, bh = fold["bbox"]

        x = int(x)
        y = int(y)
        bw = int(bw)
        bh = int(bh)

        if bw <= 0:
            return image, {
                "applied": False,
                "reason": "invalid fold width",
                "fold_bbox": [
                    int(x),
                    int(y),
                    int(bw),
                    int(bh),
                ],
            }

        # Дополнительная страховка: если сюда попал не широкий fold,
        # лучше не резать.
        if bw < w * 0.30:
            return image, {
                "applied": False,
                "reason": "fold bbox is too narrow for safe centered crop",
                "image_shape_before": [
                    int(h),
                    int(w),
                ],
                "fold_bbox": [
                    int(x),
                    int(y),
                    int(bw),
                    int(bh),
                ],
            }

        fold_center_x = x + bw / 2.0

        target_width = int(round(bw * 1.10))
        half_width = target_width / 2.0

        raw_left = int(round(fold_center_x - half_width))
        raw_right = int(round(fold_center_x + half_width))

        # ВАЖНО:
        # не сдвигаем окно, если оно выходит за границы.
        # Только отсекаем по границам изображения.
        # Так сохраняется принцип "от центра красной полосы".
        left = max(0, raw_left)
        right = min(w, raw_right)

        crop_width = right - left

        if crop_width <= 0:
            return image, {
                "applied": False,
                "reason": "invalid centered crop width",
                "image_shape_before": [
                    int(h),
                    int(w),
                ],
                "fold_bbox": [
                    int(x),
                    int(y),
                    int(bw),
                    int(bh),
                ],
                "raw_bbox": [
                    int(raw_left),
                    0,
                    int(raw_right - raw_left),
                    int(h),
                ],
            }

        # Если почти ничего не меняется — оставляем как есть.
        if crop_width > w * 0.98:
            return image, {
                "applied": False,
                "reason": "centered fold crop is almost full width",
                "image_shape_before": [
                    int(h),
                    int(w),
                ],
                "fold_bbox": [
                    int(x),
                    int(y),
                    int(bw),
                    int(bh),
                ],
                "raw_bbox": [
                    int(raw_left),
                    0,
                    int(raw_right - raw_left),
                    int(h),
                ],
                "source_bbox": [
                    int(left),
                    0,
                    int(crop_width),
                    int(h),
                ],
            }

        refined = image[:, left:right]

        return refined, {
            "applied": True,
            "reason": "crop width refined from selected red fold center",
            "image_shape_before": [
                int(h),
                int(w),
            ],
            "image_shape_after": [
                int(refined.shape[0]),
                int(refined.shape[1]),
            ],
            "fold_bbox": [
                int(x),
                int(y),
                int(bw),
                int(bh),
            ],
            "fold_center_x": float(fold_center_x),
            "fold_width": int(bw),
            "target_width": int(target_width),
            "margin_ratio_each_side": 0.05,
            "raw_bbox": [
                int(raw_left),
                0,
                int(raw_right - raw_left),
                int(h),
            ],
            "source_bbox": [
                int(left),
                0,
                int(crop_width),
                int(h),
            ],
            "clipped_left": bool(raw_left < 0),
            "clipped_right": bool(raw_right > w),
        }
    
    layouts = []

    for rotation_name, variant in variants:
        layouts.append(
            find_marker_layout(
                variant,
                rotation_name,
            )
        )

    layouts.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    normalize_crop_orientation.last_scores = layouts

    best_layout = layouts[0]

    normalize_crop_orientation.last_marker_info = best_layout

    if not best_layout.get("found"):
        normalize_crop_orientation.last_refine_info = {
            "applied": False,
            "reason": "no red marker layout found",
        }

        return crop

    best_rotation_name = best_layout["rotation"]

    best_crop = crop

    for rotation_name, variant in variants:
        if rotation_name == best_rotation_name:
            best_crop = variant
            break

    refined_crop, refine_info = crop_by_fold_line(
        best_crop,
        best_layout,
    )

    normalize_crop_orientation.last_refine_info = refine_info

    return refined_crop

def build_red_mask(image: np.ndarray) -> np.ndarray:
    """
    Строит маску красных элементов паспорта.

    Сейчас нужна в первую очередь для поиска красной полосы сгиба.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    lower_red_1 = np.array([0, 40, 40], dtype=np.uint8)
    upper_red_1 = np.array([15, 255, 255], dtype=np.uint8)

    lower_red_2 = np.array([165, 40, 40], dtype=np.uint8)
    upper_red_2 = np.array([179, 255, 255], dtype=np.uint8)

    mask_1 = cv2.inRange(hsv, lower_red_1, upper_red_1)
    mask_2 = cv2.inRange(hsv, lower_red_2, upper_red_2)

    mask = cv2.bitwise_or(mask_1, mask_2)

    h, w = image.shape[:2]

    open_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (3, 3),
    )

    close_kernel_width = max(15, int(w * 0.025))
    close_kernel_height = max(3, int(h * 0.004))

    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (close_kernel_width, close_kernel_height),
    )

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)

    return mask

def rotate_image_by_name(image: np.ndarray, rotation_name: str) -> np.ndarray:
    """
    Возвращает изображение, повернутое по имени варианта.
    Используется для debug и для поиска красной полосы во всех ориентациях.
    """
    if rotation_name == "rot0":
        return image

    if rotation_name == "rot90_cw":
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)

    if rotation_name == "rot180":
        return cv2.rotate(image, cv2.ROTATE_180)

    if rotation_name == "rot90_ccw":
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return image

def detect_red_fold_line(crop: np.ndarray) -> dict:
    """
    Ищет красную полосу сгиба внутри crop, пробуя 4 возможных поворота.

    Это важно, потому что rough crop может быть ориентирован неверно.
    На этом этапе функция только диагностирует полосу и не меняет финальный crop.
    """
    rotation_names = [
        "rot0",
        "rot90_cw",
        "rot180",
        "rot90_ccw",
    ]

    all_candidates = []

    for rotation_name in rotation_names:
        image = rotate_image_by_name(crop, rotation_name)

        h, w = image.shape[:2]

        mask = build_red_mask(image)

        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        for contour in contours:
            area = float(cv2.contourArea(contour))

            if area < float(h * w) * 0.0001:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)

            if bw <= 0 or bh <= 0:
                continue

            width_ratio = float(bw) / float(w)
            height_ratio = float(bh) / float(h)

            center_x_ratio = float(x + bw / 2.0) / float(w)
            center_y_ratio = float(y + bh / 2.0) / float(h)

            aspect = float(bw) / float(max(1, bh))

            # Нас интересует горизонтальная красная полоса.
            if width_ratio < 0.18:
                continue

            if aspect < 2.5:
                continue

            if height_ratio > 0.25:
                continue

            area_ratio = area / float(h * w)

            # Центр — полезный признак, но не жёсткий фильтр.
            # На плохом rough crop полоса может быть не по центру всего изображения.
            center_bonus = 1.0 - min(
                abs(center_y_ratio - 0.5) * 2.0,
                1.0,
            )

            score = (
                width_ratio * 4.0
                + min(aspect / 10.0, 2.0)
                + min(area_ratio * 150.0, 2.0)
                + center_bonus * 0.75
                - height_ratio * 2.0
            )

            rect = cv2.minAreaRect(contour)
            rect_w, rect_h = rect[1]
            angle = float(rect[2])

            if rect_w < rect_h:
                angle += 90.0

            while angle > 90.0:
                angle -= 180.0

            while angle <= -90.0:
                angle += 180.0

            all_candidates.append(
                {
                    "score": float(score),
                    "rotation": rotation_name,
                    "image_shape": [
                        int(h),
                        int(w),
                    ],
                    "bbox": [
                        int(x),
                        int(y),
                        int(bw),
                        int(bh),
                    ],
                    "area": float(area),
                    "area_ratio": float(area_ratio),
                    "width_ratio": float(width_ratio),
                    "height_ratio": float(height_ratio),
                    "center_x_ratio": float(center_x_ratio),
                    "center_y_ratio": float(center_y_ratio),
                    "aspect": float(aspect),
                    "angle_degrees": float(angle),
                }
            )

    all_candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    if not all_candidates:
        return {
            "found": False,
            "confidence": 0.0,
            "candidates": [],
        }

    best = all_candidates[0]

    confidence = min(
        max(best["score"] / 7.0, 0.0),
        1.0,
    )

    return {
        "found": True,
        "confidence": float(confidence),
        "best": best,
        "candidates": all_candidates[:8],
    }

def save_red_fold_debug(
    crop: np.ndarray,
    fold_info: dict,
    debug_dir: str,
) -> None:
    """
    Сохраняет debug-файлы по поиску красной полосы.

    Если красная полоса найдена в повернутом варианте crop,
    debug-картинки сохраняются именно в этой найденной ориентации.
    """
    os.makedirs(debug_dir, exist_ok=True)

    rotation_name = "rot0"

    if fold_info.get("found"):
        rotation_name = fold_info["best"].get("rotation", "rot0")

    debug_crop = rotate_image_by_name(crop, rotation_name)

    mask = build_red_mask(debug_crop)

    cv2.imwrite(
        os.path.join(debug_dir, "red_fold_mask.jpg"),
        mask,
    )

    overlay = debug_crop.copy()

    if fold_info.get("found"):
        x, y, bw, bh = fold_info["best"]["bbox"]

        cv2.rectangle(
            overlay,
            (x, y),
            (x + bw, y + bh),
            (0, 255, 0),
            3,
        )

        center_y = y + bh // 2

        cv2.line(
            overlay,
            (0, center_y),
            (overlay.shape[1], center_y),
            (0, 255, 0),
            2,
        )

        text = "red fold found: " + rotation_name

    else:
        text = "red fold not found"

    cv2.putText(
        overlay,
        text,
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    cv2.imwrite(
        os.path.join(debug_dir, "red_fold_overlay.jpg"),
        overlay,
    )

    with open(
        os.path.join(debug_dir, "red_fold_info.json"),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            fold_info,
            f,
            ensure_ascii=False,
            indent=2,
        )

def save_red_marker_debug(
    crop: np.ndarray,
    marker_info: dict,
    refine_info: dict,
    debug_dir: str,
) -> None:
    """
    Сохраняет debug по новому алгоритму:
    - найденная красная полоса;
    - найденный красный маркер фото;
    - bbox уточняющей обрезки.
    """
    os.makedirs(debug_dir, exist_ok=True)

    overlay = crop.copy()
    
    offset_x = 0
    offset_y = 0

    if refine_info.get("applied") and refine_info.get("source_bbox"):
        offset_x = int(refine_info["source_bbox"][0])
        offset_y = int(refine_info["source_bbox"][1])

    def shifted_bbox(bbox: list[int]) -> list[int]:
        x, y, bw, bh = bbox

        return [
            int(x - offset_x),
            int(y - offset_y),
            int(bw),
            int(bh),
        ]

    if marker_info.get("found"):
        fold = marker_info.get("fold")
        photo_marker = marker_info.get("photo_marker")

        if fold:
            x, y, bw, bh = shifted_bbox(fold["bbox"])

            cv2.rectangle(
                overlay,
                (x, y),
                (x + bw, y + bh),
                (0, 255, 0),
                3,
            )

            cv2.putText(
                overlay,
                "fold",
                (x, max(30, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

        if photo_marker:
            x, y, bw, bh = shifted_bbox(photo_marker["bbox"])

            cv2.rectangle(
                overlay,
                (x, y),
                (x + bw, y + bh),
                (255, 0, 0),
                3,
            )

            cv2.putText(
                overlay,
                "photo marker",
                (x, max(30, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 0, 0),
                2,
                cv2.LINE_AA,
            )

        text = "red markers: " + marker_info.get("rotation", "unknown")

    else:
        text = "red markers not found"

    cv2.putText(
        overlay,
        text,
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    cv2.imwrite(
        os.path.join(debug_dir, "red_markers_overlay.jpg"),
        overlay,
    )

    with open(
        os.path.join(debug_dir, "red_markers_info.json"),
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            {
                "marker_info": marker_info,
                "refine_info": refine_info,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

def save_debug_images(
    debug_dir: str,
    resized: np.ndarray,
    gray: np.ndarray,
    mask: np.ndarray,
    candidates: list,
    best_candidate: dict | None,
    crop: np.ndarray,
):
    """Сохраняет отладочные файлы для визуального контроля."""
    os.makedirs(debug_dir, exist_ok=True)

    cv2.imwrite(os.path.join(debug_dir, "original_resized.jpg"), resized)
    cv2.imwrite(os.path.join(debug_dir, "gray.jpg"), gray)
    cv2.imwrite(os.path.join(debug_dir, "mask.jpg"), mask)
    cv2.imwrite(os.path.join(debug_dir, "crop.jpg"), crop)

    # overlay всех валидных компонент
    comp_overlay = resized.copy()
    for c in candidates:
        box = np.array(c["rect_box"], dtype=np.int32)
        cv2.drawContours(comp_overlay, [box], 0, (0, 0, 255), 2)
        cv2.putText(
            comp_overlay,
            f"S:{c['score']:.2f}",
            (box[0][0], box[0][1] - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
        )
    cv2.imwrite(os.path.join(debug_dir, "components_overlay.jpg"), comp_overlay)

    # overlay лучшего кандидата
    best_overlay = resized.copy()
    if best_candidate:
        box = np.array(best_candidate["rect_box"], dtype=np.int32)
        cv2.drawContours(best_overlay, [box], 0, (0, 255, 0), 3)
    cv2.imwrite(os.path.join(debug_dir, "best_candidate_overlay.jpg"), best_overlay)

    # Сброс метрик без поля 'rect_box' (оно не сериализуется в json напрямую)
    metrics = []
    for c in candidates:
        item = {k: v for k, v in c.items() if k != "rect_box"}
        metrics.append(item)
    with open(os.path.join(debug_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=4, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Production Passport Cropper v1")
    parser.add_argument("input", help="Путь к исходному файлу изображения")
    parser.add_argument("-o", "--output", required=True, help="Путь для сохранения результата кропа")
    parser.add_argument("--debug-dir", help="Директория для сохранения debug-данных")
    args = parser.parse_args()

    # 1. Загрузка
    orig_img = load_image(args.input)

    # 2. Изменение размера для быстрой детекции
    resized, scale = resize_for_detection(orig_img, target_width=1200)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

      # 4. Построение маски
    mask = build_mask(gray)

    # 5-7. Поиск и скоринг компонент
    candidates = analyze_components(mask)
    if not candidates:
        raise RuntimeError("На изображении не найдено ни одного подходящего объекта.")

    best = candidates[0]

    # 8-9. Пересчет координат обратно в оригинальное разрешение
    resized_box = best["rect_box"]
    orig_box = resized_box / scale

    # 10. WarpPerspective на оригинальном разрешении
    crop = warp_passport(orig_img, orig_box)

    # 11. Выравнивание в горизонтальную ориентацию
    crop = normalize_crop_orientation(crop)

    orientation_scores = getattr(
        normalize_crop_orientation,
        "last_scores",
        [],
    )

    marker_info = getattr(
        normalize_crop_orientation,
        "last_marker_info",
        {},
    )

    refine_info = getattr(
        normalize_crop_orientation,
        "last_refine_info",
        {},
    )

    # Это теперь только пост-контроль после нормализации.
    # Не использовать этот fold_info как источник для обрезки.
    fold_info = detect_red_fold_line(crop)

    if args.debug_dir:
        save_red_fold_debug(crop, fold_info, args.debug_dir)

        save_red_marker_debug(
            crop,
            marker_info,
            refine_info,
            args.debug_dir,
        )

        with open(
            os.path.join(args.debug_dir, "orientation_scores.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                orientation_scores,
                f,
                ensure_ascii=False,
                indent=2,
            )

        with open(
            os.path.join(args.debug_dir, "crop_refine_info.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                refine_info,
                f,
                ensure_ascii=False,
                indent=2,
            )

    # 12. Сохранение результата
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    cv2.imwrite(args.output, crop)

    # 13. Сохранение дебага при необходимости
    if args.debug_dir:
        save_debug_images(args.debug_dir, resized, gray, mask, candidates, best, crop)


if __name__ == "__main__":
    main()
