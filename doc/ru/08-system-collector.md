# Система и файловые системы

`system_info` содержит сведения ОС и ядра, uptime, boot parameters, блочные устройства и локальные файловые системы. Данные sysfs зависят от namespace, прав и наличия оборудования. Dmesg — отдельная внешняя команда; её запрет не блокирует базовые сведения системы.

Statvfs локальных mount points выполняется в ограниченных worker-процессах с таймаутом. Сетевые/autofs mount points не опрашиваются этим путём. `--external-tools off` не отключает эти встроенные процессы: это не сторонние диагностические команды.

`system_info` и `gpu_pcie` завершаются при сборке отчёта, а не обязательно в чистом базовом интервале. Смотрите start/end timestamps. Ошибки чтения источников и неполный доступ отражаются в отчёте; наличие ключа не гарантирует измерение.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off -o system.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `filesystems`, `filesystem_worker`, `restore_metrics`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/08-system-collector.md)
