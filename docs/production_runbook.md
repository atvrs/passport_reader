# Production runbook: passport_reader

## Назначение

`passport_reader` — файловый production-сервис распознавания паспортов для интеграции с 1С.

Текущий production-вариант:

```text
код:      /opt/passport_reader
ветка:    main
service:  passport-reader.service
обмен:    /data/passport_reader
SMB:      \\OCR-SERVER\passport_reader
```

Сервис работает без HTTP. 1С пишет фото и командный JSON в SMB-шару, сервис обрабатывает задание и пишет result JSON.

## Основные директории

```text
/data/passport_reader/in          входные изображения
/data/passport_reader/commands    входные команды от 1С
/data/passport_reader/out         готовые result JSON
/data/passport_reader/processing  команда, взятая в работу
/data/passport_reader/error       ошибочные command JSON
/data/passport_reader/work        временные файлы обработки
/data/passport_reader/archive     архив успешных кейсов
/data/passport_reader/logs        логи сервиса
/data/passport_reader/status      service_status.json
```

1С должна использовать только:

```text
/data/passport_reader/in
/data/passport_reader/commands
/data/passport_reader/out
```

## Проверка production-состояния

```bash
cd /opt/passport_reader

./tools/check_production_status.sh
```

Ручной минимум:

```bash
cd /opt/passport_reader

git branch --show-current
git rev-parse --short HEAD
git status --short

systemctl status passport-reader.service --no-pager
tail -n 60 /data/passport_reader/logs/passport_service.log
cat /data/passport_reader/status/service_status.json
```

Ожидаемо:

```text
ветка main
рабочее дерево чистое
passport-reader.service active/running
service_status.json обновляется
```

## Перезапуск сервиса

```bash
sudo systemctl restart passport-reader.service
sudo systemctl status passport-reader.service --no-pager
tail -n 80 /data/passport_reader/logs/passport_service.log
```

В логе должны появиться строки вида:

```text
Starting passport service
Service lock acquired
Initializing PaddleOCR once...
PaddleOCR initialized in ... sec
```

## Локальный end-to-end тест на OCR-сервере

Тест без SMB, напрямую через `/data/passport_reader`:

```bash
cd /opt/passport_reader
./tools/test_local_service.sh
```

По умолчанию используется:

```text
/opt/passport_reader/samples/test1.jpg
```

Другой файл можно передать первым аргументом:

```bash
./tools/test_local_service.sh /path/to/passport.jpg
```

Для эталонного `test1.jpg` ожидается:

```text
validation.status: ok
birth_place: ГОР. ТЕСТОВСК
```

## Parser regression test

```bash
cd /opt/passport_reader
python3 tools/test_parser_birth_place.py
```

Проверяет критичные OCR-нормализации:

```text
ГОП.ТЕСТОВСК -> ГОР. ТЕСТОВСК
ГОP.ТЕСТОВСК -> ГОР. ТЕСТОВСК
ФОП.ТЕСТОВСК -> ГОР. ТЕСТОВСК
Г0Р.ТЕСТОВСК -> ГОР. ТЕСТОВСК
```

## SMB end-to-end тест с сервера 1С

На Windows/1С-сервере:

```powershell
cd C:\Users\vrs
powershell -ExecutionPolicy Bypass -File .\test_ocr_smb_ps2.ps1
```

Ожидаемый результат:

```text
SMB ACCESS TEST: ok
SMB WRITE / RENAME / DELETE TEST: ok
OCR END-TO-END TEST: ok
validation.status: ok
birth_place: ГОР. ТЕСТОВСК
```

## Типовой production deploy

```bash
cd /opt/passport_reader

git pull --rebase origin main
python3 -m py_compile src/parse_passport.py src/process_photo.py src/passport_service.py
python3 tools/test_parser_birth_place.py
sudo systemctl restart passport-reader.service
./tools/test_local_service.sh
```

После этого выполнить SMB-тест с сервера 1С.

## Где смотреть ошибки

Лог сервиса:

```bash
tail -n 200 /data/passport_reader/logs/passport_service.log
```

Текущий статус:

```bash
cat /data/passport_reader/status/service_status.json
```

Ошибочные команды:

```bash
ls -lah /data/passport_reader/error
```

Необработанные команды:

```bash
ls -lah /data/passport_reader/commands
ls -lah /data/passport_reader/processing
```

## Что делать, если результат не появился

1. Проверить, что JPG есть в `in/`.
2. Проверить, что command JSON появился именно в `commands/*.json`, не только `.tmp`.
3. Проверить лог сервиса.
4. Проверить `error/`.
5. Проверить права SMB и локальные права на `/data/passport_reader`.
6. Проверить, что `passport-reader.service` запущен.

Команды:

```bash
systemctl status passport-reader.service --no-pager
ls -lah /data/passport_reader/in
ls -lah /data/passport_reader/commands
ls -lah /data/passport_reader/processing
ls -lah /data/passport_reader/error
tail -n 200 /data/passport_reader/logs/passport_service.log
```

## Что делать, если parser-ошибка появилась после правок

Вернуться к последнему рабочему commit:

```bash
cd /opt/passport_reader

git log --oneline -10
git status --short
```

Если рабочее дерево чистое и нужно откатиться:

```bash
git reset --hard <GOOD_COMMIT>
sudo systemctl restart passport-reader.service
./tools/test_local_service.sh
```

## Retention

Production-настройки:

```text
archive_retention_days = 30
archive_max_gb = 5
out_retention_days = 7
log_total_max_mb = 100
```

Архив успешных кейсов:

```text
/data/passport_reader/archive/YYYY-MM/YYYY-MM-DD/<request_id>/
  input.jpg
  command.json
  result.json
```

1С может удалять result JSON после чтения. Если не удалит, сервис удалит старые result JSON автоматически.
