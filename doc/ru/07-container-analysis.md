# PID и cgroup

`--cgroup` выбирает существующий путь cgroup с учётом mount root и membership. Поддерживаются v1/v2: quota, cpuset, память, memory events, CPU throttling и доступные I/O-показатели. Совместные PID и cgroup должны соответствовать друг другу.

CPU count хоста не равен разрешённой quota контейнера. Основное правило `cpu_throttling` использует накопленное число throttled periods; `throttled_periods_per_sec`, `throttled_period_pct` и `throttled_seconds_per_sec` сохраняются отдельно в данных cgroup. Не представляйте накопленный счётчик как текущую долю задержек. `container_cpu_utilization` в текущем коде выводится из throttled time/quota, его нельзя считать обычным процентом выполненной CPU-работы.

Фильтр cgroup ограничивает процессные данные, но не все внешние трассировки. Ограничения сохраняются в `filter_limitation`. Native tcpretrans не фильтруется по cgroup. Статистика сетевого namespace и часть procfs могут описывать хост; проверяйте scope каждого результата.

```bash
python3 linuxperf.py collect --cgroup /sys/fs/cgroup/example.service --profile quick -o cgroup.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `resolve_cgroup`, `cgroup_sources`, `cgroup_snapshot`, `enrich`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/07-container-analysis.md)
