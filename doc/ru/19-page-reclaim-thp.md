# Reclaim, compaction и THP

Сбор использует vmstat, PSI, buddyinfo, sysctl и параметры transparent_hugepage в sysfs. Метрики direct_reclaim_rate, compaction_stall_rate, thp_split_rate вычисляются из дельт счётчиков при доступности обоих снимков. Исходные pgscan/pgsteal могут оставаться историческими.

Ненулевой direct reclaim указывает на работу reclamation в контексте выделения памяти, но для оценки задержек нужны PSI и поведение приложения. Compaction и THP split не тождественны исчерпанию RAM. Режим THP в sysfs показывает политику; он не доказывает наличие задержки сам по себе.

Сначала соберите чистую базу, затем сопоставьте окна memory PSI, reclaim и I/O. Универсального значения swappiness, watermark или THP для всех нагрузок нет. Linuxperf формирует рекомендации текстом, а не применяет sysctl или systemd units.

```bash
python3 linuxperf.py collect --focus memory --external-tools off --native-ebpf off --duration 30s -o reclaim.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `collect`, `restore_metrics`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/19-page-reclaim-thp.md)
