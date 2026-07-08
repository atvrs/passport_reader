# Production CLI для passport_reader

## Назначение

`process_photo.py` — основной production-вход для обработки одного изображения разворота паспорта РФ.

Команда принимает фото паспорта, выполняет полный pipeline:

```text
crop → OCR → parse → validation
и записывает итоговый JSON для 1С.

Production-команда
python3 src/process_photo.py input.jpg -o result.json

Пример:

python3 src/process_photo.py /data/in/REQ001.jpg -o /data/out/REQ001.json
Production-контракт файлов

В обычном production-режиме после успешной обработки на диске остаётся только:

result.json

Промежуточные файлы не сохраняются:

crop.jpg
raw_ocr.json
parsed_debug.json
ocr_overlay.jpg
summary.json
PaddleOCR debug folder

Входное изображение после успешного распознавания удаляется.

Поведение при успешной обработке

Если результат валиден:

{
  "validation": {
    "status": "ok"
  }
}

то:

1. result.json записан;
2. входной image file удалён;
3. временный crop удалён автоматически;
4. raw OCR остаётся только в оперативной памяти;
5. parser result остаётся только в оперативной памяти до записи result.json.
Поведение при ошибке

Если произошла ошибка pipeline или validation error:

входное изображение НЕ удаляется

Это нужно для повторной обработки или диагностики.

При ошибке всё равно записывается result.json с ошибочным статусом:

{
  "validation": {
    "status": "error",
    "errors": [
      {
        "field": "__pipeline__",
        "code": "pipeline_failed"
      }
    ]
  }
}
Режим сохранения входного изображения

Для ручных тестов можно запретить удаление входного изображения:

python3 src/process_photo.py input.jpg -o result.json --keep-input

В этом режиме при успешной обработке:

input.jpg остаётся на диске
result.json записывается
Debug-режим

Для диагностики проблемного паспорта используется:

python3 src/process_photo.py input.jpg -o result.json --work-dir debug/case001 --debug-artifacts

В debug-режиме дополнительно сохраняются:

debug/case001/crop/
debug/case001/ocr/*_raw_ocr.json
debug/case001/ocr/*_ocr_overlay.jpg
debug/case001/ocr/<name>/paddle_official/
debug/case001/parse/*_parsed_debug.json
debug/case001/summary.json

При этом result.json всё равно остаётся коротким production JSON без большого debug-блока.

Полный debug JSON лежит отдельно:

debug/case001/parse/*_parsed_debug.json
Формат result.json

Основные поля:

{
  "last_name": "ТЕСТОВ",
  "first_name": "ТЕСТ",
  "middle_name": "ТЕСТОВИЧ",
  "birth_date": "2099-01-31",
  "sex": "МУЖ",
  "birth_place": "ГОР. ТЕСТОВСК",
  "issue_date": "0000-00-00",
  "department_code": "999-999",
  "issued_by": "ТЕСТОВЫМ ОТДЕЛОМ МВД ГОР. ТЕСТОВСКА",
  "document_number": "9999 999999",
  "validation": {
    "status": "ok",
    "errors": [],
    "warnings": [],
    "summary": {
      "errors_count": 0,
      "warnings_count": 0
    }
  }
}
Поля
Поле	Описание
last_name	Фамилия
first_name	Имя
middle_name	Отчество
birth_date	Дата рождения в формате YYYY-MM-DD
sex	Пол: МУЖ, ЖЕН, М, Ж
birth_place	Место рождения
issue_date	Дата выдачи в формате YYYY-MM-DD
department_code	Код подразделения в формате 000-000
issued_by	Орган, выдавший паспорт
document_number	Серия и номер паспорта в формате 0000 000000
validation	Статус пригодности результата
Validation status

Возможные значения:

ok
warning
error
ok

Все обязательные поля найдены и прошли базовую проверку формата.

warning

Основные поля есть, но есть подозрительные признаки. Например:

document_number отсутствует
подозрительный формат имени
низкая уверенность OCR

Часть warning-правил будет расширяться по мере накопления реальных примеров.

error

Результат нельзя считать пригодным для автоматической передачи без разбора.

Примеры:

обязательное поле отсутствует
дата имеет неправильный формат
код подразделения имеет неправильный формат
pipeline упал
Быстрая проверка production-режима

Не запускать на оригинальном sample, если не нужен его delete. Для проверки использовать копию:

rm -rf debug/doc_prod_check
mkdir -p debug/doc_prod_check/in debug/doc_prod_check/out

cp samples/test1.jpg debug/doc_prod_check/in/test1.jpg

python3 src/process_photo.py \
  debug/doc_prod_check/in/test1.jpg \
  -o debug/doc_prod_check/out/result.json

Проверить:

find debug/doc_prod_check -maxdepth 4 -type f | sort

Ожидаемый результат:

debug/doc_prod_check/out/result.json

Входной файл должен быть удалён:

test ! -f debug/doc_prod_check/in/test1.jpg && echo "input deleted"
Быстрая проверка debug-режима
rm -rf debug/doc_debug_check

cp samples/test1.jpg /tmp/passport_test1.jpg

python3 src/process_photo.py \
  /tmp/passport_test1.jpg \
  -o debug/doc_debug_check/result.json \
  --work-dir debug/doc_debug_check \
  --debug-artifacts \
  --keep-input

Проверить:

find debug/doc_debug_check -maxdepth 4 -type f | sort

Ожидаются production JSON и debug artifacts.


---

## 2. Проверка markdown-файла

```bash
cd ~/passport_reader

test -f docs/production_cli.md && sed -n '1,80p' docs/production_cli.md