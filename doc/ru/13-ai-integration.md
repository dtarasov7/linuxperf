# Промпт и MCP

`--ai-prompt -o report.json` записывает `report.prompt.txt` рядом с автоматически компактным JSON. Из сохранённого JSON удаляется ai_context, чтобы не дублировать инструкцию. Вставьте текст промпта в чат и прикрепите полный JSON. При stdout-отчёте промпт называется report.prompt.txt в текущей директории. Генерация локальная, без вызова модели и отправки данных.

Промпт содержит статусы и причины неполноты, окна измерений, CPU-время программы и дочерних процессов. Peak RSS относится к самой программе. Подсказки по стекам/гистограммам требуют успешных непустых результатов. 27 гипотез сохранены как необязательный справочник: не перебирать всё, не объявлять совпадение доказанной причиной. Ответ ограничен 500 словами и тремя вероятными проблемами с evidence, confidence и проверками.

MCP запускается через stdio JSON-RPC (протокол 2024-11-05). Инструменты: get_health, collect_metrics, list_anomalies, explain_anomaly. Допускается один активный сбор в worker-процессе; поддержаны отмена и ping во время работы. Аргументы collect_metrics ограничены profile/pid/focus, это не полный CLI. Настройка клиента: command=python3, args=[абсолютный путь к linuxperf.py, mcp].

```bash
python3 linuxperf.py collect --profile standard --ai-prompt -o report.json
python3 linuxperf.py mcp
```

Реализация: [linuxperf.py](../../linuxperf.py) — `build_ai_context`, `mcp`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/13-ai-integration.md)
