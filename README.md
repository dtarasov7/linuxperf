# linuxperf

Версия 1.1.2. Самостоятельная однофайловая диагностика Linux на Python 3.8+, только стандартная библиотека. Для эксплуатации достаточно скопировать `linuxperf.py`. Отчёты имеют собственную схему `linuxperf/1.0`.

```bash
# Показывает доступность файловых источников, внешних утилит и предпосылок native eBPF.
# Не запускает полноценный сбор и не гарантирует успешную загрузку BPF.
python3.8 linuxperf.py capabilities

# Быстрый сбор с окном 10 секунд: базовые метрики и выбранные трассировщики.
# Записывает report.json; недоступные источники отражаются в статусах и coverage.
python3.8 linuxperf.py collect --profile quick -o report.json

# Сбор с окном 10 секунд без внешних диагностических команд.
# Встроенный tcpretrans остаётся включён: для отключения добавьте --native-ebpf off.
python3.8 linuxperf.py collect --external-tools off --duration 10s -o report.json

# Сбор standard с окном 30 секунд для процесса PID 123, результат — process.json.
# PID ограничивает процессные данные и поддерживающие фильтр трассировки;
# общесистемные метрики CPU, памяти и дисков не становятся метриками одного PID.
python3.8 linuxperf.py collect --pid 123 --profile standard -o process.json

# Быстрый сбор для существующей cgroup: её лимиты, счётчики и входящие процессы.
# Результат — cgroup.json; не все внешние/native трассировки ограничиваются cgroup.
python3.8 linuxperf.py collect --cgroup /sys/fs/cgroup/example --profile quick -o cgroup.json

# Выбирает дисковые инструменты из deep с общим окном 60 секунд и системные команды.
# Сохраняет компактный disk.json и отдельный disk.prompt.txt для модели.
# Базовые категории сохраняются; очередь может сократить окна отдельных инструментов.
python3.8 linuxperf.py collect --profile deep --focus disk --ai-prompt -o disk.json

# Сравнивает два отчёта linuxperf и записывает изменения в diff.json:
# дельты метрик, регрессии/улучшения, аномалии и ограничения сопоставимости.
python3.8 linuxperf.py diff before.json after.json -o diff.json

# Преобразует готовый JSON-отчёт в автономную HTML-страницу с экранированным JSON.
python3.8 linuxperf.py export report.json --format html -o report.html

# Строит SVG flamegraph из уже собранных стеков инструмента profile.
# Новую трассировку не запускает; без этих стеков в report.json вернёт ошибку.
python3.8 linuxperf.py export report.json --format flamegraph --collector profile -o cpu.svg

# Запускает MCP-сервер через stdin/stdout для подключения совместимого AI-клиента.
# Запросы клиента управляют сбором; это не HTTP-сервер и не однократный отчёт.
python3.8 linuxperf.py mcp
```

Примеры независимы: замените PID и путь cgroup на реальные, а для diff/export подготовьте входные отчёты. Стеки `profile` собираются в `deep`, если инструмент доступен и успел выполнить измерение. Время команды может превышать окно наблюдения из-за базового интервала и завершения сборщиков.

## Вывод в терминал

Обычный запуск показывает ход сбора с относительными отметками времени: начало фаз, запуск и завершение сборщиков, периодические сообщения о выборках и итог. Например:

```text
[0ms] Starting collection: profile=quick, duration=10s, interval=1s, external-tools=auto
[0ms] Phase 1: System baseline (no external tools running)...
[0ms]   [cpu_utilization] collecting...
[1.005s]   [cpu_utilization] done (1005ms)
...
[1.005s] Phase 2: External tools and periodic sampling...
...
[11.080s] Collection complete. 7 categories, health=65/100, anomalies=1
[11.080s] Health score: 65/100 | Coverage: 28/36 rules | Status: partial
[11.080s]   CRITICAL swap_usage: 91.6 % (threshold 50)
[11.080s] Recommendations: 1 fixes, 5 optimizations
[11.080s] Report saved to report.json (176.1 KiB)
```

