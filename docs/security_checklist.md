# Security checklist

## Цель

Ограничить доступ к файловому обмену паспортов и не хранить лишние персональные данные дольше необходимого.

## Текущая модель доступа

```text
OCR-сервер: OCR-SERVER
1С-сервер:  1C-SERVER
SMB share:  \\OCR-SERVER\passport_reader
```

Доступ к SMB-шаре должен быть разрешён только с 1С-сервера.

## Samba

Ожидаемая логика:

```text
1. guest/RW доступ только с 1C-SERVER;
2. доступ к служебным директориям скрыт/запрещён;
3. запись идёт от выделенного локального пользователя;
4. 1С видит только in, commands, out.
```

Проверить конфигурацию:

```bash
testparm -s
```

Проверить активные подключения:

```bash
sudo smbstatus
```

## Firewall

Разрешить SMB только с 1С-сервера:

```text
TCP 445 from 1C-SERVER
```

Проверка UFW:

```bash
sudo ufw status verbose
```

## Права на директории

Проверить:

```bash
ls -ld /data/passport_reader
ls -ld /data/passport_reader/in
ls -ld /data/passport_reader/commands
ls -ld /data/passport_reader/out
ls -ld /data/passport_reader/archive
ls -ld /data/passport_reader/logs
ls -ld /data/passport_reader/status
```

1С не должна иметь прямой доступ к:

```text
processing
error
archive
logs
status
work
```

## Retention

Production-лимиты:

```text
out_retention_days = 7
archive_retention_days = 30
archive_max_gb = 5
log_total_max_mb = 100
```

Проверить размер archive:

```bash
du -sh /data/passport_reader/archive
```

Проверить result JSON старше 7 дней:

```bash
find /data/passport_reader/out -type f -name '*.json' -mtime +7 -print
```

## Логи

Логи не должны содержать полные OCR-сырые данные или изображения.

Основной лог:

```text
/data/passport_reader/logs/passport_service.log
```

## Backup/архив

Архив успешных кейсов содержит персональные данные и изображения паспорта. Его нельзя копировать в небезопасные места.

Для передачи проекта на анализ использовать snapshot без:

```text
/data/passport_reader/archive
/data/passport_reader/in
/data/passport_reader/out
реальных фото паспортов
```

## Проверка после reboot

```bash
systemctl is-enabled passport-reader.service
systemctl status passport-reader.service --no-pager
cat /data/passport_reader/status/service_status.json
```

## Минимальная периодическая проверка

```bash
cd /opt/passport_reader
./tools/check_production_status.sh
```
