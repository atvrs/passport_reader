# Service mode

## Назначение

`src/passport_service.py` — основной production-сервис файловой интеграции с 1С.

Сервис:

```text
1. запускается один раз;
2. инициализирует PaddleOCR один раз при старте;
3. ждёт command JSON;
4. обрабатывает паспорта по одному;
5. пишет итоговый JSON;
6. архивирует успешные кейсы;
7. удаляет входное изображение после успешной обработки;
8. сохраняет диагностические данные при ошибке.
```

HTTP API не используется.

## Production-запуск

Обычно запуск идёт через systemd:

```bash
sudo systemctl restart passport-reader.service
```

Ручной запуск для диагностики:

```bash
cd /opt/passport_reader

python3 src/passport_service.py \
  --commands-dir /data/passport_reader/commands \
  --processing-dir /data/passport_reader/processing \
  --input-dir /data/passport_reader/in \
  --output-dir /data/passport_reader/out \
  --error-dir /data/passport_reader/error \
  --work-dir /data/passport_reader/work \
  --archive-dir /data/passport_reader/archive \
  --archive-retention-days 30 \
  --archive-max-gb 5 \
  --out-retention-days 7 \
  --ocr-max-side 1800 \
  --lock-file /data/passport_reader/passport_service.lock \
  --log-file /data/passport_reader/logs/passport_service.log \
  --log-total-max-mb 100 \
  --status-file /data/passport_reader/status/service_status.json \
  --heartbeat-sec 10
```

Перед ручным запуском systemd-сервис должен быть остановлен, иначе сработает lock.

```bash
sudo systemctl stop passport-reader.service
```

## Протокол обработки

1. 1С полностью записывает изображение в `in/`.
2. 1С атомарно создаёт command JSON в `commands/`.
3. Сервис переносит command JSON в `processing/`.
4. Сервис запускает pipeline:

```text
crop -> OCR -> parse -> validation -> save result
```

5. Сервис атомарно пишет result JSON в `out/`.
6. При успешной обработке сервис архивирует успешный кейс и удаляет входной JPG.

## Command JSON

Минимальный вариант:

```json
{
  "request_id": "REQ001",
  "image_file": "REQ001.jpg"
}
```

Будущий multi-document вариант допускает дополнительное поле:

```json
{
  "request_id": "REQ001",
  "image_file": "REQ001.jpg",
  "document_type": "rf_internal"
}
```

Пока отсутствие `document_type` должно трактоваться как:

```text
rf_internal
```

## Output JSON

Основные поля:

```text
last_name
first_name
middle_name
birth_date
sex
birth_place
issue_date
department_code
issued_by
document_number
validation
timing
```

`validation.status`:

```text
ok
warning
error
```

## Timing

В result/status/log сохраняются основные времена:

```text
crop_sec
ocr_sec
parse_sec
save_result_sec
total_sec
```

Ожидаемое production-время на текущем стенде:

```text
около 2 секунд на документ
```

## OCR resize

Текущая production-настройка:

```text
--ocr-max-side 1800
```

Это уменьшает crop только для OCR-этапа. Исходное изображение и архивный input не меняются.

`0` отключает resize.

## Debug artifacts

В production debug-артефакты выключены. Сохраняется только итоговый result JSON и архив успешных кейсов.

Для диагностики можно запускать отдельные debug-скрипты вручную, не включая постоянное сохранение debug в production.
