# Файловый обмен с 1С

## Production root

```text
/data/passport_reader
```

SMB-путь для 1С-сервера:

```text
\\OCR-SERVER\passport_reader
```

## Директории для 1С

1С использует только эти директории:

```text
/data/passport_reader/in
/data/passport_reader/commands
/data/passport_reader/out
```

Эквивалентные SMB-пути:

```text
\\OCR-SERVER\passport_reader\in
\\OCR-SERVER\passport_reader\commands
\\OCR-SERVER\passport_reader\out
```

Служебные директории сервиса:

```text
/data/passport_reader/processing
/data/passport_reader/error
/data/passport_reader/archive
/data/passport_reader/logs
/data/passport_reader/status
/data/passport_reader/work
```

1С не должна писать в служебные директории.

## Создание задания

Для каждого паспорта 1С создаёт уникальный `request_id`.

Рекомендуемый формат:

```text
REQ_YYYYMMDD_HHMMSS_GUID
```

Пример:

```text
REQ_20260708_125353_6f4b2c
```

## Правильный порядок записи

Команда `.json` должна появляться последней.

Правильный порядок:

1. Записать изображение во временный файл:

```text
in/REQ001.jpg.tmp
```

2. После полной записи атомарно переименовать:

```text
REQ001.jpg.tmp -> REQ001.jpg
```

3. Записать команду во временный файл:

```text
commands/REQ001.json.tmp
```

4. После полной записи атомарно переименовать:

```text
REQ001.json.tmp -> REQ001.json
```

Появление файла:

```text
commands/REQ001.json
```

является сигналом сервису, что изображение полностью готово к обработке.

Нельзя создавать command JSON до завершения записи JPG.

## Минимальный command JSON

```json
{
  "request_id": "REQ001",
  "image_file": "REQ001.jpg"
}
```

Поля:

```text
request_id  уникальный идентификатор задания
image_file  имя файла изображения в директории in/
```

`request_id` должен совпадать с именем result JSON:

```text
out/REQ001.json
```

## Кодировка command JSON

Рекомендуемая кодировка:

```text
UTF-8 without BOM
```

Сервис также принимает:

```text
UTF-8 with BOM
```

Это сделано для совместимости со старыми Windows/PowerShell/1С-окружениями.

## Чтение результата

1С ждёт файл:

```text
out/REQ001.json
```

Готовым считается только файл с расширением `.json`.

Файлы `.tmp` читать нельзя.

## Успешный result JSON

Пример:

```json
{
  "last_name": "ТЕСТОВ",
  "first_name": "ТЕСТ",
  "middle_name": "ТЕСТОВИЧ",
  "birth_date": "2099-01-31",
  "sex": "МУЖ",
  "birth_place": "ГОР. ТЕСТОВСК",
  "issue_date": "2099-02-28",
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
```

## Статусы validation

```text
ok       результат пригоден для автоматической передачи в 1С
warning  критичных ошибок нет, но есть предупреждения
error    результат непригоден без ручной проверки
```

На текущем этапе 1С должна считать полностью автоматическим только:

```text
validation.status == "ok"
```

## Форматы полей

```text
birth_date       YYYY-MM-DD
issue_date       YYYY-MM-DD
department_code  000-000
document_number  0000 000000
sex              МУЖ / ЖЕН / М / Ж
```

## Поведение сервиса после обработки

При успешной обработке:

```text
1. result JSON записывается в out/
2. исходный JPG удаляется из in/
3. command JSON удаляется из processing/
4. input.jpg + command.json + result.json архивируются
```

При ошибке:

```text
1. result JSON с validation.status=error может быть записан в out/
2. command JSON переносится в error/
3. входное изображение сохраняется для диагностики
```

## Retention

```text
out/*.json удаляются сервисом после 7 дней
archive хранится 30 дней, общий лимит 5 ГБ
```

1С может удалять result JSON после успешного чтения.

## PowerShell 2.0-compatible SMB test

Эталонный тестовый скрипт хранится в репозитории:

```text
tools/test_ocr_smb_ps2.ps1
```

Рабочую копию можно положить на сервер 1С:

```text
C:\Users\vrs\test_ocr_smb_ps2.ps1
```

Запуск:

```powershell
powershell -ExecutionPolicy Bypass -File .\test_ocr_smb_ps2.ps1
```
