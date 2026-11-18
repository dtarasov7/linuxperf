# Анализ дисков

Diskstats даёт IOPS, bytes/s, среднюю задержку, очередь и busy time по устройствам. Сектора `/proc/diskstats` переводятся в байты с множителем 512; это не предположение о физическом размере сектора. Sysfs добавляет rotational, scheduler, read-ahead и признак раздела.

Средняя задержка не определяет p99. Для biolatency нужны реальные непустые buckets, известные единицы и для SSD/HDD-правил — известный тип устройства. Не суммируйте разделы, device mapper и физические устройства как независимые I/O. Busy time NVMe не равен проценту исчерпания всей параллельной пропускной способности.

`unsupported_probe` у biolatency/biosnoop означает недоступную точку подключения ядра, а не высокую задержку диска. Headers сами по себе это не исправляют. `deep --focus disk` использует общий дедлайн: очереди могут сократить окна инструментов.

```bash
python3 linuxperf.py collect --profile deep --focus disk --max-workers 2 -o disk.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `collect`, `enrich`, `external_metrics`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/04-disk-analysis.md)
