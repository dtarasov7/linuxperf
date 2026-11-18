# Форматы и экспорт

Схема отчёта — linuxperf/1.0. Каждая категория содержит результаты с collector, backend, status, reason, data и scope; дополнительные поля зависят от источника. Доступны статусы ok, partial, unavailable, skipped, error. Отчёт ограничен 32 MiB; запись файла использует временный файл и rename. JSON запрещает NaN/Infinity.

Compact удаляет отступы и пробелы, сохраняя измерения. AI-prompt автоматически включает compact и выносит инструкцию в отдельный файл. Progress/summary идут в stderr; stdout остаётся JSON при -o -. Quiet отключает progress, а не ошибки.

HTML — автономная страница с экранированным JSON внутри pre, а не графический dashboard с карточками и графиками. Folded/SVG требуют реальных положительных stack samples; при смешении samples/us/allocations выбирайте один collector. Ширина flamegraph отражает вес, а не обязательно CPU-время.

```bash
python3 linuxperf.py export report.json --format html -o report.html
python3 linuxperf.py export report.json --format folded --collector profile -o cpu.folded
python3 linuxperf.py export report.json --format flamegraph --collector profile -o cpu.svg
```

Реализация: [linuxperf.py](../../linuxperf.py) — `write_json`, `write_text`, `export`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/16-output-formats.md)
