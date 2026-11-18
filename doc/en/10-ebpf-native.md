# Native eBPF tcpretrans

The native backend uses ctypes, mmap and BPF/perf_event_open syscalls on little-endian x86_64. It implements tcpretrans rather than replacing the full BCC catalog. This path needs neither the Python BCC package nor a compiler.

It first tries tcp/tcp_retransmit_skb with tracepoint format discovery. The fallback uses BTF, a PMU kprobe and sock_common fields. Finding BTF does not guarantee permission to load the program. Appropriate privileges, ring-buffer support and attachment points are required.

Native failure can fall back to the external tool when enabled; native_attempt retains the failure. Event PID describes current execution context, not necessarily socket ownership. There is no cgroup filter and ring-buffer losses remain unknown (`lost_events=null`). Support on every kernel is not claimed.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf auto --focus network -o native.json
```

Implementation: [linuxperf.py](../../linuxperf.py) — `native_capability`, `native_tcpretrans`, `retrans_program`.

[Contents](00-chapters.md) · [README](../../README.md) · [Русский](../ru/10-ebpf-native.md)
