# Интерпретация NUMA

В memory_info доступны NUMA node memory и numastat; дополнительно собираются distance, cpulist и доступные настройки balancing/reclaim. PCI topology позволяет сопоставить GPU/NIC с NUMA node. Источники находятся в sysfs и зависят от оборудования.

`numa_miss_ratio` — отношение исторических счётчиков выделения памяти. Это не измерение удалённых обращений CPU и не текущая задержка доступа. Высокий накопленный ratio требует проверки размещения нагрузки, а низкий не гарантирует оптимальную CPU/memory affinity.

Отсутствие нескольких NUMA nodes не должно становиться гипотезой о межсокетной проблеме. Изменение pinning, interleave, zone_reclaim_mode или balancing может ухудшить другую нагрузку. Сначала определите реальную CPU/memory привязку и сравните повторяемый workload до и после одного изменения. Автоматической оптимизации NUMA нет.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off --focus memory -o numa.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `restore_metrics`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/20-numa-optimization.md)
