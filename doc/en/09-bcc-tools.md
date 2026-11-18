# External BCC tools

TOOLS embeds 67 external tracer names and five system commands in `linuxperf.py`. Names span Python/BCC, libbpf-tools and bpftrace; package availability and interface compatibility are not guaranteed. Runtime collection does not read this documentation. Trusted paths are checked for ownership and permissions; argv executes without a shell and with a restricted environment.

Two collectors run by default. Oomkill is prioritized, followed by system commands and the remaining queue. Focus filters external categories while retaining system commands. Continuous tracers receive timed SIGINT and, if needed, SIGTERM/SIGKILL. Queued work does not extend the global deadline.

Limits include 8 MiB per command, an additional 12 MiB budget distributed across the selected set, and 1000 events. Budget exhaustion can refer to time or output; inspect data/truncated and timestamps. Result-limit indicates truncation. An installed executable may still be incompatible with the kernel.

Biosnoop -d selects a disk. Slower tools receive a 1 ms threshold without an extra duration. Wakeuptime uses -f; stackcount uses -D with sched_switch. The catalog below reflects current argument templates.

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

Implementation: [linuxperf.py](../../linuxperf.py) — `trusted_tool`, `command`, `run_tools`, `parse_tool`, `tool_duration`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/09-bcc-tools.md)

See the [README](../../README.md#недостающие-утилиты-в-ред-ос-73--8) for the eight commonly missing names, functional alternatives and the current biostacks integration limitation.
