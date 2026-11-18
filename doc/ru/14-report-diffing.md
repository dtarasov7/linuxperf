# Сравнение отчётов

Diff принимает два отчёта схемы linuxperf/1.0. Сравниваются общие метрики, USE, отдельные устройства/интерфейсы и доступные процентили. Изменения содержат comparable, reason, delta и percent_change.

Отсутствующее значение не равно нулю. Различие единиц, метода, хоста или scope может запретить сравнение. Изменение boot identity, профиля и версии score отражается явно. Процент изменения при нулевом исходном значении не вычисляется.

`anomalies_resolved` не включает правило, которое просто перестало проверяться: такие случаи находятся в anomalies_unverified. Проверяйте coverage_before/after вместе с regressions и improvements. Уменьшение числа аномалий из-за утраты инструментов не является улучшением производительности.

```bash
python3 linuxperf.py diff before.json after.json -o diff.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `load_report`, `diff_reports`, `compare_inventory`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/14-report-diffing.md)
