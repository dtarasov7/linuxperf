# Рекомендации и проверка изменений

Движок содержит 35 условий рекомендаций по измерениям, sysctl и свойствам устройств. Результат включает priority, type, evidence, commands, persistent, expected_impact и source. Не все рекомендации возникают в каждом отчёте.

Команды — текст для проверки оператором. Collect их не выполняет. Даже рекомендация типа fix не доказывает причину задержек. Изменения swappiness, THP, TCP buffers, backlog и I/O scheduler должны учитывать нагрузку, лимиты памяти и возможность отката.

Сохраните исходное значение, изменяйте один фактор, повторите сопоставимый сбор, сравните coverage и измерения через diff. Persistent-настройки применяйте после проверки. Примеры из вывода не являются универсальным скриптом настройки всех серверов.

```bash
python3 linuxperf.py diff before.json after.json -o changes.json
```

Реализация: [linuxperf.py](../../linuxperf.py) — `generate_recommendations`.

[Оглавление](00-chapters.md) · [README](../../README.md) · [English](../en/12-recommendations.md)
