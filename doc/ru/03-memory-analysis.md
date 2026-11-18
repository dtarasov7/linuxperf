# Анализ памяти

`memory_info` содержит meminfo, vmstat, NUMA и THP; дополнительные показатели формируются из PSI, buddyinfo, socket memory и sysctl. Основной показатель использования памяти опирается на MemAvailable, а не только MemFree.

`swap_usage` — занятая доля swap, не скорость обмена. Для давления памяти нужны согласованные признаки: PSI, direct reclaim, major faults и поведение приложения. Счётчики vmstat могут быть накопленными; различайте исходные значения и скорости в `metrics`.

Утечку нельзя доказать одним RSS-снимком. Сравнивайте несколько одинаковых окон и top процессов. Memleak в deep — дорогая системная трассировка; без PID он может наблюдать kernel allocations. Его позиционный аргумент задаёт интервал отчёта, завершение ограничено таймером linuxperf.

```bash
python3 linuxperf.py collect --focus memory --external-tools off --native-ebpf off -o memory.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `collect`, `restore_metrics`, `parse_sockstat`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/03-memory-analysis.md)