Значения в примере иллюстративные; итог берётся из реально записанного отчёта. Progress и summary выводятся в **stderr**. При `-o -` stdout остаётся чистым JSON. `-q` отключает progress и summary, Недоступные внешние утилиты выводятся сразу при проверке, например `[biolatency] unavailable — missing_tool`, без необходимости включать verbose. `-v` дополнительно показывает пропуски по бюджету, подробности native fallback и каждую выборку. Сводка доступности также остаётся в итоге и JSON.

JSON остаётся подробным диагностическим отчётом. Чтобы уменьшить размер без удаления данных, используйте `--compact`: он убирает отступы и лишние пробелы.

```bash
python3.8 linuxperf.py collect --profile quick --compact -o report.json
```

С `--ai-prompt` компактный JSON включается автоматически. Инструкция для модели записывается отдельно от отчёта:

```bash
python3.8 linuxperf.py collect --profile standard --ai-prompt -o report.json
# report.json — компактный JSON с измерениями
# report.prompt.txt — инструкция для анализа отчёта
```

Вставьте текст `report.prompt.txt` в чат модели и прикрепите `report.json`. Блок `ai_context` в этом режиме исключается из сохранённого JSON, чтобы не дублировать инструкции. Имя промпта получается заменой последнего расширения отчёта на `.prompt.txt`; файл сохраняется в той же директории. При выводе отчёта в stdout (`-o -`, в том числе по умолчанию) промпт записывается в `report.prompt.txt` текущей директории, а stdout содержит только компактный JSON. Уведомление о файле идёт в stderr; `-q` его подавляет. Генерация выполняется локально и не вызывает модель.

## Сбор

Профили quick/standard/deep задают окна 10/30/60 секунд. `--duration` переопределяет окно, `--interval` — шаг выборки (по умолчанию 1 s). Первый интервал выполняется до запуска тяжёлых инструментов. В автоматическом режиме базовая диагностика использует этот чистый интервал, а последующие снимки сохраняются в `time_series` с `observer_active=true`.

Встроенные источники:

- CPU aggregate/per-core, load 1/5/15 min, CFS-параметры, context switches, PSI some/full, steal и IRQ.
- RAM, swap, reclaim/compaction/THP, buddyinfo, NUMA-счётчики и топология.
- Diskstats: IOPS, bytes/s, средняя задержка, очередь, busy time; параметры устройств из sysfs.
- TCP/UDP, softnet, интерфейсы, conntrack, socket memory/orphans, receive IRQ distribution, нормализованные ethtool/driver counters, sysctl; состояния TCP из procfs, listen backlog из SOCK_DIAG.
- Процессы: top CPU/RAM/IO, CPU, RSS и memory%, IO rates, threads, FD; фильтры PID/cgroup.
- Cgroup v1/v2: membership и mount root, quota, cpuset, memory limits/events, throttling rates, IO.
- ОС, uptime, boot parameters, локальные файловые системы через ограниченные worker-процессы/statvfs.
- PCI GPU/NIC, NUMA-расположение; GPU index/driver, GPU и memory utilization, VRAM, температура и энергопотребление при наличии nvidia-smi.

По умолчанию `--native-ebpf auto` сначала пытается использовать встроенный tcpretrans, затем `--external-tools auto` использует каталог из 67 внешних трассировщиков разных семейств и ss/ethtool/nvidia-smi/dmesg/df; наличие и совместимость каждой реализации проверяются отдельно. Quick выбирает biolatency, tcpretrans, opensnoop, oomkill и дополнительные системные команды. Standard выбирает runqlat, biolatency, tcpretrans, oomkill и системные команды; deep выбирает весь реестр с учётом focus. При collect команды не устанавливаются; отправка данных в сеть, sudo и автоматическое изменение настроек отсутствуют. Install и share запускаются отдельными явными командами.

