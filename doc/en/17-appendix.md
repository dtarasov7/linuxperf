# CLI and verification reference

Deployment requires one file. Source, collect, run_tools, parse_tool, diagnose, build_ai_context, diff_reports and export live in linuxperf.py. Tests and fixtures are not runtime dependencies. The root README covers installation including RED OS package lookup.

The collect help below comes from current argparse. Durations support s, m and ms; interval must be smaller than duration. Focus accepts cpu,memory,disk,network,process,container,system,stacks/stacktrace. MCP exposes only a subset of CLI options.

Python checks run without root or actual BPF loading. Passing tests does not establish BCC compatibility with every kernel. Distinguish live trace validation from parser tests.

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

Implementation: [linuxperf.py](../../linuxperf.py) — `parser`, `prepare`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/17-appendix.md)
