# JSON contract

## Command JSON v1

Минимальный production-запрос:

```json
{
  "request_id": "REQ001",
  "image_file": "REQ001.jpg"
}
```

Поля:

```text
request_id  string, required
image_file  string, required
```

## Command JSON v2 draft

Для будущей поддержки разных типов документов:

```json
{
  "request_id": "REQ001",
  "image_file": "REQ001.jpg",
  "document_type": "rf_internal"
}
```

`document_type` должен быть необязательным для обратной совместимости.

Если поле отсутствует:

```text
document_type = rf_internal
```

Планируемые значения:

```text
rf_internal        внутренний паспорт РФ
tj_foreign         загранпаспорт Таджикистана
uz_foreign         загранпаспорт Узбекистана
kg_foreign         загранпаспорт Кыргызстана
unknown            автоопределение/не задано, если будет реализовано позже
```

## Result JSON: успешный пример

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
  },
  "timing": {
    "crop_sec": 0.293,
    "ocr_sec": 1.722,
    "parse_sec": 0.002,
    "save_result_sec": 0.0,
    "total_sec": 2.017
  }
}
```

## Required fields for RF internal passport

```text
last_name
first_name
birth_date
sex
birth_place
issue_date
department_code
issued_by
```

`middle_name` и `document_number` полезны, но могут быть обработаны как отдельные validation rules.

## validation.status

```text
ok       автоматическая обработка допустима
warning  результат получен, но есть предупреждения
error    результат непригоден без ручной проверки
```

## Error issue object

```json
{
  "field": "birth_place",
  "code": "missing_required_field",
  "message": "Required field is missing",
  "value": null
}
```

## Date format

Все даты в result JSON:

```text
YYYY-MM-DD
```

## Department code format

```text
000-000
```

## Document number format for RF internal passport

```text
0000 000000
```

## Encoding

Command JSON:

```text
UTF-8 without BOM preferred
UTF-8 with BOM accepted
```

Result JSON:

```text
UTF-8
```
