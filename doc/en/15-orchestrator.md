# Collection scheduling

Collect takes a clean baseline interval, starts external/native collectors and continues periodic snapshots. System/GPU inventory is enriched during assembly. Sampling and the tool queue have distinct roles; two phases do not remove observer effects during tracing.

Max-workers defaults to two. Oomkill takes the first slot when selected by focus. Remaining work shares the other slots and a global deadline: baseline interval plus duration plus up to five seconds of grace. Cleanup may add time. Queued tools are not guaranteed a full window.

Longer duration also lengthens early traces, so it does not by itself fix the deep queue. Max-tool-seconds caps commands but shortened results may remain partial. More workers increase simultaneous BCC compilation and VM interference. There is currently no batch scheduler guaranteeing each tool its own full window.

SIGINT/SIGTERM preserves available partial data; a second signal exits immediately. Self-profile/pprof writes cProfile/pstats, not an HTTP profile.

```bash
python3 linuxperf.py collect --profile deep --max-workers 2 --self-profile linuxperf.pstats -o deep.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `collect`, `run_tools`, `tool_duration`, `handle_signal`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/15-orchestrator.md)