У BCC-инструментов разные интерфейсы длительности. Для biosnoop, *slower, execsnoop, statsnoop и tcpsynbl окно ограничивает сам linuxperf с завершением через SIGINT; дополнительные аргументы длительности им не передаются. У biosnoop `-d` означает диск. Для wakeuptime используется `-f duration`, для llcstat — один аргумент duration. Stackcount получает `-f -K -D duration t:sched:sched_switch` и собирает стеки переключения задач; доступность tracepoint зависит от ядра.

Доступность проверяется по источникам и доверенным системным путям. Наличие бинарника не гарантирует права, kernel support или совместимость его версии. Неудачный запуск, ограничение бюджета, непонятный формат и отсутствие источника отражаются в результате.

Бюджеты внешнего сбора:

```bash
python3.8 linuxperf.py collect --profile deep --duration 180s --max-workers 4 --max-tool-seconds 30s -o extended.json
```

По умолчанию разрешено до 2 одновременных внешних сборщиков: массовый запуск BCC-компиляторов может исчерпать память и вызвать длительные зависания VM из-за swap. После чистого базового замера первым запускается oomkill: он получает полное окно профиля (с учётом --max-tool-seconds) и занимает один слот. Затем запускаются системные команды и остальные трассировки в пределах общего лимита сборщиков; при --max-workers 2 они используют второй слот до завершения oomkill. Standard запускает только runqlat, biolatency, tcpretrans и oomkill; полный набор, включая memleak и сбор стеков, доступен через deep. Не успевшие запуститься команды будут отмечены budget_exhausted; инструменты из очереди могут получить сокращённое окно. --max-workers позволяет явно изменить параллелизм. Максимальный вывод одной команды — 8 MiB с дополнительным общим бюджетом на выбранный набор. Deep собирает стеки 30 s; остальные инструменты используют длительность профиля. Явный --duration переопределяет оба окна. После базового интервала даётся полное окно трассировки и до 5 s на запуск/завершение инструментов. Deep требует оценки доступной памяти и нагрузки; даже один тяжёлый трассировщик может заметно повлиять на систему. Таймауты и усечённые результаты не считаются полными измерениями. `--external-tools off` запрещает диагностические команды, сохраняя возможность встроенного eBPF. Для чистого procfs/sysfs задайте также `--native-ebpf off`. Локальные statvfs workers остаются частью встроенного сбора.

## Отчёт и диагностика

JSON содержит `metadata`, `system`, `categories`, `metrics`, `metric_specs`, `time_series`, `summary`, `source_errors`, необязательный `ai_context`.

Для метрик указаны единица, метод, источник и scope. Каждый результат имеет окно измерения, backend, статус и причину неполноты. Дельты считаются по monotonic time; сброс счётчика или смена boot identity не превращаются в положительную скорость. PID сравнивается вместе со starttime. Размер страницы и CLK_TCK определяются через sysconf.

37 правил имеют зависимости от реально доступных входных данных. `summary` содержит USE, аномалии, рекомендации с evidence и coverage по категориям. Недоступное значение — null. Непроверенное правило перечислено в `unchecked_rules`; доказанно неприменимое — в `not_applicable_rules`.

`health_score` возвращается только при достаточном базовом наборе CPU/RAM/disk/network. `partial_health_score` относится исключительно к наблюдаемым данным. Алгоритм `linuxperf/use-2` использует веса ресурсов и отдельные штрафы за аномалии; связанная USE-метрика и аномалия могут давать два штрафа. Оценки нужно сравнивать вместе с coverage и score_version.

Восстановлены 35 исходных условий рекомендаций: порядок, priority, type, evidence, commands, persistent, expected_impact и source. Команды рекомендаций не выполняются. CPU throttling для исходного правила — накопленные throttled periods (пороги 100/1000); скорости и доля throttled periods сохраняются отдельно. USE использует исходные определения: CPU saturation=max(load/CPUs−1,0)×100; память — swap used%; диск — максимальный in_flight; сеть — TIME_WAIT+CLOSE_WAIT. Штрафы за USE и аномалии могут суммироваться. Неполнота исходных данных остаётся видна в coverage.

