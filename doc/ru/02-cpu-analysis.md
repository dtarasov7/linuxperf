# Анализ CPU

`cpu_utilization` использует дельты `/proc/stat`; дополнительно доступны per-core состояния, steal, iowait, IRQ, context switches, load и PSI. CPU приложения и CPU хоста имеют разные знаменатели: процесс может использовать более 100% на нескольких ядрах.

При включённой трассировке основные CPU-метрики опираются на чистый базовый интервал до запуска BCC. Поздние снимки находятся в `time_series` с `observer_active=true`. Низкий базовый CPU не противоречит полной загрузке во время компиляции BPF. Смотрите `baseline_window_seconds`, `observed_window_seconds`, `sample_count` и `observer_overhead`.

Runqlat измеряет ожидание планировщика; cpudist — длительности CPU-выполнения. Неполные гистограммы и отсутствие единицы требуют осторожности. Не выводите однопоточную проблему только из load или одного высокого p99. Сравнивайте с независимым базовым сбором.

```bash
python3 linuxperf.py collect --profile standard --focus cpu --max-workers 2 -o cpu.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `snapshot`, `collect`, `sample_summary`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/02-cpu-analysis.md)
