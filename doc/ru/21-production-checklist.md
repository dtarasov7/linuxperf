# Проверка на рабочем сервере

Перед сбором определите наблюдаемую проблему, время проявления, PID/cgroup и доступный бюджет нагрузки. Начните с external-tools off и native-ebpf off. Проверьте coverage и permissions; при необходимости включайте конкретную категорию трассировки.

Используйте одинаковые профиль, окно, scope и workload для сравнения. Контролируйте CPU и память самой диагностики. В deep два workers не дают полного окна каждому инструменту; 32 workers на двух vCPU могут вызвать конкуренцию компиляторов. Увеличение параллелизма не является исправлением ошибок BCC или неизвестного формата.

Сохраните отчёт до изменения. Выберите одну подтверждённую гипотезу, план проверки, исходное значение и откат. После изменения повторите сбор и diff, проверьте также задержки и ошибки приложения. Выполнять весь набор рекомендаций одним скриптом не следует: программа не генерирует доказательство применимости каждой настройки к серверу.

Report может содержать hostname, PID, пути и адреса. Перед явной публикацией проверьте содержимое. Сбор сам ничего не отправляет.

```bash
python3 linuxperf.py collect --external-tools off --native-ebpf off -o before.json
python3 linuxperf.py collect --external-tools off --native-ebpf off -o after.json
python3 linuxperf.py diff before.json after.json -o comparison.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `collect`, `diff_reports`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/21-production-checklist.md)
