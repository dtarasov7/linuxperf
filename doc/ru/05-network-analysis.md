# Анализ сети

Сетевой сбор сочетает procfs TCP/UDP, счётчики интерфейсов, conntrack, softnet, socket memory/orphans, sysctl и listen backlog через SOCK_DIAG. Ettool добавляет свойства и driver counters там, где драйвер поддерживает запросы. Неподдерживаемые запросы виртуального интерфейса не означают неисправность сети.

PID-фильтр не превращает `/proc/PID/net` в статистику только этого процесса: это область сетевого namespace. Встроенный tcpretrans системный, cgroup-фильтр к нему не применяется. Для событий проверяйте адреса, порты, единицы и источник PID.

TIME_WAIT часто нормален. CLOSE_WAIT, retransmits, drops и zero-window требуют контекста очередей и приложения. Значение сетевого USE saturation — число TIME_WAIT+CLOSE_WAIT, не процент. Два DNS-события не дают устойчивого p99 и не доказывают каскад таймаутов.

```bash
python3 linuxperf.py collect --profile standard --focus network -o network.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `listen_queues`, `parse_sockstat`, `parse_ethtool`, `enrich`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/05-network-analysis.md)