BCC-парсеры поддерживают tabular/periodic, отдельные устройства и единицы histogram, bucket-based percentiles, folded и inline kernel stacks, allocation stacks. Для percentile-аномалии требуется непустая выборка и известная единица; для SSD/HDD также известный rotational. Процентиль оценивается серединой выбранного bucket, как в исходном алгоритме; это не точный процентиль событий. События нормализуются, адреса и порты разделяются; доступны top-N группировки с количеством и средней/максимальной задержкой. Короткая выборка или неизвестный формат остаются неполными.

Diff сравнивает **только отчёты linuxperf**: общие метрики, USE, отдельные диски/интерфейсы и процентили. Выводятся regression/improvement, significance, число улучшений/регрессий и изменения состава аномалий; непроверенная аномалия не считается устранённой. Различающиеся единицы/методы/scope и отсутствующие значения помечаются несравнимыми. Смена хоста, boot, профиля и score_version отражается явно. HTML полностью автономен; SVG/folded требуют реальных стеков. При смешении samples/us/allocations нужно выбрать `--collector`.

## MCP

Stdio JSON-RPC, версия протокола `2024-11-05`: initialize, initialized, ping, tools/list, tools/call и notifications/cancelled. Поддерживаются get_health, collect_metrics, list_anomalies, explain_anomaly. Длительный сбор выполняется в отдельном процессе; основная петля продолжает принимать ping и отмену. Одновременно разрешён один сбор. EOF завершает собственные workers; логи идут только в stderr.

