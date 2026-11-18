# Справочник CLI и проверки

Программа поставляется одним файлом. Source, collect, run_tools, parse_tool, diagnose, build_ai_context, diff_reports и export — функции/класс в linuxperf.py. Каталог tests содержит unittest и фикстуры; runtime не читает их. Корневой README описывает установку, в том числе проверку пакетов в РЕД ОС.

Ниже приведена справка collect из текущего argparse. Длительности принимают s, m, ms; interval должен быть меньше duration. Focus: cpu,memory,disk,network,process,container,system,stacks/stacktrace. Не все ключи CLI доступны через MCP.

Проверки Python можно выполнить без root и без реальной загрузки BPF. Успех тестов не доказывает совместимость BCC с каждым ядром; результаты реальных запусков отделяйте от проверок парсеров.

```bash
python3 linuxperf.py collect --help
python3 -m py_compile linuxperf.py
python3 -m unittest discover -s tests -v
```

```text
usage: linuxperf.py collect [-h] [--profile {quick,standard,deep}]
                               [--duration DURATION] [--interval INTERVAL]
                               [--external-tools {auto,off}] [--focus FOCUS]
                               [--pid PID] [--cgroup CGROUP] [--top TOP]
                               [--max-events MAX_EVENTS]
                               [--proc-root PROC_ROOT] [--sys-root SYS_ROOT]
                               [--etc-root ETC_ROOT]
                               [--max-workers MAX_WORKERS]
                               [--max-tool-seconds MAX_TOOL_SECONDS]
                               [--max-tool-output MAX_TOOL_OUTPUT]
                               [--native-ebpf {auto,off}]
                               [--self-profile SELF_PROFILE] [--ai-prompt]
                               [--compact] [-q] [-v] [-o OUTPUT]

optional arguments:
  -h, --help            show this help message and exit
  --profile {quick,standard,deep}
  --duration DURATION
  --interval INTERVAL
  --external-tools {auto,off}
  --focus FOCUS
  --pid PID
  --cgroup CGROUP
  --top TOP
  --max-events MAX_EVENTS
  --proc-root PROC_ROOT
  --sys-root SYS_ROOT
  --etc-root ETC_ROOT
  --max-workers MAX_WORKERS
                        Maximum concurrent external collectors (default: 2)
  --max-tool-seconds MAX_TOOL_SECONDS
  --max-tool-output MAX_TOOL_OUTPUT
  --native-ebpf {auto,off}
  --self-profile SELF_PROFILE, --pprof SELF_PROFILE
                        Write cProfile statistics for this run
  --ai-prompt           Write a separate .prompt.txt file and compact JSON;
                        stdout reports use report.prompt.txt in the current
                        directory
  --compact             Write JSON without indentation; preserve all report
                        data
  -q, --quiet           Suppress progress and terminal summary
  -v, --verbose
  -o OUTPUT, --output OUTPUT
```

Реализация: [linuxperf.py](../../linuxperf.py) — `parser`, `prepare`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/17-appendix.md)
