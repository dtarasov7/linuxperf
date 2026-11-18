# Быстрый старт

Запускайте команды из корня проекта на Linux с Python 3.8+. Первый сбор ниже отключает внешние утилиты и встроенный eBPF. Для базовой диагностики root не обязателен, но права могут ограничить доступ к процессам и источникам.

`quick` выбирает четыре трассировщика и окно 10 s; `standard` — другой ограниченный набор и 30 s; `deep` — весь каталог и 60 s. По умолчанию внешние команды и native eBPF включены, максимум два внешних/native сборщика работают через очередь. Большое число workers может загрузить CPU компиляторами BCC.

JSON записывается в файл или stdout, progress — в stderr. `-q` убирает progress. Проверьте `metadata.status`, `summary.coverage`, `source_errors` и статусы категорий. `partial` не означает, что все измерения непригодны.

С `--ai-prompt` создаются компактный JSON и отдельный `.prompt.txt`. Вставьте промпт в чат и прикрепите JSON. Затем можно экспортировать HTML или сравнить два отчёта.

```bash
python3 linuxperf.py collect --profile quick --external-tools off --native-ebpf off -o baseline.json
python3 linuxperf.py collect --profile standard --ai-prompt -o report.json
python3 linuxperf.py export report.json --format html -o report.html
python3 linuxperf.py diff baseline.json report.json -o diff.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `parser`, `prepare`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/00-quickstart.md)
