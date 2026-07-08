# Systemd service: passport-reader.service

## Назначение

`passport-reader.service` запускает production-сервис файлового распознавания паспортов.

Сервис:

```text
1. стартует как systemd daemon;
2. один раз инициализирует PaddleOCR;
3. ждёт command JSON в /data/passport_reader/commands;
4. переносит команду в /data/passport_reader/processing;
5. обрабатывает документы последовательно;
6. пишет result JSON в /data/passport_reader/out;
7. при успешном результате архивирует JPEG + command JSON + result JSON;
8. после успешного результата удаляет входной JPG и command JSON;
9. пишет heartbeat/status JSON.
```

HTTP API не используется.

## Production-путь

```text
/opt/passport_reader
```

Рабочая git-ветка:

```text
main
```

## Unit-файл

Шаблон unit-файла в репозитории:

```text
deploy/passport-reader.service
```

Production unit:

```text
/etc/systemd/system/passport-reader.service
```

## Проверить unit

```bash
systemctl cat passport-reader.service
```

Ключевые параметры должны указывать на:

```text
WorkingDirectory=/opt/passport_reader
ExecStart=/usr/bin/python3 /opt/passport_reader/src/passport_service.py
```

## Основные директории

```text
/data/passport_reader/commands
/data/passport_reader/processing
/data/passport_reader/in
/data/passport_reader/out
/data/passport_reader/error
/data/passport_reader/work
/data/passport_reader/archive
/data/passport_reader/logs
/data/passport_reader/status
```

## Основные параметры запуска

```text
--commands-dir /data/passport_reader/commands
--processing-dir /data/passport_reader/processing
--input-dir /data/passport_reader/in
--output-dir /data/passport_reader/out
--error-dir /data/passport_reader/error
--work-dir /data/passport_reader/work
--archive-dir /data/passport_reader/archive
--archive-retention-days 30
--archive-max-gb 5
--out-retention-days 7
--ocr-max-side 1800
--lock-file /data/passport_reader/passport_service.lock
--log-file /data/passport_reader/logs/passport_service.log
--log-total-max-mb 100
--status-file /data/passport_reader/status/service_status.json
--heartbeat-sec 10
```

## Установка unit

```bash
cd /opt/passport_reader

sudo cp deploy/passport-reader.service /etc/systemd/system/passport-reader.service
sudo systemctl daemon-reload
sudo systemctl enable passport-reader.service
sudo systemctl restart passport-reader.service
```

## Управление сервисом

Статус:

```bash
systemctl status passport-reader.service --no-pager
```

Перезапуск:

```bash
sudo systemctl restart passport-reader.service
```

Остановка:

```bash
sudo systemctl stop passport-reader.service
```

Автозапуск:

```bash
sudo systemctl enable passport-reader.service
```

Проверка автозапуска:

```bash
systemctl is-enabled passport-reader.service
```

## Логи

Основной лог:

```bash
tail -n 200 /data/passport_reader/logs/passport_service.log
```

Systemd journal:

```bash
journalctl -u passport-reader.service -n 200 --no-pager
```

## Status heartbeat

```bash
cat /data/passport_reader/status/service_status.json
```

Этот файл обновляется сервисом и содержит текущее состояние, счётчики и последние timing-метрики.

## Lock-файл

```text
/data/passport_reader/passport_service.lock
```

Сервис должен запускаться в одном экземпляре. Если второй экземпляр не стартует из-за lock — это штатная защита.

После аварийной остановки сначала проверить процессы:

```bash
ps aux | grep passport_service.py | grep -v grep
```

Удалять lock вручную можно только когда точно нет запущенного сервиса.

## Production deploy

```bash
cd /opt/passport_reader

git pull --rebase origin main
python3 -m py_compile src/parse_passport.py src/process_photo.py src/passport_service.py
python3 tools/test_parser_birth_place.py
sudo systemctl restart passport-reader.service
./tools/test_local_service.sh
```

После этого выполнить SMB-тест с сервера 1С.
