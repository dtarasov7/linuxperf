# Внешние BCC-инструменты

Реестр TOOLS содержит 67 имён внешних трассировщиков и пять системных команд. Имена относятся к разным семействам, включая BCC/libbpf-tools и bpftrace; наличие каждого инструмента в bcc-tools и совместимость интерфейса не гарантированы. Имена и аргументы встроены в `linuxperf.py`; установленная программа не читает этот каталог документации. Доверенные пути проверяются по владельцу и правам, запускается argv без shell, окружение ограничено.

По умолчанию два сборщика; oomkill имеет приоритет, затем идут системные команды и остальная очередь. Фильтр focus ограничивает выбранные внешние категории, системные команды сохраняются. Непрерывные трассировщики останавливаются SIGINT по таймеру, затем при необходимости SIGTERM/SIGKILL. Общий дедлайн не продлевается для очереди.

Лимиты: максимум 8 MiB вывода одной команды, дополнительный бюджет 12 MiB, распределённый на выбранный набор, и max-events 1000. `budget_exhausted` может означать время или вывод; читайте data/truncated и timestamps. `result_limit` означает усечение результата. Наличие файла утилиты не доказывает совместимость с ядром.

Для biosnoop -d — диск; *slower получают порог 1 ms без лишней длительности; wakeuptime — -f; stackcount получает -D и tracepoint sched_switch. Полный каталог ниже отражает текущие argv-шаблоны.

```bash
python3 linuxperf.py install --dry-run
python3 linuxperf.py collect --profile deep --max-workers 2 --max-events 1000 -o deep.json
```

| Tool | Category | Argument template |
|---|---|---|
| `runqlat` | cpu | `-m {duration} 1` |
| `runqlen` | cpu | `{duration} 1` |
| `cpudist` | cpu | `{duration} 1` |
| `biolatency` | disk | `-D {duration} 1` |
| `biosnoop` | disk | — |
| `ext4slower` | disk | `1` |
| `fileslower` | disk | `1` |
| `bitesize` | disk | `{duration} 1` |
| `tcpconnlat` | network | — |
| `tcpretrans` | network | — |
| `tcprtt` | network | `-d {duration}` |
| `gethostlatency` | network | — |
| `tcpdrop` | network | — |
| `tcpstates` | network | — |
| `profile` | stacktrace | `-af {duration}` |
| `offcputime` | stacktrace | `-fK {duration}` |
| `cachestat` | memory | `{duration} 1` |
| `execsnoop` | process | — |
| `hardirqs` | cpu | `{duration} 1` |
| `softirqs` | cpu | `{duration} 1` |
| `opensnoop` | process | `-d {duration}` |
| `killsnoop` | process | — |
| `threadsnoop` | process | — |
| `syncsnoop` | process | — |
| `exitsnoop` | process | — |
| `statsnoop` | process | — |
| `capable` | process | — |
| `filelife` | disk | — |
| `mountsnoop` | disk | — |
| `btrfsslower` | disk | `1` |
| `xfsslower` | disk | `1` |
| `nfsslower` | disk | `1` |
| `zfsslower` | disk | `1` |
| `mdflush` | disk | — |
| `runqslower` | cpu | `10000` |
| `cpufreq` | cpu | — |
| `cpuunclaimed` | cpu | `{duration} 1` |
| `tcpconnect` | network | — |
| `tcpaccept` | network | — |
| `tcplife` | network | — |
| `udpconnect` | network | — |
| `sofdsnoop` | network | — |
| `sockstat` | network | — |
| `skbdrop` | network | — |
| `oomkill` | memory | — |
| `shmsnoop` | memory | — |
| `drsnoop` | memory | — |
| `numamove` | memory | — |
| `llcstat` | cpu | `{duration}` |
| `ext4dist` | disk | `{duration} 1` |
| `btrfsdist` | disk | `{duration} 1` |
| `xfsdist` | disk | `{duration} 1` |
| `nfsdist` | disk | `{duration} 1` |
| `zfsdist` | disk | `{duration} 1` |
| `tcpsynbl` | network | — |
| `scsilatency` | disk | `{duration} 1` |
| `nvmelatency` | disk | `{duration} 1` |
| `wakeuptime` | stacktrace | `-f {duration}` |
| `offwaketime` | stacktrace | `-fK {duration}` |
| `biostacks` | stacktrace | `-f {duration}` |
| `stackcount` | stacktrace | `-f -K -D {duration} t:sched:sched_switch` |
| `biotop` | disk | `{duration} 1` |
| `slabratetop` | memory | `{duration} 1` |
| `vfsstat` | disk | `{duration} 1` |
| `syscount` | process | `-d {duration}` |
| `funccount` | cpu | `-d {duration} tcp_*` |
| `memleak` | memory | `-a {duration}` |
| `ss` | network | `-ltn` |
| `ethtool` | network | `--version` |
| `nvidia-smi` | system | `--query-gpu=name,pci.bus_id,utilization.gpu,memory.used,memory.total,driver_version,utilization.memory,temperature.gpu,power.draw,index --format=csv,noheader,nounits` |
| `dmesg` | system | `--level=err,warn --nopager` |
| `df` | system | `-P -T` |

Реализация: [linuxperf.py](../../linuxperf.py) — `trusted_tool`, `command`, `run_tools`, `parse_tool`, `tool_duration`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/09-bcc-tools.md)

Назначение восьми часто отсутствующих имён, функциональные аналоги и ограничение текущего biostacks описаны в [README](../../README.md#недостающие-утилиты-в-ред-ос-73--8).