Ссылки на спецификацию: [stdio transport](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports), [cancellation](https://modelcontextprotocol.io/specification/2024-11-05/basic/utilities/cancellation).

## Проверка и ограничения среды

```bash
python3.8 -m py_compile linuxperf.py
python3.8 -m unittest discover -s tests -v
```

Тесты используют собственный каталог и текстовые фикстуры в `tests/fixtures`; установленная версия не читает файлы репозитория. Приёмочные результаты и непроверенные внешние окружения перечислены в [LINUXPERF_VALIDATION.md](LINUXPERF_VALIDATION.md).

Root и внешние утилиты необязательны для базовой диагностики. Hidepid, namespaces, seccomp, отсутствие PSI/sysfs и ограничения netlink уменьшают покрытие. Метрики относятся к видимой области: `/proc/stat` в контейнере может представлять хост, а cgroup — контейнер. `/proc/<PID>/net` не означает трафик только этого PID. Сетевые/autofs файловые системы не опрашиваются через statvfs. Ядро может не позволить немедленно завершить процесс в uninterruptible IO.

## Встроенный tcpretrans

На little-endian x86_64 используются системные вызовы bpf/perf_event_open через ctypes, mmap и сгенерированные инструкции BPF. Ни компилятор, ни libbpf, ни Python-пакет bcc не нужны. Первый вариант подключения — tracepoint tcp/tcp_retransmit_skb с чтением его format. Если tracefs не доступен, используются BTF /sys/kernel/btf/vmlinux, PMU kprobe и разрешённые по BTF поля struct sock_common. Поддержаны IPv4/IPv6. Буферы, perf FD и программы освобождаются после сбора. Потери ring buffer пока не подсчитываются: lost_events=null.

Нужны разрешения ядра на BPF/perf, подходящий kernel с ringbuf и доступ к tracepoint либо BTF/kprobe PMU. При отказе ядра выполняется fallback на внешний tcpretrans; причина native-отказа сохраняется в native_attempt. На других архитектурах native пока возвращает unsupported, остальные сборщики продолжают работать. Поле PID описывает текущий контекст выполнения, не гарантирует владельца сокета. Cgroup-фильтр не применяется к этой системной трассировке.

Документация механизма: [Linux BPF ring buffer](https://docs.kernel.org/bpf/ringbuf.html). Реальная загрузка и поток событий не подтверждены в текущей среде: bpf map create возвращает EPERM. Проверены BTF текущего ядра, ABI/инструкции, ringbuf decoder и пути отказа; это не заменяет привилегированный тест на целевом сервере.

## Явная установка и профилирование

```bash
python3.8 linuxperf.py install --dry-run
# Только при явном запуске под root:
python3.8 linuxperf.py install
python3.8 linuxperf.py collect --profile quick --self-profile linuxperf.pstats -o report.json
python3.8 -m pstats linuxperf.pstats
```

Install выбирает пакеты apt/dnf/yum/pacman/zypper по дистрибутиву, включая системные зависимости внешних BCC-инструментов и kernel headers. Сам linuxperf их не импортирует и не требует. Пакеты устанавливаются по одному; ошибки сохраняются в результате, частичная установка возвращает ненулевой код. Установка здесь не выполнялась. Встроенному SVG-генератору не требуется клонирование внешнего FlameGraph. `--pprof` — алиас `--self-profile`, формат файла — Python cProfile/pstats, а не бинарный формат Go pprof. Объединяются профили главного и рабочих потоков с CPU-таймером thread_time; дочерние внешние процессы учитываются отдельно через getrusage.

### Недостающие утилиты в РЕД ОС 7.3 / 8

Используйте репозитории своей версии и редакции РЕД ОС. Пакет `bcc-tools` опубликован, например, в [репозитории РЕД ОС 7.3](https://repo3.red-soft.ru/redos/7.3/x86_64/os/). Список официальных репозиториев и зеркал: [ресурсы РЕД СОФТ](https://redadm.red-soft.ru/about/public-resources/). Наличие конкретного файла проверяйте в подключённых репозиториях целевой машины: состав пакета меняется между версиями.

```bash
cat /etc/os-release
uname -r
dnf repolist
# Проверка доступных версий и установка основного набора BCC:
dnf --refresh list --available bcc-tools
sudo dnf install bcc-tools
# Если пакет уже установлен, проверить наличие обновления в своих репозиториях:
sudo dnf upgrade bcc-tools
# Какие инструменты поставляет установленный пакет:
rpm -ql bcc-tools
```

В каталоге linuxperf встречаются имена из разных семейств: Python/BCC, BCC libbpf-tools и bpftrace. Поэтому `missing_tool` не всегда устраняется установкой `bcc-tools`. Для следующих восьми имён сначала установите назначение и конкретную реализацию.

| Имя | Назначение | Реализация / аналоги и границы замены |
|---|---|---|
| `cpufreq` | Выборка частоты CPU по системе и процессам; помогает исследовать работу на пониженных частотах | [BCC libbpf-tools/cpufreq](https://github.com/iovisor/bcc/blob/master/libbpf-tools/cpufreq.c), также `cpufreq.bt` из книги. `cpupower frequency-info` показывает политику/доступную частоту, `turbostat` — аппаратные показатели при поддержке платформой; это не тот же профиль частот по процессам. В VM cpufreq sysfs может отсутствовать. |
| `udpconnect` | Трассировка вызовов подключения UDP-сокетов: процесс и адрес назначения. У UDP нет TCP-handshake; неподключённые sendto/sendmsg этим не покрываются | `udpconnect.bt` из [сетевых инструментов книги](https://github.com/brendangregg/bpf-perf-tools-book/tree/master/originals/Ch10_Networking). `ss -uap` — снимок сокетов, tcpdump — пакеты; они не заменяют трассировку connect. `tcpconnect` наблюдает TCP, `bindsnoop` — bind, это другие события. |
| `sockstat` | Периодическая статистика сокетов и частоты socket-related вызовов ядра/системных вызовов | `sockstat.bt` из того же сетевого набора. `ss -s`, `/proc/net/sockstat` и `/proc/net/sockstat6` дают часть агрегатов; `syscount` — частоты syscalls. Linuxperf уже читает sockstat/sockstat6 встроенным сбором. Одноимённая BSD-утилита или иной пакет не доказывают совместимость. |
| `skbdrop` | Трассировка освобождения/сбросов sk_buff с kernel stacks, чтобы локализовать место потери пакета | [skbdrop.bt](https://github.com/brendangregg/bpf-perf-tools-book/blob/master/originals/Ch10_Networking/skbdrop.bt) использует `skb:kfree_skb`. Смысл события и доступные причины зависят от ядра. `tcpdrop` — близкий инструмент только для TCP; это не полная замена всех skb-событий. |
| `numamove` | Количество и суммарное время NUMA-миграций misplaced pages/folios | [BCC libbpf-tools/numamove](https://github.com/iovisor/bcc/blob/master/libbpf-tools/numamove.c), также `numamove.bt` из главы Memory книги. `numastat -p PID` показывает размещение памяти, не задержки миграции. `numasched` трассирует миграции задач между NUMA, а не перенос страниц. |
| `scsilatency` | Распределения задержек SCSI-команд с разделением по host/opcode | `scsilatency.bt` из [главы Disks книги](https://github.com/brendangregg/bpf-perf-tools-book/tree/master/originals/Ch09_Disks). `biolatency`/`biosnoop` измеряют другой, блочный уровень; `iostat -x` даёт агрегаты, а не такую гистограмму SCSI-команд. |
| `nvmelatency` | Задержки команд NVMe-драйвера по устройству и opcode | `nvmelatency.bt` из той же главы Disks. `biolatency`/`biosnoop` — приближение на другом уровне стека. `nvme-cli`/SMART-лог дают сведения о контроллере, но не эквивалентную трассировку распределения задержек команд. |
| `biostacks` | Задержки блочного I/O, сгруппированные по стеку инициализации запроса | Есть [BCC libbpf-tools/biostacks](https://github.com/iovisor/bcc/blob/master/libbpf-tools/biostacks.c) и [bpftrace biostacks.bt](https://github.com/bpftrace/bpftrace/blob/master/tools/biostacks.bt). Stackcount на событии выдачи I/O показывает стеки/число событий, но не задержку завершения. |

Это функциональные аналоги для ручного исследования, а не взаимозаменяемые исполняемые файлы. Авторский [репозиторий BPF Performance Tools](https://github.com/brendangregg/bpf-perf-tools-book) отдельно отличает примеры книги от поддерживаемых инструментов BCC/bpftrace. Семейство libbpf-tools находится в репозитории BCC, но не является набором Python-скриптов из `tools/`. Наличие исходника upstream не подтверждает наличие RPM в конкретной РЕД ОС.

#### Поиск файлов без совпадений с исходниками ядра

Шаблон `*/cpufreq` слишком широк: он также совпадает с каталогом `/usr/src/debug/.../drivers/cpufreq` в kernel-debuginfo. Это не исполняемая утилита; устанавливать debuginfo ради такого совпадения не нужно. Ищите точные пути в каталогах инструментов:

```bash
for tool in cpufreq udpconnect sockstat skbdrop numamove scsilatency nvmelatency biostacks; do
    echo "Исполняемый инструмент: ${tool}"
    dnf provides "/usr/bin/${tool}" "/usr/sbin/${tool}" "/usr/bin/${tool}-bpfcc" "/usr/sbin/${tool}-bpfcc" "/usr/share/bcc/tools/${tool}" "/usr/share/bcc/tools/old/${tool}"
done
```

Для bpftrace-реализаций ищите отдельно `.bt`, например:

```bash
dnf provides '/usr/share/bpftrace/tools/biostacks.bt'
# Состав уже установленных пакетов:
rpm -ql bcc-tools
rpm -ql bpftrace
# Проверить, что найден именно исполняемый файл, а не каталог:
ls -l /usr/sbin/cpufreq
file /usr/sbin/cpufreq
```

Если DNF нашёл поставщика, сверяйте имя пакета, файловый путь и реализацию; затем устанавливайте именно этот пакет. Для подтверждённого файла возможна установка по точному пути:

```bash
# Только если DNF нашёл поставщика именно этого исполняемого файла:
sudo dnf install /usr/sbin/cpufreq
# Проверка интерфейса libbpf-tools (изучите вывод перед трассировкой):
/usr/sbin/cpufreq --help
```

Пути в примере — кандидаты, не обещание наличия файлов на конкретной системе. `No matches found` означает отсутствие поставщика в доступных метаданных подключённых репозиториев; ошибка сети не доказывает отсутствие пакета.

#### Совместимость с текущим linuxperf

Linuxperf обнаруживает имена `имя` и `имя-bpfcc` в доверенных каталогах. Он пока не запускает `.bt` через bpftrace и не сопоставляет функциональные аналоги автоматически. Нельзя переименовать `numastat` в `numamove`, `ss` в `sockstat` или `tcpdrop` в `skbdrop`: изменятся смысл, аргументы и формат результатов.

Особенно важно: текущий каталог передаёт `biostacks -f duration`, тогда как проверенный upstream libbpf-вариант принимает `[-d DISK] [-m] [duration]` и не имеет `-f`. Он выводит гистограммы задержек по стеку, а текущий linuxperf ожидает folded stacks. Поэтому установка даже правильного libbpf biostacks ещё не обеспечивает его работу в отчёте: требуется отдельный адаптер аргументов и парсера. Вывод `cpufreq` также содержит распределения частот, тогда как текущий каталог трактует его как общий табличный инструмент; корректный разбор этой реализации не подтверждён. Аналоги здесь предназначены для ручной диагностики до проверки интеграции.

`nvidia-smi` устанавливается отдельно и нужен при наличии доступного NVIDIA GPU (в VM — например, с пробросом GPU). Для проверки пакета-поставщика и установки, если он найден:

```bash
dnf provides '/usr/bin/nvidia-smi'
# Выполнять только после проверки найденного пакета и совместимости драйвера:
sudo dnf install /usr/bin/nvidia-smi
nvidia-smi
```

Установка пакета утилиты не гарантирует работающий GPU: могут потребоваться совместимый драйвер и перезагрузка. Официальные инструкции: [NVIDIA в РЕД ОС 7.3](https://redos.red-soft.ru/base/redos-7_3/7_3-equipment/7_3-video-drv/7_3-nvidia-install/) и [NVIDIA в РЕД ОС 8](https://redos.red-soft.ru/base/redos-8_0/8_0-equipment/8_0-video-drv/8_0-nvidia-install/). На VM без NVIDIA GPU этот сборщик можно оставить недоступным.

В приведённом запуске deep `53 skipped` означает исчерпание общего времени ожидания в очереди при двух сборщиках; установка пакетов это не исправляет. `timeout` и `parse_error` также не означают отсутствие утилиты. `ethtool: unsupported` означает неподдерживаемые запросы драйвера, а не недостающий пакет. Ошибки совместимости BCC с ядром рассмотрены в разделе «Ошибки запуска BCC» ниже.

## Публикация отчётов

```bash
# Локальная автономная ссылка, без сети:
python3.8 linuxperf.py share report.json --offline -o report-url.txt
# Свой сервис (SQLite, по умолчанию loopback, TTL 7 суток):
python3.8 linuxperf.py serve-reports --port 8787 --storage reports.sqlite --token example-token
# Явная отправка summary и metadata своему сервису:
python3.8 linuxperf.py share report.json --api-url http://127.0.0.1:8787/api/reports --token example-token
```

Offline-ссылка — самодостаточный data:text/html URL. Сервис принимает gzip JSON и возвращает короткую ссылку /r/<id>; HTML не требует CDN. Для нелокального bind обязательны --public-url и --token; TLS можно завершать на reverse proxy. Формат публикации самостоятельный, чужой сервис по умолчанию не используется. POST ограничен размером, TTL и частотой; БД создаётся с правами 0600. Данные отчёта доступны получателю ссылки. При collect отправки данных нет.

Промпт в отдельном `.prompt.txt` включает аномалии, сводку качества внешнего/native сбора по статусам и причинам, пустые результаты, окна измерений и накладные расходы самого linuxperf и дочерних процессов. Базовый замер отделён от периода трассировки; отсутствие событий не объявляется ошибкой или доказательством здоровья. Подсказки об анализе стеков и гистограмм добавляются только для успешных непустых результатов. Модель получает короткий формат ответа: ограничения сбора и до трёх проблем с доказательствами, единицами, окном наблюдения, уверенностью и командами проверки; настройка — с оценкой риска и откатом. В промпте сохранён справочник из 27 гипотез: модель должна выбирать только гипотезы с опорой на измерения, не перебирать весь список и не считать совпадение доказанной причиной. Если подтверждений нет, подбирать гипотезу принудительно не требуется. Сведения о CPU — это CPU-время, а peak RSS относится только к самому сборщику; эти значения не описывают полностью влияние BPF на ядро. Observer tracker исключает собственные/дочерние PID из процессных списков и доступных PID событий; общесистемные счётчики и агрегированные histograms физически вычесть нельзя.

## Ошибки запуска BCC

Наличие пакета bcc не гарантирует возможность компиляции всех трассировщиков. Если в stderr есть `chdir(/lib/modules/<release>/build): No such file or directory`, linuxperf выводит `missing_kernel_headers` и путь отсутствующих build headers прямо в терминале. Нужен пакет development headers именно работающего ядра; install для RPM-систем выбирает development package работающего ядра. Для РЕД ОС 7.3 с ядром 6.1 это `kernel-lt-devel-<uname release>`, для обычной RPM-схемы — `kernel-devel-<uname release>`. Наличие старой версии в подключённых репозиториях проверяется отдельно.

Другие ошибки различаются: `bpf_compile_error`, `bpf_attach_error`, `permission_denied`; stderr сохраняется в JSON. Непрерывные event tools останавливаются по duration без дополнительных 5 s наблюдения. Завершение окна считается успешным только при видимом стартовом заголовке и штатном выходе/ожидаемом SIGINT; пустой или принудительно убитый процесс остаётся partial.

Ошибка `unsupported_probe` означает, что установленная BCC-утилита запрашивает недоступный kernel probe. Например, старый `biolatency` может запрашивать `blk_account_io_done`, недоступный на целевом ядре. Нужна совместимая с работающим ядром версия BCC-утилиты; установка headers сама по себе эту ошибку не устраняет. Linuxperf сохраняет stderr и выводит имя probe, не подменяя отсутствующую histogram другими метриками.

В 1.1.2 исправлено преждевременное завершение команд после EOF stdout/stderr: закрытие вывода не означает завершения процесса. События собственных процессов исключаются до применения `--max-events`, чтобы компиляция BCC не вытесняла события нагрузки из `opensnoop`. Достижение лимитов теперь выводится как `result_limit`/`budget_exhausted` с пояснением.

Native tracing использует одно perf-подключение на онлайн-CPU, как [bpf_attach_tracing_event в BCC](https://github.com/iovisor/bcc/blob/master/src/cc/libbpf.c): tracing callbacks действуют для всех CPU. Убрано повторное присоединение той же программы на каждом CPU, способное приводить к `EEXIST`. Ошибки perf содержат стадию подключения; при переходе к внешнему tcpretrans причина native-отказа видна без `--verbose`.

Отказ kernel verifier во встроенном backend имеет причину `verifier_rejected`, даже если syscall вернул EACCES. Это отличается от отсутствия прав. В 1.1.1 исправлены невыровненные чтения tracepoint context (например, IPv4-поле с offset=34); verifier log сохраняется отдельно. Перед загрузкой выполняется попытка поднять memlock только текущего процесса, без изменения настроек ОС.
