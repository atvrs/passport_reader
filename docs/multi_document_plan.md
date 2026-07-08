# Multi-document plan

## Цель

После стабилизации паспорта РФ добавить распознавание загранпаспортов:

```text
Таджикистан
Узбекистан
Кыргызстан
возможно другие страны
```

Текущий RF parser не нужно превращать в один огромный универсальный файл. Лучше перейти к модульной архитектуре.

## Принцип обратной совместимости

Старый command JSON должен работать без изменений:

```json
{
  "request_id": "REQ001",
  "image_file": "REQ001.jpg"
}
```

Если `document_type` отсутствует:

```text
document_type = rf_internal
```

Новый вариант:

```json
{
  "request_id": "REQ001",
  "image_file": "REQ001.jpg",
  "document_type": "rf_internal"
}
```

## Предлагаемые document_type

```text
rf_internal  внутренний паспорт РФ
tj_foreign   загранпаспорт Таджикистана
uz_foreign   загранпаспорт Узбекистана
kg_foreign   загранпаспорт Кыргызстана
```

## Предлагаемая структура

```text
src/parsers/
  __init__.py
  common.py
  rf_internal.py
  foreign_passport_mrz.py
  tj_foreign.py
  uz_foreign.py
  kg_foreign.py
```

Где:

```text
common.py                общие OCR item, bbox, line grouping, normalization helpers
rf_internal.py           текущая RF layout-логика
foreign_passport_mrz.py  общая MRZ-логика для загранпаспортов
*_foreign.py             country-specific postprocessing/validation
```

## Почему MRZ важен

Для загранпаспортов основным стабильным источником обычно является MRZ-зона.

MRZ может дать:

```text
фамилию
имя
номер документа
гражданство
дату рождения
пол
дату окончания срока действия
контрольные суммы
```

Визуальная зона нужна для:

```text
дополнительных полей
проверки
случаев плохой MRZ
локальных написаний
```

## План внедрения

### Шаг 1. Заморозить RF baseline

Перед рефакторингом должны проходить:

```bash
python3 tools/test_parser_birth_place.py
./tools/test_local_service.sh
```

И SMB-тест с 1С-сервера.

### Шаг 2. Ввести document_type без изменения поведения

Добавить чтение `document_type` в service/process layer.

Пока:

```text
missing document_type -> rf_internal
rf_internal -> старый parser
```

### Шаг 3. Вынести RF parser в модуль

Текущий `parse_passport.py` можно оставить как совместимый CLI-wrapper, но внутреннюю логику перенести постепенно.

Цель:

```text
parse_passport.py -> вызывает parsers.rf_internal
```

### Шаг 4. Добавить MRZ parser

Сначала без country-specific правил:

```text
foreign_passport_mrz.py
```

На вход — OCR items/lines, на выход — базовые поля MRZ + validation.

### Шаг 5. Добавить страновые модули

```text
tj_foreign.py
uz_foreign.py
kg_foreign.py
```

Каждый модуль:

```text
1. использует MRZ parser;
2. добавляет country-specific normalization;
3. добавляет validation;
4. формирует единый result JSON.
```

## Что собрать для каждой новой страны

Для каждой страны нужно минимум:

```text
5-10 фото разного качества
raw OCR JSON
ожидаемые поля
пример корректного result JSON
понимание нужных 1С полей
наличие/качество MRZ
```

Не хранить реальные образцы в публичном git.

## Риски

```text
1. разные алфавиты и транслитерация;
2. OCR может смешивать латиницу/кириллицу;
3. MRZ может быть повреждена бликами;
4. разные поколения паспортов внутри одной страны;
5. фото может быть не разворотом, а одной страницей.
```

## Рекомендация

Не начинать multi-document refactor до того, как RF production baseline покрыт локальными тестами и runbook-документацией.
