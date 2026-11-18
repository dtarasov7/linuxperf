# Анализ процессов

`process_info.data` содержит `top_by_cpu`, `top_by_memory`, `top_by_io`. Доступны PID, comm, CPU%, RSS, memory%, скорости I/O, threads и fd_count в пределах доступных источников. `--top` задаёт число строк, по умолчанию 20.

CPU и I/O сопоставляются между снимками с проверкой starttime, чтобы повторное использование PID не давало ложные дельты. Процесс может завершиться в момент чтения; недоступные данные не считаются нулевой активностью. Hidepid и права уменьшают полноту.

ObserverTracker исключает известные PID самого сборщика и его потомков из доступных процессных и событийных данных. Это не устраняет накладные расходы из общесистемных счётчиков и стеков. Не путайте имена BCC-процессов с рабочим приложением.

```bash
python3 linuxperf.py collect --pid 12345 --top 10 --profile standard -o process.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `proc_stat`, `snapshot`, `enrich`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/06-process-analysis.md)
