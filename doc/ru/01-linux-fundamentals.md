# Источники и окна измерений Linux

`/proc/stat` содержит счётчики CPU, `/proc/meminfo` — память, `/proc/vmstat` — события VM, `/proc/diskstats` — I/O, `/proc/net/dev` и SNMP — сеть. Sysfs даёт свойства устройств, NUMA и PCI. Cgroup v1/v2 дополняет общесистемные данные лимитами и статистикой выбранной группы.

Скорость вычисляется как разность счётчика, делённая на фактическое время между снимками. Убывание счётчика, смена boot identity или процесса не должны превращаться в положительную скорость. Единицы CPU ticks и размер страниц определяются через sysconf; не предполагайте фиксированный размер страницы.

PSI — доля времени задержек, load включает не только готовые к выполнению задачи. Занятый swap и исторический NUMA miss ratio не доказывают текущие задержки. Для единиц, метода и области видимости используйте `metric_specs`; данные внутри контейнера могут относиться к хосту.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off --duration 10s -o baseline.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `snapshot`, `delta`, `pairs`, `metric_spec`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/01-linux-fundamentals.md)
