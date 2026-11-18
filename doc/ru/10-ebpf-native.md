# Встроенный eBPF tcpretrans

Встроенный backend реализован на ctypes, mmap и системных вызовах BPF/perf_event_open для little-endian x86_64. Это реализация tcpretrans, а не универсальная замена всем BCC-утилитам. Python-пакет BCC и компилятор для этого пути не нужны.

Сначала используется tracepoint tcp/tcp_retransmit_skb с чтением его format; резервный путь использует BTF, PMU kprobe и поля sock_common. Возможность обнаружить BTF не означает, что ядро разрешит загрузить программу. Требуются подходящие права, ring buffer и поддерживаемые точки подключения.

При отказе native выполняется внешний fallback, если внешние команды включены. Причина остаётся в native_attempt. Поле PID — текущий контекст события, не гарантированно владелец сокета. Cgroup-фильтра нет, потери ring buffer пока неизвестны (`lost_events=null`). Успех на всех ядрах не заявляется.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf auto --focus network -o native.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `native_capability`, `native_tcpretrans`, `retrans_program`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/10-ebpf-native.md)
