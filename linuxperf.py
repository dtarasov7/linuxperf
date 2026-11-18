#!/usr/bin/env python3
"""Linux performance diagnostics, Python 3.8+, standard library only.

Usage: python3 linuxperf.py collect --profile quick -o report.json
External tools are discovered automatically; --external-tools off disables them.
Collection never installs packages, uploads reports, or changes system settings.
Installation and network sharing are separate explicitly invoked commands.

Tool catalog and initial threshold values were informed by melisai
(https://github.com/dmitriimaksimovdevelop/melisai), whose README identifies
the project license as Apache-2.0. This implementation has its own report schema.
"""
import argparse
import datetime
import csv
from concurrent.futures import ThreadPoolExecutor
import glob
import html
import json
import logging
import math
import socket
import struct
import multiprocessing
import os
import re
import resource
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import threading
import ctypes
import mmap
import fcntl
import errno
import io
import sqlite3
import secrets
import http.server
import cProfile
import pstats
import gzip
import base64
import urllib.request
import urllib.parse

VERSION = '1.1.2'
SCHEMA = 'linuxperf/1.0'
STOP = 0
TOOLS = {}


class Progress:
    """Потокобезопасный вывод хода сбора и сводки отдельно от JSON."""
    def __init__(self, quiet=False, verbose=False, stream=None):
        """Настраивает вывод прогресса и счётчик времени.

        Параметры: quiet, verbose (bool): режимы вывода; stream (TextIO или None): поток, по умолчанию stderr.
        Возвращает: None.
        """
        self.quiet, self.verbose = quiet, verbose
        self.stream = stream if stream is not None else sys.stderr
        self.started = time.monotonic()
        self.collectors = {}
        self.lock = threading.RLock()

    def log(self, message):
        """Печатает сообщение с относительной отметкой времени.

        Параметры: message (str): сообщение.
        Возвращает: None; quiet подавляет вывод.
        """
        if self.quiet:
            return
        with self.lock:
            elapsed = time.monotonic() - self.started
            stamp = '%dms' % (elapsed * 1000) if elapsed < 1 else '%.3fs' % elapsed
            print('[%s] %s' % (stamp, message), file=self.stream, flush=True)

    def begin(self, name):
        """Запоминает время старта сборщика и сообщает о начале.

        Параметры: name (str): имя сборщика.
        Возвращает: None.
        """
        with self.lock:
            self.collectors[name] = time.monotonic()
            self.log('  [%s] collecting...' % name)

    def end(self, name, status='ok', reason=None):
        """Показывает результат и длительность работы сборщика.

        Параметры: name, status (str): сборщик и состояние; reason (str или None): пояснение.
        Возвращает: None; некоторые незапущенные сборщики видимы только в verbose.
        """
        with self.lock:
            started = self.collectors.pop(name, None)
            if started is None and not self.verbose and status != 'unavailable':
                return
            duration = ' (%.0fms)' % ((time.monotonic() - started) * 1000) if started is not None else ''
            label = 'done' if status == 'ok' else status
            detail = ' — ' + str(reason) if reason else ''
            self.log('  [%s] %s%s%s' % (name, label, duration, detail))

    def summary(self, report, output):
        """Выводит итог из фактически собранного отчёта.

        Параметры: report (dict): отчёт; output (str): путь файла или «-».
        Возвращает: None.
        Ошибки: OSError при чтении размера недоступного выходного файла.
        """
        summary = report['summary']
        score = summary['health_score']
        health = '%s/100' % score if score is not None else 'unavailable (insufficient data)'
        categories = sum(bool(rows) for rows in report['categories'].values())
        state = 'interrupted' if report['metadata']['interrupted'] else 'complete'
        self.log('Collection %s. %d categories, health=%s, anomalies=%d' %
                 (state, categories, health, len(summary['anomalies'])))
        coverage = summary['coverage']
        self.log('Health score: %s | Coverage: %d/%d rules | Status: %s' %
                 (health, coverage['evaluated'], coverage['selected'], report['metadata']['status']))
        anomalies = summary['anomalies']
        for anomaly in anomalies[:5]:
            self.log('  %s %s: %.3g %s (threshold %.3g)' %
                     (anomaly['severity'].upper(), anomaly['metric'], anomaly['value'],
                      anomaly['unit'], anomaly['threshold']))
        if len(anomalies) > 5:
            self.log('  ... %d more anomalies in report' % (len(anomalies) - 5))
        if not anomalies:
            self.log('No anomalies detected in available measurements.')
        external = [r for rows in report['categories'].values() for r in rows if r['backend'] == 'external']
        if external:
            counts = {status: sum(r['status'] == status for r in external) for status in ('ok', 'partial', 'unavailable', 'skipped', 'error')}
            self.log('External tools: ' + ', '.join('%d %s' % (count, status) for status, count in counts.items() if count))
        native = [r if r['backend'] == 'native_ebpf' else r['native_attempt'] for rows in report['categories'].values() for r in rows if r['backend'] == 'native_ebpf' or 'native_attempt' in r]
        if native:
            self.log('Native eBPF: ' + ', '.join('%s=%s%s' % (r['collector'], r['status'], ' (' + r['reason'] + ')' if r.get('reason') else '') for r in native))
        fixes = sum(r['type'] == 'fix' for r in summary['recommendations'])
        optimizations = sum(r['type'] == 'optimization' for r in summary['recommendations'])
        self.log('Recommendations: %d fixes, %d optimizations' % (fixes, optimizations))
        if output == '-':
            self.log('Report written to stdout.')
        else:
            self.log('Report saved to %s (%.1f KiB)' % (output, os.path.getsize(output) / 1024))


def progress(cfg):
    """Получает необязательный индикатор хода сбора.

    Параметры: cfg (argparse.Namespace): настройки запуска.
    Возвращает: Progress или None.
    """
    return getattr(cfg, 'progress', None)


def utc():
    """Формирует текущую отметку времени UTC.

    Возвращает: str: дата и время в ISO 8601 с часовым поясом.
    """
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def divide(a, b, scale=1):
    """Делит известные значения с проверкой положительного знаменателя.

    Параметры: a, b (число или None): числитель и знаменатель; scale (число): множитель.
    Возвращает: Число или None при неизвестном числителе либо неположительном знаменателе.
    """
    return a / b * scale if a is not None and b and b > 0 else None


def delta(a, b, elapsed):
    """Вычисляет скорость изменения монотонного счётчика.

    Параметры: a, b (число или None): значения до и после; elapsed (float): секунды.
    Возвращает: Число или None при сбросе счётчика, пропуске или неположительном времени.
    """
    return (b - a) / elapsed if a is not None and b is not None and b >= a and elapsed > 0 else None


def pairs(text):
    """Разбирает строки источника в пары имени и целого значения.

    Параметры: text (str): строки вида «имя: число» или «имя число».
    Возвращает: dict: первые числовые значения строк; неподходящие строки пропускаются.
    """
    result = {}
    for line in text.splitlines():
        fields = line.replace(':', '').split()
        if len(fields) >= 2:
            try:
                result[fields[0]] = int(fields[1])
            except ValueError:
                continue
    return result


class Source:
    """Чтение procfs/sysfs с лимитами и накоплением уникальных ошибок."""
    def __init__(self, proc='/proc', sysroot='/sys', etc='/etc'):
        """Задаёт корни источников и пустой журнал ошибок.

        Параметры: proc, sysroot, etc (str): корни procfs, sysfs и конфигурации.
        Возвращает: None.
        """
        self.proc, self.sys, self.etc = proc, sysroot, etc
        self.errors = []
        self._error_keys = set()

    def read(self, path, limit=4 * 1024 * 1024):
        """Читает файл с ограничением байтов и регистрацией отказов.

        Параметры: path (str): путь; limit (int): максимум байтов.
        Возвращает: str: текст с заменой неверного UTF-8; при OSError — пустая строка и запись в errors.
        """
        try:
            with open(path, 'rb') as stream:
                chunks, remaining = [], limit + 1
                while remaining:
                    size = min(65536, remaining)
                    block = stream.read(size)
                    chunks.append(block)
                    remaining -= len(block)
                    if len(block) < size:
                        break
                data = b''.join(chunks)
            if len(data) > limit:
                self.error(path, 'budget_exhausted')
                data = data[:limit]
            return data.decode('utf-8', 'replace')
        except OSError as exc:
            self.error(path, 'permission_denied' if exc.errno in (1, 13) else 'missing_source')
            return ''

    def error(self, path, reason):
        """Добавляет ошибку источника без дубликатов.

        Параметры: path, reason (str): источник и причина.
        Возвращает: None; журнал ограничен 1000 уникальных записей.
        """
        record = {'source': path, 'reason': reason}
        key = (path, reason)
        if len(self.errors) < 1000 and key not in self._error_keys:
            self._error_keys.add(key)
            self.errors.append(record)

    def p(self, path):
        """Читает файл относительно корня procfs.

        Параметры: path (str): относительный путь.
        Возвращает: str: содержимое или пустая строка с записью ошибки.
        """
        return self.read(os.path.join(self.proc, path))

    def s(self, path):
        """Читает файл относительно корня sysfs.

        Параметры: path (str): относительный путь.
        Возвращает: str: содержимое или пустая строка с записью ошибки.
        """
        return self.read(os.path.join(self.sys, path))


def proc_stat(text):
    """Извлекает идентичность процесса и счётчики из procfs stat.

    Параметры: text (str): содержимое /proc/PID/stat.
    Возвращает: dict: comm, состояние, CPU ticks, starttime, RSS в байтах и PPID.
    Ошибки: ValueError при неполной строке или неверных числах.
    """
    end = text.rfind(')')
    fields = text[end + 2:].split()
    if end < 0 or len(fields) < 22:
        raise ValueError('invalid process stat')
    return {'comm': text[text.find('(') + 1:end], 'state': fields[0],
            'ticks': int(fields[11]) + int(fields[12]), 'starttime': int(fields[19]),
            'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE'), 'ppid': int(fields[1])}


def snapshot(src, cfg):
    """Снимает доступные счётчики системы и выбранных процессов.

    Параметры: src (Source): корни и ошибки чтения; cfg (argparse.Namespace): PID, cgroup и лимиты.
    Возвращает: dict: снимок с UTC, монотонным временем и boot identity; пропуски отражаются в src.errors.
    """
    snap = {'timestamp': utc(), 'time': time.monotonic(), 'boot': src.p('sys/kernel/random/boot_id').strip()}
    snap['global_stat'] = pairs(src.p('stat'))
    snap['cgroup'] = cgroup_snapshot(src, cfg)
    snap['sysctls'] = {key: src.p('sys/' + key).strip() for key in SYSCTLS}
    snap['net_rx'] = {}
    for line in src.p('softirqs').splitlines():
        if line.strip().startswith('NET_RX:'):
            try:
                snap['net_rx'] = {i: int(v) for i, v in enumerate(line.split()[1:])}
            except ValueError:
                src.error('softirqs', 'parse_error')
    snap['stat'] = {}
    for line in src.p('stat').splitlines():
        f = line.split()
        if f and f[0].startswith('cpu'):
            try:
                snap['stat'][f[0]] = [int(x) for x in f[1:9]]
            except ValueError:
                src.error('stat', 'parse_error')
    for name in ('meminfo', 'vmstat'):
        snap[name] = pairs(src.p(name))
    snap['tcp_text'] = src.p('net/tcp') + '\n' + src.p('net/tcp6')
    snap['socket_memory'] = {name: parse_sockstat(src.p('net/' + name)) for name in ('sockstat', 'sockstat6')}
    snap['load'] = src.p('loadavg').split()[:3]
    snap['disks'] = {}
    for line in src.p('diskstats').splitlines():
        f = line.split()
        if len(f) >= 14:
            try:
                snap['disks'][f[2]] = [int(x) for x in f[3:]]
            except ValueError:
                src.error('diskstats', 'parse_error')
    snap['net'] = {}
    for line in src.p('net/dev').splitlines():
        if ':' in line:
            name, values = line.split(':', 1)
            try:
                snap['net'][name.strip()] = [int(x) for x in values.split()]
            except ValueError:
                src.error('net/dev', 'parse_error')
    snap['rx_dropped'] = {name: int_or_none(src.s('class/net/' + name + '/statistics/rx_dropped')) for name in snap['net']}
    snap['protocol'] = {}
    for name in ('snmp', 'netstat'):
        lines = src.p('net/' + name).splitlines()
        for header, values in zip(lines[::2], lines[1::2]):
            h, v = header.split(), values.split()
            if h and v and h[0] == v[0]:
                try:
                    snap['protocol'].update({h[0] + k: int(n) for k, n in zip(h[1:], v[1:])})
                except ValueError:
                    src.error('net/' + name, 'parse_error')
    softnet = []
    for line in src.p('net/softnet_stat').splitlines():
        try:
            fields = [int(v, 16) for v in line.split()]
            if len(fields) >= 3:
                softnet.append(fields)
        except ValueError:
            src.error('net/softnet_stat', 'parse_error')
    snap['softnet'] = sum(f[1] for f in softnet) if softnet else None
    snap['squeeze'] = sum(f[2] for f in softnet) if softnet else None
    snap['psi'] = {}
    for name in ('cpu', 'memory', 'io'):
        for line in src.p('pressure/' + name).splitlines():
            f = line.split()
            if f and f[0] in ('some', 'full'):
                try:
                    values = dict(x.split('=', 1) for x in f[1:])
                    if 'avg10' in values and math.isfinite(float(values['avg10'])):
                        snap['psi'].setdefault(name, {})[f[0]] = values
                except ValueError:
                    src.error('pressure/' + name, 'parse_error')
    snap['processes'] = {}
    try:
        candidates = [str(cfg.pid)] if cfg.pid else sorted(os.listdir(src.proc))
    except OSError:
        candidates = []
        src.errors.append({'source': src.proc, 'reason': 'missing_source'})
    seen = 0
    for pid in candidates:
        if not pid.isdigit() or int(pid) in getattr(cfg, 'observer_pids', {os.getpid()}):
            continue
        seen += 1
        if seen > 10000:
            src.errors.append({'source': 'processes', 'reason': 'budget_exhausted'})
            break
        membership = src.p(pid + '/cgroup') if cfg.cgroup else ''
        if cfg.cgroup and not any(line.split(':', 2)[-1] == cfg.cgroup_membership or line.split(':', 2)[-1].startswith(cfg.cgroup_membership.rstrip('/') + '/') for line in membership.splitlines()):
            continue
        try:
            data = proc_stat(src.p(pid + '/stat'))
            if getattr(cfg, 'observer', None) and cfg.observer.is_observer(int(pid), data['ppid']):
                continue
            data.update(pairs(src.p(pid + '/io')))
            data['pid'] = int(pid)
            snap['processes'][pid] = data
        except (ValueError, IndexError):
            continue
    return snap


def trusted_tool(name):
    """Находит исполняемый файл в доверенных системных каталогах.

    Параметры: name (str): имя команды без пути; проверяется также суффикс -bpfcc.
    Возвращает: str: разрешённый абсолютный путь, либо None; проверяются владелец и права пути.
    """
    for root in ('/usr/share/bcc/tools', '/usr/sbin', '/usr/bin', '/usr/local/bin', '/usr/local/sbin', '/usr/share/bcc/tools/old', '/snap/bin', '/sbin', '/bin'):
        for candidate in (name, name + '-bpfcc'):
            path = os.path.realpath(os.path.join(root, candidate))
            try:
                current = path
                while current != '/':
                    st = os.stat(current)
                    if st.st_uid != 0 or st.st_mode & 0o022:
                        break
                    current = os.path.dirname(current)
                else:
                    if os.path.isfile(path) and os.access(path, os.X_OK):
                        return path
            except OSError:
                continue
    return None


def command(path, args, timeout, cap=8 * 1024 * 1024, tracker=None, stop_signal=signal.SIGTERM):
    """Запускает команду без shell и ограничивает время и объём вывода.

    Параметры: path (str): исполняемый файл; args (list[str]): argv; timeout (float): секунды; cap (int): общий лимит stdout/stderr в байтах; tracker (ObserverTracker или None): учёт PID; stop_signal (int): первый сигнал остановки.
    Возвращает: dict: stdout, stderr, reason, returncode и truncated; STOP инициирует остановку группы.
    Ошибки: OSError при запуске/работе с процессом, TimeoutExpired при незавершённом cleanup.
    """
    output = [bytearray(), bytearray()]
    truncated = False
    status = 'ok'
    with subprocess.Popen([path] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'LANG': 'C', 'PYTHONUNBUFFERED': '1'}) as child:
        if tracker:
            tracker.register(child.pid)
        sel = selectors.DefaultSelector()
        for i, stream in enumerate((child.stdout, child.stderr)):
            os.set_blocking(stream.fileno(), False)
            sel.register(stream, selectors.EVENT_READ, i)
        # Для таймаутов используем монотонные часы, независимые от коррекции системного времени.
        deadline = time.monotonic() + timeout
        stopping = False
        try:
            while sel.get_map():
                if (STOP and not stopping) or time.monotonic() >= deadline:
                    if stopping:
                        break
                    status = 'interrupted' if STOP else 'timeout'
                    if tracker:
                        tracker.snapshot()
                    try:
                        os.killpg(child.pid, stop_signal)
                    except ProcessLookupError:
                        logging.debug('Child exited before stop signal')
                    stopping = True
                    deadline = time.monotonic() + .5
                for key, _ in sel.select(min(.1, max(0, deadline - time.monotonic()))):
                    data = os.read(key.fd, 65536)
                    if not data:
                        sel.unregister(key.fileobj)
                    else:
                        available = cap - sum(len(x) for x in output)
                        output[key.data].extend(data[:max(0, available)])
                        if len(data) > available:
                            truncated = True
                            status = 'budget_exhausted'
                            break
                if truncated:
                    break
            # Закрытые stdout/stderr ещё не означают завершение процесса.
            # Ждём exit отдельно, продолжая проверять STOP и дедлайн.
            while status == 'ok' and child.poll() is None:
                if STOP or time.monotonic() >= deadline:
                    status = 'interrupted' if STOP else 'timeout'
                    break
                try:
                    child.wait(timeout=min(.1, max(.001, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    continue
        finally:
            sel.close()
            if child.poll() is None or status != 'ok':
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=.2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    logging.debug('Child already exited')
            try:
                child.wait(timeout=max(.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                status = 'timeout'
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    logging.debug('Child already reaped')
                child.wait(timeout=1)
            if tracker:
                tracker.snapshot()
    return {'stdout': output[0].decode('utf-8', 'replace'), 'stderr': output[1].decode('utf-8', 'replace'),
            'reason': status if status != 'ok' else (None if child.returncode == 0 else 'command_failed'),
            'returncode': child.returncode, 'truncated': truncated}



def result(name, category, data, backend='procfs', status='ok', reason=None):
    """Создаёт запись сборщика в схеме отчёта.

    Параметры: name, category, backend, status (str): идентификаторы и состояние; data (object): данные; reason (str или None): причина неполноты.
    Возвращает: dict: запись с областью host-visible по умолчанию.
    """
    return {'collector': name, 'category': category, 'backend': backend, 'status': status,
            'reason': reason, 'data': data, 'scope': 'host-visible'}


def collect(cfg):
    """Собирает базу, трассировки и итоговую диагностику в один отчёт.

    Параметры: cfg (argparse.Namespace): проверенные через prepare настройки сбора.
    Возвращает: dict: отчёт linuxperf с метриками, coverage, окнами и накладными расходами.
    Ошибки: ValueError при несовместимом выборе PID/cgroup; недоступные источники сохраняются как неполнота.
    """
    src = Source(cfg.proc_root, cfg.sys_root, cfg.etc_root)
    start, stamp = time.monotonic(), utc()
    cfg.observer = ObserverTracker(src)
    cfg.observer_pids = cfg.observer.pids
    before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    observer_before = observer_snapshot(src)
    categories = {k: [] for k in ('cpu', 'memory', 'disk', 'network', 'process', 'container', 'system', 'stacktrace')}
    display = progress(cfg)
    tracing = cfg.external_tools == 'auto' or cfg.native_ebpf == 'auto'
    if display:
        display.log('Starting collection: profile=%s, duration=%gs, interval=%gs, external-tools=%s' % (cfg.profile, cfg.duration, cfg.interval, cfg.external_tools))
        display.log('Phase 1: System baseline (no external tools running)...')
        for name in ('cpu_utilization', 'memory_info', 'disk_stats', 'network_stats', 'process_info', 'container_info'):
            display.begin(name)
    if cfg.cgroup:
        cfg.cgroup_membership = resolve_cgroup(src, cfg.cgroup)
    first = snapshot(src, cfg)
    if cfg.pid and cfg.cgroup and str(cfg.pid) not in first['processes']:
        raise ValueError('PID does not belong to selected cgroup or is inaccessible')
    sampling_deadline = start + cfg.duration + (cfg.interval if tracing else 0)
    deadline = sampling_deadline + (5 if tracing else 0)
    samples = 1
    # Чистый интервал заканчивается до запуска тяжёлых трассировщиков.
    while not STOP and time.monotonic() < min(deadline, start + cfg.interval):
        time.sleep(min(.05, max(0, min(deadline, start + cfg.interval) - time.monotonic())))
    baseline = snapshot(src, cfg)
    last = baseline
    cfg.baseline_queues = listen_queues(min(1., cfg.interval)) if src.proc == '/proc' else {'listeners': [], 'errors': ['fixture mode'], 'status': 'unavailable'}
    cfg.baseline_gauge_time = utc()
    samples += 1
    if display:
        sources = {'cpu_utilization': 'stat', 'memory_info': 'meminfo', 'disk_stats': 'disks', 'network_stats': 'net', 'process_info': 'processes'}
        for name, source in sources.items():
            available = bool(first[source]) and bool(baseline[source])
            display.end(name, 'ok' if available else 'unavailable', None if available else 'missing_source')
        available = baseline['cgroup']['version'] is not None
        display.end('container_info', 'ok' if available else 'unavailable', None if available else 'missing_source')
        display.log('Phase 2: External tools and periodic sampling...' if cfg.external_tools == 'auto' else 'Phase 2: Native eBPF and periodic sampling (external tools disabled)...' if cfg.native_ebpf == 'auto' else 'Phase 2: Periodic sampling (external tools disabled)...')
    pool, future = None, None
    if tracing and not STOP:
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(profiled_task, cfg, run_tools if cfg.external_tools == 'auto' else run_native_only, cfg, categories, deadline)
    series = [sample_summary(first, baseline, False)]
    missed_samples = 0
    next_sample = time.monotonic() + cfg.interval
    next_update = time.monotonic() + 5
    try:
        while not STOP and time.monotonic() < sampling_deadline:
            until = min(next_sample, sampling_deadline)
            while not STOP and time.monotonic() < until:
                time.sleep(min(.05, max(0, until - time.monotonic())))
            if STOP:
                break
            previous = last
            last = snapshot(src, cfg)
            series.append(sample_summary(previous, last, tracing))
            samples += 1
            if display and (display.verbose or time.monotonic() >= next_update):
                display.log('Sampling: %d samples, %.1f/%gs elapsed' % (samples, time.monotonic() - start, cfg.duration))
                next_update = time.monotonic() + 5
            next_sample += cfg.interval
            if next_sample < time.monotonic():
                skipped = int((time.monotonic() - next_sample) / cfg.interval) + 1
                missed_samples += skipped
                next_sample += skipped * cfg.interval
        if future:
            future.result()
    finally:
        if pool:
            pool.shutdown(wait=True)
    if display:
        display.log('Sampling complete: %d samples; assembling report...' % samples)
        display.begin('system_info')
        display.begin('gpu_pcie')
    assembly_stamp = utc()
    observed_last = last
    # Базовые метрики считаются до трассировки; поздние снимки остаются во временном ряду.
    if tracing:
        last = baseline
    elapsed = last['time'] - first['time']
    valid = first['boot'] == last['boot']
    rate = lambda a, b: delta(a, b, elapsed) if valid else None
    metrics = {}
    cpu = {}
    for name, values in last['stat'].items():
        old = first['stat'].get(name)
        if valid and old and len(old) == len(values) and all(b >= a for a, b in zip(old, values)):
            changes = [b - a for a, b in zip(old, values)]
            total = sum(changes)
            cpu[name] = {key: divide(v, total, 100) for key, v in zip(('user_pct', 'nice_pct', 'system_pct', 'idle_pct', 'iowait_pct', 'irq_pct', 'softirq_pct', 'steal_pct'), changes)}
    aggregate = cpu.get('cpu', {})
    metrics['cpu_utilization'] = 100 - aggregate['idle_pct'] if aggregate.get('idle_pct') is not None else None
    metrics['cpu_iowait'] = aggregate.get('iowait_pct')
    try:
        metrics['load_average'] = float(last['load'][0]) / max(1, len([k for k in last['stat'] if k != 'cpu'])) if last['load'] and last['stat'] else None
    except ValueError:
        metrics['load_average'] = None
        src.error('loadavg', 'parse_error')
    categories['cpu'].append(result('cpu_utilization', 'cpu', cpu, status='ok' if aggregate else 'unavailable'))
    mem = last['meminfo']
    metrics['memory_utilization'] = divide(mem.get('MemTotal', 0) - mem['MemAvailable'], mem.get('MemTotal'), 100) if 'MemAvailable' in mem else None
    metrics['swap_usage'] = divide(mem.get('SwapTotal', 0) - mem.get('SwapFree', 0), mem.get('SwapTotal'), 100)
    for metric, keys in [('direct_reclaim_rate', [k for k in last['vmstat'] if k.startswith('pgscan_direct') and k != 'pgscan_direct_throttle']), ('compaction_stall_rate', ['compact_stall']), ('thp_split_rate', ['thp_split_page'])]:
        values = [rate(first['vmstat'].get(k), last['vmstat'].get(k)) for k in keys]
        metrics[metric] = sum(values) if values and all(v is not None for v in values) else None
    categories['memory'].append(result('memory_info', 'memory', {'meminfo': mem, 'total_bytes': scale(mem.get('MemTotal'), 1024), 'available_bytes': scale(mem.get('MemAvailable'), 1024), 'cached_bytes': scale(mem.get('Cached'), 1024), 'buffers_bytes': scale(mem.get('Buffers'), 1024), 'swap_total_bytes': scale(mem.get('SwapTotal'), 1024), 'swap_free_bytes': scale(mem.get('SwapFree'), 1024), 'vmstat': last['vmstat'], 'thp': src.s('kernel/mm/transparent_hugepage/enabled').strip(), 'numa': {os.path.basename(p): pairs(src.read(p + '/numastat')) for p in glob.glob(src.sys + '/devices/system/node/node[0-9]*')}}))
    disks = []
    for name, b in last['disks'].items():
        a = first['disks'].get(name)
        if not a or len(a) < 11 or len(b) < 11:
            continue
        rd, wr = rate(a[0], b[0]), rate(a[4], b[4])
        disks.append({'name': name, 'read_iops': rd, 'write_iops': wr, 'read_bytes_per_sec': scale(rate(a[2], b[2]), 512), 'write_bytes_per_sec': scale(rate(a[6], b[6]), 512), 'utilization_pct': scale(rate(a[9], b[9]), .1), 'avg_latency_ms': divide(rate(a[3] + a[7], b[3] + b[7]), rd + wr) if rd is not None and wr is not None else None, 'average_queue': scale(rate(a[10], b[10]), .001), 'in_flight': b[8]})
    for key, field in [('disk_utilization', 'utilization_pct'), ('disk_avg_latency', 'avg_latency_ms')]:
        metrics[key] = maximum(d[field] for d in disks)
    categories['disk'].append(result('disk_stats', 'disk', {'devices': disks}))
    interfaces = []
    for name, b in last['net'].items():
        a = first['net'].get(name)
        if a and len(a) >= 16 and len(b) >= 16:
            interfaces.append({'name': name, 'rx_bytes_per_sec': rate(a[0], b[0]), 'tx_bytes_per_sec': rate(a[8], b[8]), 'errors_per_sec': rate(a[2] + a[10], b[2] + b[10]), 'drops_per_sec': rate(a[3] + a[11], b[3] + b[11])})
    for key, field in [('tcp_retransmits', 'Tcp:RetransSegs'), ('listen_overflows', 'TcpExt:ListenOverflows')]:
        metrics[key] = rate(first['protocol'].get(field), last['protocol'].get(field))
    metrics['softnet_dropped'] = rate(first['softnet'], last['softnet'])
    metrics['softnet_time_squeeze'] = rate(first['squeeze'], last['squeeze'])
    metrics['network_errors_per_sec'] = maximum(i['errors_per_sec'] for i in interfaces)
    metrics['network_interface_errors_total'] = sum(i['errors_per_sec'] for i in interfaces) if interfaces and all(i['errors_per_sec'] is not None for i in interfaces) else None
    for key, field in [('tcp_abort_on_memory', 'TcpExt:TCPAbortOnMemory'), ('udp_rcvbuf_errors', 'Udp:RcvbufErrors'), ('tcp_rcvq_drop', 'TcpExt:TCPRcvQDrop'), ('tcp_zero_window_drop', 'TcpExt:TCPZeroWindowDrop')]:
        metrics[key] = rate(first['protocol'].get(field), last['protocol'].get(field))
    tcp_text = last['tcp_text']
    metrics['tcp_close_wait'] = sum(1 for l in tcp_text.splitlines() if len(l.split()) > 3 and l.split()[3] == '08') if tcp_text else None
    metrics['tcp_timewait'] = sum(1 for l in tcp_text.splitlines() if len(l.split()) > 3 and l.split()[3] == '06') if tcp_text else None
    count, maximum_ct = src.p('sys/net/netfilter/nf_conntrack_count').strip(), src.p('sys/net/netfilter/nf_conntrack_max').strip()
    metrics['conntrack_usage_pct'] = divide(int(count), int(maximum_ct), 100) if count.isdigit() and maximum_ct.isdigit() else None
    categories['network'].append(result('network_stats', 'network', {'interfaces': interfaces, 'protocol_counters': last['protocol'], 'socket_states_scope': 'network_namespace'}))
    for source, key in [('cpu', 'cpu_psi_pressure'), ('memory', 'memory_psi_pressure'), ('io', 'io_psi_pressure')]:
        metrics[key] = float(last['psi'][source]['some']['avg10']) if source in last['psi'] and 'some' in last['psi'][source] else None
    processes = []
    for pid, b in last['processes'].items():
        a = first['processes'].get(pid)
        item = dict(b)
        item['memory_pct'] = divide(b['rss_bytes'], scale(mem.get('MemTotal'), 1024), 100)
        same_process = a and a['starttime'] == b['starttime']
        item['read_bytes_per_sec'] = rate(a.get('read_bytes'), b.get('read_bytes')) if same_process else None
        item['write_bytes_per_sec'] = rate(a.get('write_bytes'), b.get('write_bytes')) if same_process else None
        item['cpu_pct'] = scale(rate(a['ticks'], b['ticks']), 100 / os.sysconf('SC_CLK_TCK')) if a and a['starttime'] == b['starttime'] else None
        processes.append(item)
    categories['process'].append(result('process_info', 'process', {'top_by_cpu': sorted(processes, key=lambda p: p['cpu_pct'] or 0, reverse=True)[:cfg.top], 'top_by_memory': sorted(processes, key=lambda p: p['rss_bytes'], reverse=True)[:cfg.top], 'top_by_io': sorted(processes, key=lambda p: (p['read_bytes_per_sec'] or 0) + (p['write_bytes_per_sec'] or 0), reverse=True)[:cfg.top]}, status='ok' if processes else 'partial'))
    categories['container'].append(result('container_info', 'container', last['cgroup'], backend='cgroup'))
    categories['system'].append(result('system_info', 'system', {'os_release': src.read(src.etc + '/os-release'), 'kernel': os.uname().release, 'uptime': src.p('uptime').split()[:1], 'mountinfo': src.p('self/mountinfo')}))
    pci = []
    for path in glob.glob(src.sys + '/bus/pci/devices/*'):
        cls = src.read(path + '/class').strip()
        if cls.startswith(('0x03', '0x02')):
            pci.append({'pci': os.path.basename(path), 'class': cls, 'vendor': src.read(path + '/vendor').strip(), 'numa_node': src.read(path + '/numa_node').strip()})
    categories['system'].append(result('gpu_pcie', 'system', {'devices': pci}, backend='sysfs'))
    gpu_nodes = [d['numa_node'] for d in pci if d['class'].startswith('0x03') and d['numa_node'] not in ('', '-1')]
    nic_nodes = [d['numa_node'] for d in pci if d['class'].startswith('0x02') and d['numa_node'] not in ('', '-1')]
    metrics['gpu_nic_cross_numa'] = sum(a != b for a in gpu_nodes for b in nic_nodes) if gpu_nodes and nic_nodes else None
    numa_nodes = next(r['data']['numa'] for r in categories['memory'] if r['collector'] == 'memory_info')
    metrics['numa_miss_ratio'] = maximum(divide(n.get('numa_miss'), n.get('numa_hit', 0) + n.get('numa_miss', 0), 100) for n in numa_nodes.values())
    sysctls = enrich(src, cfg, first, last, metrics, categories, rate)
    restore_metrics(src, cfg, first, last, metrics, categories)
    src.errors = list({(e['source'], e['reason']): e for e in src.errors}.values())[:1000]
    for group in categories.values():
        group.sort(key=lambda r: r['collector'])
        for entry in group:
            entry.setdefault('start_time', first['timestamp'])
            entry.setdefault('end_time', last['timestamp'] if entry['backend'] == 'procfs' else utc())
            entry.setdefault('sample_count', (2 if tracing else samples) if entry['collector'] in ('cpu_utilization', 'memory_info', 'disk_stats', 'network_stats', 'process_info', 'container_info') else 1)
            if entry['collector'] in ('system_info', 'gpu_pcie'):
                entry.update(start_time=assembly_stamp, end_time=utc())
            if entry['backend'] == 'procfs':
                entry['missing_metrics'] = [e for e in src.errors if e['source'].startswith(src.proc)][:20]
                if entry['missing_metrics'] and entry['status'] == 'ok':
                    entry['status'] = 'partial'
    not_applicable = []
    if last['meminfo'].get('SwapTotal') == 0:
        not_applicable.append('swap_usage')
    if not last['cgroup']['version']:
        not_applicable += ['cpu_throttling', 'container_memory_usage']
    elif last['cgroup']['memory_limit_bytes'] is None:
        not_applicable.append('container_memory_usage')
    if os.path.isdir(src.sys + '/bus/pci/devices') and not any(d['class'].startswith('0x03') for d in pci):
        not_applicable.append('gpu_nic_cross_numa')
    metrics['cpu_saturation'] = max(0, (metrics['load_average'] - 1) * 100) if metrics['load_average'] is not None else None
    metrics['tcp_wait_sockets'] = metrics['tcp_timewait'] + metrics['tcp_close_wait'] if metrics['tcp_timewait'] is not None and metrics['tcp_close_wait'] is not None else None
    metrics['network_total_errors'] = int(metrics['network_interface_errors_total'] + metrics['tcp_retransmits']) if metrics['network_interface_errors_total'] is not None and metrics['tcp_retransmits'] is not None else None
    metrics['disk_in_flight'] = maximum(d['in_flight'] for d in disks)
    metrics['network_utilization'] = maximum(i.get('utilization_pct') for i in next(r['data']['interfaces'] for r in categories['network'] if r['collector'] == 'network_stats'))
    for name, _, _, _, _ in RULES:
        metrics.setdefault(name, None)
    summary = diagnose(metrics, not_applicable, sysctls, cfg, categories)
    if display:
        display.end('system_info')
        display.end('gpu_pcie')
    after = resource.getrusage(resource.RUSAGE_SELF)
    report = {'metadata': {'tool': 'linuxperf', 'version': VERSION, 'schema_version': SCHEMA, 'timestamp': stamp, 'hostname': os.uname().nodename, 'profile': cfg.profile, 'arch': os.uname().machine, 'cpus': os.cpu_count(), 'sample_interval': cfg.interval, 'focus': cfg.focus, 'clock_ticks': os.sysconf('SC_CLK_TCK'), 'page_size': os.sysconf('SC_PAGE_SIZE'), 'requested_duration': cfg.duration, 'actual_duration': time.monotonic() - start, 'sample_count': samples, 'missed_samples': missed_samples, 'boot_identity_available': bool(first['boot']), 'interrupted': bool(STOP), 'status': 'partial' if src.errors or STOP or summary['unchecked_rules'] or any(r['status'] != 'ok' for group in categories.values() for r in group) else 'ok', 'limitations': [], 'boot_id': first['boot'], 'scope': {'pid': cfg.pid, 'cgroup': cfg.cgroup, 'network_namespace': namespace_id(src, 'net'), 'pid_namespace': namespace_id(src, 'pid')}, 'baseline_window_seconds': elapsed, 'observer_active_samples': samples - 2 if tracing else 0, 'observed_window_seconds': observed_last['time'] - first['time'], 'capabilities': capability_probe(src, include_tools=False), 'observer_overhead': {'cpu_user_ms': (after.ru_utime - before.ru_utime) * 1000, 'cpu_system_ms': (after.ru_stime - before.ru_stime) * 1000, 'peak_rss_bytes': after.ru_maxrss * 1024, 'children_user_ms': (resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime - children_before.ru_utime) * 1000, 'children_system_ms': (resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime - children_before.ru_stime) * 1000, 'disk_read_bytes': delta_value(observer_before['io'].get('read_bytes'), pairs(src.p('self/io')).get('read_bytes')), 'disk_write_bytes': delta_value(observer_before['io'].get('write_bytes'), pairs(src.p('self/io')).get('write_bytes')), 'observer_pids': sorted(cfg.observer.pids), 'children_io': cfg.observer.io_totals(), 'context_switches': after.ru_nvcsw + after.ru_nivcsw - before.ru_nvcsw - before.ru_nivcsw}}, 'system': {'kernel': os.uname().release}, 'categories': categories, 'metrics': metrics, 'time_series': series[:3600], 'metric_specs': {name: metric_spec(name) for name in metrics}, 'summary': summary, 'source_errors': src.errors, 'ai_context': None}
    if cfg.ai_prompt:
        report['ai_context'] = build_ai_context(summary, cfg, elapsed, categories, report['metadata'])
    return report


def scale(value, factor):
    """Масштабирует известное значение, сохраняя пропуск.

    Параметры: value (число или None): значение; factor (число): множитель.
    Возвращает: Число или None.
    """
    return value * factor if value is not None else None


def maximum(values):
    """Находит максимум доступных значений.

    Параметры: values (Iterable): числа и None.
    Возвращает: Число или None, если все значения неизвестны.
    """
    values = [v for v in values if v is not None]
    return max(values) if values else None


def resolve_cgroup(src, path):
    """Преобразует видимый путь cgroup в путь членства относительно mount root.

    Параметры: src (Source): доступ к mountinfo; path (str): выбранный каталог cgroup.
    Возвращает: str: путь членства.
    Ошибки: ValueError, если путь вне видимых cgroup mounts.
    """
    target = os.path.realpath(path)
    for line in src.p('self/mountinfo').splitlines():
        f = line.split()
        if '-' not in f:
            continue
        sep = f.index('-')
        if f[sep + 1] not in ('cgroup', 'cgroup2'):
            continue
        mount = os.path.realpath(unescape_mount(f[4]))
        if target == mount or target.startswith(mount + '/'):
            return '/' + '/'.join(x for x in (unescape_mount(f[3]).strip('/'), os.path.relpath(target, mount).replace('.', '', 1) if target == mount else os.path.relpath(target, mount)) if x)
    raise ValueError('cgroup path is outside visible cgroup mounts')


def profiled_task(cfg, function, *args):
    """Выполняет задачу с необязательным учётом CPU-времени потока.

    Параметры: cfg (argparse.Namespace): настройки и хранилище профилей; function (Callable): задача; args (tuple): её аргументы.
    Возвращает: Результат задачи; профиль сохраняется и при исключении.
    Ошибки: исключения задачи передаются вызывающему коду.
    """
    if not getattr(cfg, 'self_profile', None):
        return function(*args)
    profiler = cProfile.Profile(timer=time.thread_time)
    try:
        return profiler.runcall(function, *args)
    finally:
        with cfg.profile_lock:
            cfg.thread_profiles.append(profiler)


def run_native_only(cfg, categories, deadline):
    """Добавляет результат native tcpretrans без запуска внешних команд.

    Параметры: cfg (argparse.Namespace): настройки/focus; categories (dict): изменяемые категории; deadline (float): монотонный дедлайн в секундах.
    Возвращает: None; результат добавляется в network, если эта категория выбрана.
    """
    if cfg.focus and 'network' not in cfg.focus:
        return
    entry = native_tcpretrans(cfg, min(deadline, time.monotonic() + tool_duration(cfg, 'tcpretrans')))
    categories['network'].append(entry)
    if progress(cfg):
        progress(cfg).end('tcpretrans', entry['status'], entry['reason'])


def classify_tool_error(data):
    """Классифицирует известные ошибки по коду и выводу утилиты.

    Параметры: data (dict): stdout, stderr, reason и returncode из command.
    Возвращает: tuple: причина и пояснение либо (None, None), если ошибка не распознана.
    """
    stderr = data.get('stderr', '')
    output = stderr + '\n' + data.get('stdout', '')
    lower = output.lower()
    build = re.search(r'chdir\((/lib/modules/[^)]+/build)\):[^\n]*(?:No such file|not found)', output)
    if build or 'unable to find kernel headers' in lower or 'kernel headers not found' in lower:
        path = build[1] if build else '/lib/modules/%s/build' % os.uname().release
        return 'missing_kernel_headers', 'BCC cannot compile: kernel build headers are missing at %s. Install development headers matching the running kernel; installing bcc alone is insufficient.' % path
    if data.get('reason') in ('command_failed', 'timeout') and any(term in lower for term in ('permission denied', 'operation not permitted', 'must be root', 'requires root')):
        return 'permission_denied', 'The tool was denied required kernel/BPF access. ' + tool_error_excerpt(stderr)
    if 'failed to compile bpf module' in lower or 'compilation failed' in lower:
        return 'bpf_compile_error', tool_error_excerpt(stderr)
    if data.get('reason') == 'command_failed' and any(term in lower for term in ('operation not supported', 'no stats available')):
        return 'unsupported', tool_error_excerpt(stderr)
    if 'failed to attach' in lower and "it's not traceable" in lower:
        symbol = re.search(r"to kprobe (?:b)?['\"]([^'\"]+)", output)
        return 'unsupported_probe', 'Installed BCC tool requests an unavailable kernel probe%s. Use a BCC tool version compatible with the running kernel. %s' % (
            ' (%s)' % symbol[1] if symbol else '', tool_error_excerpt(stderr))
    if any(term in lower for term in ('failed to attach', 'failed to load bpf')):
        return 'bpf_attach_error', tool_error_excerpt(stderr)
    if 'traceback (most recent call last)' in lower:
        return 'command_failed', tool_error_excerpt(stderr)
    if data.get('reason') == 'command_failed':
        return 'command_failed', tool_error_excerpt(stderr) or 'Command exited with code %s' % data.get('returncode')
    return None, None


def tool_error_excerpt(text):
    """Выбирает короткий диагностический фрагмент stderr.

    Параметры: text (str): исходный текст ошибки.
    Возвращает: str: последние содержательные строки, не более 500 символов.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    useful = [line for line in lines if not line.startswith(('Traceback ', 'File '))]
    return ' | '.join(useful[-3:])[:500]


def run_tools(cfg, categories, deadline):
    """Выполняет выбранные внешние/native сборщики через ограниченную очередь.

    Параметры: cfg (argparse.Namespace): профиль, фильтры и бюджеты; categories (dict): изменяемые категории; deadline (float): общий монотонный дедлайн.
    Возвращает: None; записи результатов и ошибок добавляются в categories. Ожидание в очереди расходует общий бюджет.
    """
    system_tools = ['ss', 'ethtool', 'nvidia-smi', 'dmesg', 'df']
    # Каждая BCC-утилита может запускать компилятор; обычный профиль ограничен.
    # Дорогие системные allocation/stack-трассировки доступны через deep.
    if cfg.profile == 'quick':
        selected = ['biolatency', 'tcpretrans', 'opensnoop', 'oomkill']
    elif cfg.profile == 'standard':
        selected = ['runqlat', 'biolatency', 'tcpretrans', 'oomkill']
    else:
        selected = [n for n in TOOLS if n not in system_tools]
    # OOM-события наблюдаем с первого слота: ожидание в очереди съело бы их окно.
    # Это приоритет, а не дополнительный worker сверх max_workers.
    selected.remove('oomkill')
    selected = ['oomkill'] + system_tools + selected

    def execute(name):
        category, args = TOOLS[name]
        native_failure = None
        if name == 'tcpretrans' and getattr(cfg, 'native_ebpf', 'auto') == 'auto' and not STOP and time.monotonic() < deadline:
            native = native_tcpretrans(cfg, min(deadline, time.monotonic() + tool_duration(cfg, name)))
            if native['status'] in ('ok', 'partial'):
                return native
            native_failure = native
            if progress(cfg):
                progress(cfg).log('  [tcpretrans/native] unavailable — %s: %s; trying external tool' % (native['reason'], '; '.join(native.get('errors', []))))
        path = trusted_tool(name)
        reason = 'missing_tool' if not path else 'budget_exhausted' if time.monotonic() >= deadline else 'interrupted' if STOP else None
        entry = result(name, category, None, backend='external', status='unavailable' if reason == 'missing_tool' else 'skipped', reason=reason)
        if cfg.cgroup:
            entry['filter_limitation'] = 'This external tool is not filtered by cgroup; process/cgroup metrics retain the target scope'
        if native_failure:
            entry['native_attempt'] = native_failure
        if reason:
            return entry
        if progress(cfg):
            progress(cfg).begin(name)
        remaining = max(.01, deadline - time.monotonic())
        # Непрерывный tracer завершаем по таймеру: аргумент длительности ему не нужен.
        # Запас на старт/выход даётся утилитам с собственным параметром длительности.
        continuous = name not in ('ss', 'df', 'ethtool', 'nvidia-smi', 'dmesg') and '{duration}' not in args
        budget = min(remaining, cfg.max_tool_seconds, tool_duration(cfg, name) + (0 if continuous else 5))
        callargs = [str(max(1, int(min(tool_duration(cfg, name), max(1, budget - 1))))) if a == '{duration}' else a for a in args]
        if cfg.pid and name in PID_TOOLS:
            callargs += ['-p', str(cfg.pid)]
        elif cfg.pid and name not in ('ss', 'ethtool', 'nvidia-smi', 'dmesg', 'df'):
            entry['filter_limitation'] = 'PID filtering is not supported by this tool'
        if name == 'ethtool':
            try:
                interfaces = sorted(os.listdir(os.path.join(cfg.sys_root, 'class/net')))
            except OSError as exc:
                entry.update(status='unavailable', reason='permission_denied' if exc.errno in (1, 13) else 'missing_source')
                return entry
            outputs = {}
            output_remaining = min(cfg.max_tool_output, 12 * 1024 * 1024 // len(selected))
            skipped = 0
            for interface in interfaces:
                if interface == 'lo':
                    continue
                if STOP or time.monotonic() >= deadline or output_remaining <= 0:
                    skipped += 1
                    continue
                outputs[interface] = {}
                for flag in ('-i', '-g', '-k', '-c', '-S'):
                    remaining = min(budget / 5, deadline - time.monotonic())
                    if remaining <= 0 or STOP or output_remaining <= 0:
                        break
                    try:
                        outputs[interface][flag] = command(path, [flag, interface], remaining, min(output_remaining, 65536), tracker=getattr(cfg, 'observer', None))
                        failure, explanation = classify_tool_error(outputs[interface][flag])
                        if failure:
                            outputs[interface][flag]['reason'] = failure
                        output_remaining -= len(outputs[interface][flag].get('stdout', '').encode('utf-8')) + len(outputs[interface][flag].get('stderr', '').encode('utf-8'))
                    except OSError as exc:
                        outputs[interface][flag] = {'reason': str(exc), 'stdout': '', 'stderr': ''}
            incomplete = skipped > 0 or any(len(group) < 5 or any(v['reason'] for v in group.values()) for group in outputs.values())
            failures = [v for group in outputs.values() for v in group.values() if v['reason']]
            unsupported = sum(v['reason'] == 'unsupported' for v in failures)
            reason = 'budget_exhausted' if skipped or output_remaining <= 0 else 'unsupported' if failures and unsupported == len(failures) else None
            entry.update(data=outputs, status='partial' if incomplete else 'ok', reason=reason, truncated=skipped > 0 or output_remaining <= 0, skipped_interfaces=skipped)
            if failures:
                entry['errors'] = ['Driver queries: %d unsupported, %d failed; per-interface stderr is saved in the report.' % (unsupported, len(failures) - unsupported)]
            return entry
        begin = utc()
        try:
            data = command(path, callargs, budget, min(cfg.max_tool_output, max(1024, 12 * 1024 * 1024 // len(selected))), tracker=getattr(cfg, 'observer', None), stop_signal=signal.SIGINT if name not in ('ss', 'df', 'ethtool', 'nvidia-smi', 'dmesg') else signal.SIGTERM)
            failure, explanation = classify_tool_error(data)
            if failure:
                data['reason'] = failure
                entry['errors'] = [explanation]
            planned_stop = data['reason'] == 'timeout' and continuous and budget >= tool_duration(cfg, name)
            ready = bool(re.search(r'(?im)^\s*(Tracing\b|TIME\S*\s+|PID\s+|COMM\s+)', data['stdout']))
            if planned_stop and ready and data['returncode'] in (0, -signal.SIGINT):
                data['reason'] = None
                data['window_complete'] = True
                data['completion'] = 'observation_window_elapsed'
            observer = getattr(cfg, 'observer', None)
            parsed = parse_tool(data['stdout'], cfg.max_events, name,
                                exclude_pid=observer.is_observer if observer else None)
            normalize_events(name, parsed)
            if observer:
                original_count = len(parsed['events'])
                parsed['events'] = [event for event in parsed['events'] if not (event.get('pid') and observer.is_observer(event['pid']))]
                parsed['observer_events_excluded'] += original_count - len(parsed['events'])
                group_field = 'daddr' if name.startswith(('tcp', 'udp')) else 'filename' if name in ('opensnoop', 'fileslower', 'filelife', 'statsnoop') else 'disk' if name in ('biosnoop', 'biotop') else 'comm'
                parsed['aggregation'] = aggregate_events(parsed['events'], group_field)
            entry.update(parsed)
            if len(data['stdout']) > 16384:
                data['stdout'] = data['stdout'][:16384]
                data['raw_truncated'] = True
            if data['reason'] is None and not parsed['parsed'] and name in HISTOGRAM_TOOLS | STACK_TOOLS:
                data['reason'] = 'parse_error'
            if data['reason'] is None and (parsed['truncated'] or data['truncated']):
                data['reason'] = 'result_limit' if parsed['truncated'] else 'budget_exhausted'
                entry.setdefault('errors', []).append('Collected output reached a configured limit; see truncated fields and --max-events/--max-tool-output.')
            entry.update(data=data, status='partial' if parsed['truncated'] else 'ok' if data['reason'] is None else 'partial', reason=data['reason'], start_time=begin, end_time=utc())
        except OSError as exc:
            entry.update(status='error', reason=str(exc))
        return entry

    def run(name):
        entry = execute(name)
        if progress(cfg):
            progress(cfg).end(name, entry['status'], entry['reason'])
            if entry.get('errors'):
                progress(cfg).log('  [%s] %s' % (name, ' '.join(entry['errors'][0].split())[:500]))
        return entry

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        futures = [(name, pool.submit(profiled_task, cfg, run, name)) for name in selected if not cfg.focus or TOOLS[name][0] in cfg.focus or TOOLS[name][0] == 'system']
        for name, future in futures:
            try:
                entry = future.result()
            except Exception as exc:
                logging.exception('External collector %s failed', name)
                if progress(cfg):
                    progress(cfg).end(name, 'error', str(exc))
                entry = result(name, TOOLS[name][0], None, backend='external', status='error', reason=str(exc))
            categories[entry['category']].append(entry)


def write_json(value, path, compact=False):
    """Сериализует отчёт без нечисловых float и записывает его.

    Параметры: value (object): JSON-совместимые данные; path (str): файл или «-» для stdout; compact (bool): убрать пробелы форматирования.
    Возвращает: None.
    Ошибки: ValueError при NaN/Infinity или превышении 32 MiB; TypeError для несовместимых объектов; OSError при записи.
    """
    data = json.dumps(value, ensure_ascii=True, allow_nan=False, indent=None if compact else 2, separators=(',', ':') if compact else None) + '\n'
    if len(data.encode()) > 32 * 1024 * 1024:
        raise ValueError('report exceeds 32 MiB budget')
    write_text(data, path)


def write_text(data, path):
    """Записывает UTF-8 текст атомарной заменой файла либо в stdout.

    Параметры: data (str): текст; path (str): файл или «-».
    Возвращает: None; для файла используется временный файл в той же директории.
    Ошибки: OSError при создании, синхронизации или замене файла.
    """
    if path == '-':
        sys.stdout.write(data)
        return
    fd, tmp = tempfile.mkstemp(prefix='.linuxperf-', dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def reject_json_constant(value):
    """Отклоняет нестандартные числовые константы JSON.

    Параметры: value (str): NaN или Infinity, переданные JSON-декодером.
    Возвращает: Не возвращает значение.
    Ошибки: всегда ValueError.
    """
    raise ValueError('Non-finite JSON constant: ' + value)


def load_report(path):
    """Читает JSON и проверяет базовую структуру отчёта linuxperf.

    Параметры: path (str): путь к входному файлу.
    Возвращает: dict: отчёт поддерживаемой схемы.
    Ошибки: OSError при чтении; ValueError при превышении бюджета, неверной схеме/JSON/метриках.
    """
    with open(path, encoding='utf-8') as stream:
        data = stream.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024:
        raise ValueError('input exceeds budget')
    report = json.loads(data, parse_constant=reject_json_constant)
    if not isinstance(report, dict) or report.get('metadata', {}).get('schema_version') != SCHEMA:
        raise ValueError('unsupported report schema')
    for key in ('metadata', 'metrics', 'summary', 'categories', 'metric_specs'):
        if not isinstance(report.get(key), dict):
            raise ValueError('invalid report: expected object ' + key)
    if any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in report['metrics'].values()):
        raise ValueError('invalid numeric metric')
    return report


def diff_reports(a, b):
    """Сравнивает совместимые измерения двух отчётов.

    Параметры: a, b (dict): исходный и новый отчёты после load_report.
    Возвращает: dict: изменения, сопоставимость, регрессии, coverage и изменения аномалий; пропуски не заменяются нулями.
    """
    changes, warnings = [], []
    am, bm = a.get('metadata', {}), b.get('metadata', {})
    for key in ('hostname', 'boot_id', 'profile', 'scope'):
        if am.get(key) != bm.get(key):
            warnings.append('Different ' + key)
    score_same = a['summary'].get('score_version') == b['summary'].get('score_version')
    if not score_same:
        warnings.append('Different score versions; health scores are not comparable')
    inventory_a, inventory_b = compare_inventory(a), compare_inventory(b)
    for key in sorted(set(inventory_a) | set(inventory_b)):
        old, new = inventory_a.get(key), inventory_b.get(key)
        spec_a, spec_b = a.get('metric_specs', {}).get(key), b.get('metric_specs', {}).get(key)
        reason = 'missing_metric' if old is None or new is None else 'different_metric_spec' if spec_a != spec_b else 'different_host_or_scope' if am.get('hostname') != bm.get('hostname') or am.get('scope') != bm.get('scope') else None
        if am.get('boot_id') != bm.get('boot_id') and spec_a and spec_a.get('method') == 'counter':
            reason = 'different_boot'
        if key.startswith('use.') and not score_same:
            reason = 'different_score_version'
        comparable = reason is None
        changes.append({'metric': key, 'before': old, 'after': new, 'comparable': comparable, 'reason': reason, 'delta': new - old if comparable else None, 'percent_change': (new - old) / abs(old) * 100 if comparable and old else None})
    regressions, improvements = classify_changes(changes)
    anomalies_a = {x['metric'] for x in a['summary'].get('anomalies', [])}
    anomalies_b = {x['metric'] for x in b['summary'].get('anomalies', [])}
    checked = set(b['summary'].get('unchecked_rules', []))
    anomaly_comparable = am.get('hostname') == bm.get('hostname') and am.get('scope') == bm.get('scope')
    if not anomaly_comparable:
        checked |= anomalies_a
    return {'regressions': regressions, 'improvements': improvements, 'anomaly_comparison_comparable': anomaly_comparable, 'anomalies_added': sorted(anomalies_b - anomalies_a) if anomaly_comparable else [], 'anomalies_resolved': sorted(anomalies_a - anomalies_b - checked), 'anomalies_unverified': sorted((anomalies_a - anomalies_b) & checked), 'changes': changes, 'coverage_before': a['summary'].get('coverage'), 'coverage_after': b['summary'].get('coverage'), 'warnings': warnings, 'health_score_delta': b['summary']['health_score'] - a['summary']['health_score'] if score_same and not warnings and a['summary'].get('health_score') is not None and b['summary'].get('health_score') is not None else None}


def export(report, fmt, collector=None):
    """Формирует автономный HTML либо представление собранных стеков.

    Параметры: report (dict): отчёт; fmt (str): html, folded или flamegraph; collector (str или None): фильтр сборщика стеков.
    Возвращает: str: документ.
    Ошибки: ValueError при отсутствии стеков, неверных весах или смешении единиц стеков.
    """
    if fmt == 'html':
        return '<!doctype html><meta charset="utf-8"><title>linuxperf report</title><style>body{max-width:1000px;margin:2em auto;font:16px sans-serif}pre{white-space:pre-wrap}</style><h1>linuxperf</h1><pre>' + html.escape(json.dumps(report, indent=2)) + '</pre>\n'
    stacks = [s for group in report['categories'].values() for r in group if collector is None or r['collector'] == collector for s in r.get('stacks', [])]
    if not stacks:
        raise ValueError('no stack samples available')
    if any(type(s.get('count')) is not int or s['count'] <= 0 or not isinstance(s.get('stack'), str) for s in stacks):
        raise ValueError('invalid stack sample')
    if len({s.get('unit', 'samples') for s in stacks}) > 1:
        raise ValueError('mixed stack weight units; select one --collector')
    if fmt == 'folded':
        return ''.join(s['stack'] + ' ' + str(s['count']) + '\n' for s in stacks)
    total = sum(s['count'] for s in stacks)
    root = {'children': {}, 'count': total}
    depth = 0
    for sample in stacks:
        node = root
        frames = sample['stack'].split(';')[:128]
        depth = max(depth, len(frames))
        for frame in frames:
            node = node['children'].setdefault(frame, {'children': {}, 'count': 0})
            node['count'] += sample['count']
    height = 24 * (depth + 1)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="%d">' % height]
    work = [(root, 0., 0)]
    while work:
        node, offset, level = work.pop()
        for frame, child in sorted(node['children'].items()):
            width = child['count'] / total * 1200
            y = height - (level + 1) * 24
            svg.append('<g><title>%s: %d</title><rect x="%f" y="%d" width="%f" height="23" fill="#ef9840" stroke="white"/><text x="%f" y="%d" font-size="10">%s</text></g>' % (html.escape(frame), child['count'], offset, y, width, offset + 2, y + 15, html.escape(frame[:int(width / 7)])))
            work.append((child, offset, level + 1))
            offset += width
    return ''.join(svg) + '</svg>\n'


def duration(value):
    """Разбирает положительную длительность CLI в секунды.

    Параметры: value (str): число с необязательным суффиксом ms, s или m.
    Возвращает: float: секунды в диапазоне (0, 3600].
    Ошибки: argparse.ArgumentTypeError при неверном формате или диапазоне.
    """
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s|m)?', value)
    if not match:
        raise argparse.ArgumentTypeError('expected positive duration: 10s, 1m, 500ms')
    number = float(match[1]) * {'ms': .001, 's': 1, 'm': 60, None: 1}[match[2]]
    if not 0 < number <= 3600:
        raise argparse.ArgumentTypeError('duration must be >0 and <=3600s')
    return number


def parser():
    """Создаёт описание подкоманд и аргументов CLI.

    Возвращает: argparse.ArgumentParser; разбор и запуск команд здесь не выполняются.
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', action='version', version=VERSION)
    subs = p.add_subparsers(dest='command', required=True)
    c = subs.add_parser('collect')
    c.add_argument('--profile', choices=['quick', 'standard', 'deep'], default='standard')
    c.add_argument('--duration', type=duration)
    c.add_argument('--interval', type=duration, default=1.)
    c.add_argument('--external-tools', choices=['auto', 'off'], default='auto')
    c.add_argument('--focus', type=lambda x: x.split(','), default=[])
    c.add_argument('--pid', type=int)
    c.add_argument('--cgroup')
    c.add_argument('--top', type=int, default=20)
    c.add_argument('--max-events', type=int, default=1000)
    c.add_argument('--proc-root', default='/proc')
    c.add_argument('--sys-root', default='/sys')
    c.add_argument('--etc-root', default='/etc')
    c.add_argument('--max-workers', type=int, default=2, help='Maximum concurrent external collectors (default: 2)')
    c.add_argument('--max-tool-seconds', type=duration, default=120.)
    c.add_argument('--max-tool-output', type=int, default=8 * 1024 * 1024)
    c.add_argument('--native-ebpf', choices=['auto', 'off'], default='auto')
    c.add_argument('--self-profile', '--pprof', dest='self_profile', help='Write cProfile statistics for this run')
    c.add_argument('--ai-prompt', action='store_true', help='Write a separate .prompt.txt file and compact JSON; stdout reports use report.prompt.txt in the current directory')
    c.add_argument('--compact', action='store_true', help='Write JSON without indentation; preserve all report data')
    c.add_argument('-q', '--quiet', action='store_true', help='Suppress progress and terminal summary')
    c.add_argument('-v', '--verbose', action='store_true')
    c.add_argument('-o', '--output', default='-')
    install = subs.add_parser('install', help='Explicitly install system diagnostic tools; never invoked by collect')
    install.add_argument('--dry-run', action='store_true')
    share = subs.add_parser('share', help='Create offline report URL or upload to an explicitly selected service')
    share.add_argument('report')
    share.add_argument('--api-url')
    share.add_argument('--token')
    serve = subs.add_parser('serve-reports', help='Run a local report-sharing service')
    serve.add_argument('--bind', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8787)
    serve.add_argument('--public-url')
    serve.add_argument('--token')
    serve.add_argument('--storage', default='linuxperf-reports.sqlite')
    serve.add_argument('--ttl', type=int, default=604800)
    share.add_argument('--offline', action='store_true')
    share.add_argument('--timeout', type=duration, default=10.)
    share.add_argument('-o', '--output', default='-')
    subs.add_parser('capabilities')
    subs.add_parser('mcp')
    d = subs.add_parser('diff')
    d.add_argument('baseline')
    d.add_argument('current')
    d.add_argument('-o', '--output', default='-')
    e = subs.add_parser('export')
    e.add_argument('report')
    e.add_argument('--collector', help='Select stack collector for folded/SVG export')
    e.add_argument('--format', choices=['html', 'folded', 'flamegraph'], default='html')
    e.add_argument('-o', '--output', default='-')
    return p


def prepare(cfg):
    """Проверяет параметры сбора и задаёт длительность профиля.

    Параметры: cfg (argparse.Namespace): аргументы collect; изменяется на месте.
    Возвращает: argparse.Namespace: cfg с нормализованным focus и признаком duration_overridden.
    Ошибки: ValueError для неверных PID, лимитов, focus или соотношения interval/duration.
    """
    cfg.duration_overridden = cfg.duration is not None
    if cfg.duration is None:
        cfg.duration = {'quick': 10, 'standard': 30, 'deep': 60}[cfg.profile]
    if cfg.top < 1 or cfg.top > 1000 or cfg.max_events < 1 or cfg.max_events > 100000 or (cfg.pid is not None and not 1 <= cfg.pid <= 2147483647):
        raise ValueError('invalid pid/top/max-events')
    if set(cfg.focus) - {'cpu', 'memory', 'disk', 'network', 'process', 'container', 'system', 'stacks', 'stacktrace'}:
        raise ValueError('unknown focus area')
    cfg.focus = ['stacktrace' if x == 'stacks' else x for x in cfg.focus]
    if not 1 <= cfg.max_workers <= 128 or not 1024 <= cfg.max_tool_output <= 8 * 1024 * 1024:
        raise ValueError('max-workers must be 1..128; max-tool-output must be 1024..8388608')
    if cfg.interval >= cfg.duration:
        raise ValueError('interval must be smaller than duration')
    return cfg


def handle_signal(number, frame):
    """Отмечает остановку сбора, а повторный сигнал завершает процесс.

    Параметры: number (int): номер сигнала; frame (FrameType или None): контекст обработчика.
    Возвращает: None при первом сигнале; повторный вызывает os._exit без обычного cleanup.
    """
    global STOP
    if STOP:
        os._exit(128 + number)
    STOP = number


MCP_VERSION = '2024-11-05'


def mcp_worker(connection, name, arguments):
    """Исполняет MCP-задачу в отдельном процессе и отвечает через канал.

    Параметры: connection (multiprocessing.connection.Connection): канал ответа; name (str): инструмент; arguments (dict): аргументы.
    Возвращает: None; результат или описание ошибки отправляется в канал, затем канал закрывается.
    """
    global STOP
    STOP = 0
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, handle_signal)
        argv = ['collect', '--profile', arguments.get('profile', 'quick')]
        if name == 'get_health':
            argv += ['--external-tools', 'off', '--native-ebpf', 'off', '--duration', '2s']
        for key in ('pid', 'focus'):
            if key in arguments:
                argv += ['--' + key, str(arguments[key])]
        cfg = prepare(parser().parse_args(argv))
        data = collect(cfg)
        if not STOP:
            encoded = json.dumps(data['summary'] if name == 'get_health' else data, allow_nan=False)
            if len(encoded.encode('utf-8')) > 32 * 1024 * 1024:
                raise ValueError('report exceeds 32 MiB budget')
            connection.send({'content': [{'type': 'text', 'text': encoded}], 'isError': False})
    except (Exception, SystemExit) as exc:
        connection.send({'content': [{'type': 'text', 'text': str(exc)}], 'isError': True})
    finally:
        connection.close()


def mcp():
    """Обслуживает stdio JSON-RPC с отменой длительного сбора.

    Возвращает: None после EOF/остановки; JSON-ответы идут в stdout, сбор выполняется отдельным worker-процессом.
    """
    tools = [
        {'name': 'get_health', 'description': 'Collect baseline health without external commands', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        {'name': 'collect_metrics', 'description': 'Collect Linux performance metrics', 'inputSchema': {'type': 'object', 'properties': {'profile': {'type': 'string', 'enum': ['quick', 'standard', 'deep']}, 'pid': {'type': 'integer', 'minimum': 1}, 'focus': {'type': 'string'}}, 'additionalProperties': False}},
        {'name': 'list_anomalies', 'description': 'List all anomaly rules and evidence requirements', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        {'name': 'explain_anomaly', 'description': 'Explain a metric, thresholds and recommendations', 'inputSchema': {'type': 'object', 'properties': {'anomaly_id': {'type': 'string'}}, 'required': ['anomaly_id'], 'additionalProperties': False}},
    ]
    initialized, ready, pending, buffer = False, False, {}, bytearray()
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
    context = multiprocessing.get_context('fork')

    def send(ident, value=None, error=None):
        message = {'jsonrpc': '2.0', 'id': ident}
        message['error' if error else 'result'] = error if error else value
        sys.stdout.write(json.dumps(message, allow_nan=False) + '\n')
        sys.stdout.flush()

    def cancel(ident):
        item = pending.pop(ident, None)
        if item:
            worker, pipe = item
            if worker.is_alive():
                worker.terminate()
            worker.join(.5)
            if worker.is_alive():
                worker.kill()
                worker.join(.2)
            pipe.close()

    def handle(request):
        nonlocal initialized, ready
        if not isinstance(request, dict) or request.get('jsonrpc') != '2.0' or not isinstance(request.get('method'), str):
            send(None, error={'code': -32600, 'message': 'Invalid JSON-RPC request'})
            return
        method, ident = request['method'], request.get('id')
        if ident is not None and (isinstance(ident, bool) or not isinstance(ident, (str, int))):
            send(None, error={'code': -32600, 'message': 'Invalid request ID'})
            return
        params = request.get('params', {})
        if not isinstance(params, dict):
            if 'id' in request:
                send(ident, error={'code': -32602, 'message': 'params must be an object'})
            return
        if method == 'notifications/cancelled':
            request_id = params.get('requestId')
            if isinstance(request_id, (str, int)) and not isinstance(request_id, bool):
                cancel(request_id)
            return
        if method == 'notifications/initialized':
            ready = initialized
            return
        if method.startswith('notifications/') or 'id' not in request:
            return
        if ident in pending:
            send(ident, error={'code': -32600, 'message': 'Duplicate in-flight ID'})
            return
        if method == 'initialize':
            if initialized:
                send(ident, error={'code': -32600, 'message': 'Already initialized'})
            else:
                initialized = True
                send(ident, {'protocolVersion': MCP_VERSION, 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'linuxperf', 'version': VERSION}})
            return
        if method == 'ping':
            send(ident, {})
            return
        if not ready:
            send(ident, error={'code': -32002, 'message': 'Complete initialize/notifications/initialized first'})
            return
        if method == 'tools/list':
            send(ident, {'tools': tools})
            return
        if method != 'tools/call':
            send(ident, error={'code': -32601, 'message': 'Method not found'})
            return
        name, arguments = params.get('name'), params.get('arguments', {})
        if not isinstance(arguments, dict) or not isinstance(name, str) or name not in {t['name'] for t in tools}:
            send(ident, error={'code': -32602, 'message': 'Unknown tool or invalid arguments'})
            return
        allowed = next(t['inputSchema']['properties'] for t in tools if t['name'] == name)
        if set(arguments) - set(allowed) or ('pid' in arguments and (type(arguments['pid']) is not int or arguments['pid'] < 1)) or ('profile' in arguments and arguments['profile'] not in ('quick', 'standard', 'deep')) or any(not isinstance(arguments[k], str) for k in ('focus', 'anomaly_id') if k in arguments):
            send(ident, error={'code': -32602, 'message': 'Invalid tool arguments'})
            return
        if name == 'list_anomalies':
            data = [{'metric': r[0], 'category': r[1], 'warning': r[2], 'critical': r[3], **metric_spec(r[0])} for r in RULES]
        elif name == 'explain_anomaly':
            metric = arguments.get('anomaly_id')
            if metric not in ADVICE:
                send(ident, error={'code': -32602, 'message': 'Unknown anomaly_id'})
                return
            data = {'metric': metric, 'rule': next(r for r in RULES if r[0] == metric), 'spec': metric_spec(metric), 'title': ADVICE[metric][0], 'explanation': ADVICE[metric][1], 'commands': ADVICE[metric][2], 'assumptions': ADVICE[metric][3]}
        else:
            if pending:
                send(ident, error={'code': -32000, 'message': 'Another collection is active'})
                return
            receiver, sender = context.Pipe(duplex=False)
            worker = context.Process(target=mcp_worker, args=(sender, name, arguments))
            worker.start()
            sender.close()
            pending[ident] = (worker, receiver)
            return
        send(ident, {'content': [{'type': 'text', 'text': json.dumps(data, allow_nan=False)}], 'isError': False})

    try:
        eof = False
        while not STOP and not eof:
            for key, _ in selector.select(.05):
                block = os.read(key.fd, 65536)
                if not block:
                    if buffer.strip():
                        send(None, error={'code': -32700, 'message': 'Unterminated message'})
                    eof = True
                    break
                buffer.extend(block)
                if len(buffer) > 1024 * 1024 and b'\n' not in buffer:
                    send(None, error={'code': -32600, 'message': 'Input size limit exceeded'})
                    eof = True
                    break
                while b'\n' in buffer:
                    line, _, rest = buffer.partition(b'\n')
                    buffer = bytearray(rest)
                    if len(line) > 1024 * 1024:
                        send(None, error={'code': -32600, 'message': 'Input size limit exceeded'})
                        continue
                    try:
                        request = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        send(None, error={'code': -32700, 'message': 'Parse error'})
                        continue
                    handle(request)
            for ident, (worker, pipe) in list(pending.items()):
                if pipe.poll():
                    try:
                        value = pipe.recv()
                    except EOFError:
                        value = {'content': [{'type': 'text', 'text': 'Collection worker exited'}], 'isError': True}
                    send(ident, value)
                    worker.join(.1)
                    pipe.close()
                    del pending[ident]
    finally:
        selector.close()
        for ident in list(pending):
            cancel(ident)


def main(argv=None):
    """Разбирает CLI, запускает команду и сохраняет её результаты.

    Параметры: argv (list[str] или None): аргументы без имени программы; None использует sys.argv.
    Возвращает: int: код завершения команды.
    Ошибки: SystemExit при ошибках argparse/help; OSError и ValueError внутри команды преобразуются в код 1.
    """
    cfg = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if getattr(cfg, 'verbose', False) else logging.WARNING)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_signal)
    try:
        if cfg.command == 'collect':
            try:
                cfg = prepare(cfg)
            except ValueError as exc:
                parser().error(str(exc))
            cfg.progress = Progress(quiet=cfg.quiet, verbose=cfg.verbose)
            if cfg.self_profile:
                cfg.thread_profiles = []
                cfg.profile_lock = threading.Lock()
                profiler = cProfile.Profile(timer=time.thread_time)
                report = profiler.runcall(collect, cfg)
                combined = pstats.Stats(profiler)
                for worker_profile in cfg.thread_profiles:
                    combined.add(worker_profile)
                combined.dump_stats(cfg.self_profile)
            else:
                report = collect(cfg)
            if cfg.ai_prompt:
                context = report.pop('ai_context')
                prompt_path = 'report.prompt.txt' if cfg.output == '-' else os.path.splitext(cfg.output)[0] + '.prompt.txt'
                report_name = 'the JSON report supplied with this prompt' if cfg.output == '-' else json.dumps(os.path.basename(cfg.output))
                write_text('Analyze %s. Attach the complete JSON report together with this instruction.\n\n%s\n' %
                           (report_name, context['prompt']), prompt_path)
                cfg.progress.log('AI prompt saved to %s; use it together with the JSON report.' % prompt_path)
            write_json(report, cfg.output, compact=cfg.compact or cfg.ai_prompt)
            cfg.progress.summary(report, cfg.output)
            return (128 + STOP) if STOP else (0 if any(v is not None for v in report['metrics'].values()) else 1)
        if cfg.command == 'install':
            installed = install_tools(cfg.dry_run)
            write_json(installed, '-')
            if installed.get('status') == 'partial':
                return 1
        elif cfg.command == 'share':
            write_text(share_report(load_report(cfg.report), None if cfg.offline else cfg.api_url, cfg.timeout, cfg.token) + '\n', cfg.output)
        elif cfg.command == 'serve-reports':
            serve_reports(cfg)
        elif cfg.command == 'capabilities':
            write_json(capability_probe(Source()), '-')
        elif cfg.command == 'diff':
            write_json(diff_reports(load_report(cfg.baseline), load_report(cfg.current)), cfg.output)
        elif cfg.command == 'export':
            write_text(export(load_report(cfg.report), cfg.format, cfg.collector), cfg.output)
        elif cfg.command == 'mcp':
            mcp()
        return 0
    except (OSError, ValueError) as exc:
        logging.error('%s', exc)
        return 1


def sample_summary(a, b, observer_active):
    """Формирует компактную точку временного ряда между снимками.

    Параметры: a, b (dict): последовательные снимки; observer_active (bool): активны ли трассировки.
    Возвращает: dict: время, CPU, доступная память и причина неизвестного CPU при смене boot/reset.
    """
    before, after = a['stat'].get('cpu'), b['stat'].get('cpu')
    value = None
    reason = None
    if before and after and len(before) == len(after):
        changes = [y - x for x, y in zip(before, after)]
        if any(v < 0 for v in changes) or a['boot'] != b['boot']:
            reason = 'counter_reset'
        elif sum(changes):
            value = 100 * (sum(changes) - changes[3]) / sum(changes)
    return {'timestamp': b['timestamp'], 'elapsed_seconds': b['time'] - a['time'], 'cpu_utilization': value,
            'memory_available_kib': b['meminfo'].get('MemAvailable'), 'observer_active': observer_active, 'reason': reason}


def delta_value(a, b):
    """Вычисляет неотрицательный прирост счётчика.

    Параметры: a, b (число или None): значения до и после.
    Возвращает: Число или None при неизвестных значениях либо сбросе.
    """
    return b - a if a is not None and b is not None and b >= a else None


def namespace_id(src, kind):
    """Читает идентификатор namespace текущего процесса.

    Параметры: src (Source): корень procfs; kind (str): имя namespace, например net.
    Возвращает: str или None при недоступной символьной ссылке.
    """
    try:
        return os.readlink(src.proc + '/self/ns/' + kind)
    except OSError:
        return None


def capability_probe(src, include_tools=True):
    """Описывает доступные источники и кандидатов backend-ов.

    Параметры: src (Source): корни файловых систем; include_tools (bool): искать внешние команды.
    Возвращает: dict: доступность источников и native-возможности; загрузка BPF не проверяется.
    """
    sources = {}
    for category, path in [('cpu', 'stat'), ('memory', 'meminfo'), ('disk', 'diskstats'), ('network', 'net/dev'), ('process', 'self/stat'), ('cgroup', 'self/cgroup'), ('psi', 'pressure/cpu')]:
        try:
            with open(os.path.join(src.proc, path), 'rb') as stream:
                stream.read(1)
            sources[category] = {'status': 'available', 'source': path}
        except OSError as exc:
            sources[category] = {'status': 'unavailable', 'source': path, 'reason': 'permission_denied' if exc.errno in (1, 13) else 'missing_source'}
    value = {'python': sys.version.split()[0], 'sources': sources, 'native_ebpf': native_capability(), 'external_tools_default': 'auto'}
    if include_tools:
        value['tools'] = {name: {'path': trusted_tool(name), 'status': 'discovered' if trusted_tool(name) else 'missing_tool', 'note': 'Runtime permissions and kernel support are checked on execution'} for name in TOOLS}
    return value


# Рекомендации опираются на evidence; команды являются текстом и не выполняются.
ADVICE = {
 'cpu_utilization': ('CPU saturation', 'Identify CPU consumers and check quota/steal before increasing parallelism.', ['python3 linuxperf.py collect --profile deep --focus stacks'], 'high CPU can be caused by useful work or contention'),
 'cpu_iowait': ('CPU waiting for IO', 'Correlate blocked tasks with device latency and IO pressure.', ['cat /proc/pressure/io'], 'iowait does not identify a particular device'),
 'load_average': ('Runnable or blocked workload exceeds CPU capacity', 'Inspect runnable and uninterruptible tasks; account for cgroup CPU limits.', ['cat /proc/loadavg'], 'load includes tasks blocked in uninterruptible sleep'),
 'memory_utilization': ('Memory working set is close to capacity', 'Check workload RSS, cgroup limits, cache and reclaim before resizing.', ['cat /proc/meminfo'], 'high allocation is not by itself a memory leak'),
 'swap_usage': ('Swap allocation', 'Check current swap-in/out rates and workload latency before adjusting swappiness.', ['cat /proc/vmstat'], 'allocated swap may belong to cold inactive pages'),
 'memory_psi_pressure': ('Memory stalls', 'Correlate reclaim and swap activity with container memory limits.', ['cat /proc/pressure/memory'], 'pressure can reflect a transient working-set expansion'),
 'direct_reclaim_rate': ('Direct reclaim', 'Inspect working-set growth and free reserves; consider watermark reserves after measuring.', ['cat /proc/sys/vm/watermark_scale_factor'], 'larger reserves reduce memory available to applications'),
 'compaction_stall_rate': ('Memory compaction stalls', 'Check fragmentation and THP policy; consider deferred compaction for latency-sensitive workloads.', ['cat /sys/kernel/mm/transparent_hugepage/defrag'], 'changing THP policy can affect throughput'),
 'thp_split_rate': ('THP splitting', 'Check THP allocation policy and workload mappings; evaluate madvise for targeted huge pages.', ['cat /sys/kernel/mm/transparent_hugepage/enabled'], 'THP tuning is application-dependent'),
 'numa_miss_ratio': ('Remote NUMA allocation', 'Align workload CPU affinity, memory policy and device locality.', ['cat /sys/devices/system/node/node*/numastat'], 'cumulative ratio describes allocation history, not current access latency'),
 'tcp_retransmits': ('TCP retransmissions', 'Check loss, RTT, MTU and peer saturation; correlate interface and TCP counters.', ['cat /proc/net/netstat'], 'retransmissions do not prove a local NIC problem'),
 'tcp_timewait': ('Many TIME_WAIT sockets', 'Check connection churn and ephemeral port pressure; prefer connection reuse.', ['cat /proc/sys/net/ipv4/ip_local_port_range'], 'TIME_WAIT is a normal TCP lifecycle state'),
 'disk_utilization': ('Device busy time', 'Inspect throughput, queue and latency; identify physical versus layered devices.', ['cat /proc/diskstats'], 'busy time is not a capacity percentage for all parallel devices'),
 'cpu_throttling': ('Cgroup CPU throttling', 'Compare CPU demand, quota and cpuset; adjust workload concurrency or provision capacity.', ['cat /proc/self/cgroup'], 'throttled duration can exceed wall time across CPUs'),
 'container_memory_usage': ('Cgroup memory near limit', 'Inspect memory.events and workload working set; provide headroom or reduce usage.', ['cat /proc/self/cgroup'], 'raising a limit may expose the host to memory exhaustion'),
 'biolatency_p99_ssd': ('SSD block IO tail latency', 'Correlate per-device queues, writeback, discard and workload bursts.', ['cat /proc/diskstats'], 'percentile is estimated from histogram bucket bounds'),
 'biolatency_p99_hdd': ('HDD block IO tail latency', 'Check random IO, queue depth, RAID state and workload concurrency.', ['cat /proc/diskstats'], 'seek-heavy workloads may require different storage'),
 'runqlat_p99': ('Scheduler queue latency', 'Inspect CPU saturation, affinity and quotas; check noisy neighbors.', ['cat /proc/pressure/cpu'], 'histogram estimate requires sufficient observations'),
 'dns_latency_p99': ('Slow name resolution', 'Check resolver configuration, caching and upstream reachability.', ['cat /etc/resolv.conf'], 'sampled calls may not represent all DNS traffic'),
 'cache_miss_ratio': ('Page-cache misses', 'Correlate misses with IO and working set; check file access patterns.', ['cat /proc/meminfo'], 'a streaming workload can legitimately have a high miss ratio'),
 'cpu_psi_pressure': ('CPU scheduling pressure', 'Inspect runnable workload, cpuset and CPU limits.', ['cat /proc/pressure/cpu'], 'CPU pressure is scheduling delay, not utilization'),
 'io_psi_pressure': ('IO stalls', 'Correlate device latency, memory reclaim and writeback.', ['cat /proc/pressure/io'], 'IO pressure can be secondary to memory pressure'),
 'disk_avg_latency': ('High average block latency', 'Identify slow devices and IO types; use tracing for tail distribution.', ['cat /proc/diskstats'], 'average latency cannot establish p99'),
 'network_errors_per_sec': ('Interface errors', 'Inspect physical link, driver counters and peer configuration.', ['cat /proc/net/dev'], 'virtual interfaces and physical links have different error semantics'),
 'conntrack_usage_pct': ('Conntrack table pressure', 'Inspect connection churn and memory budget before increasing nf_conntrack_max.', ['cat /proc/sys/net/netfilter/nf_conntrack_max'], 'a larger table requires kernel memory'),
 'softnet_dropped': ('Network receive backlog drops', 'Inspect CPU receive distribution, driver queues and netdev_max_backlog.', ['cat /proc/sys/net/core/netdev_max_backlog'], 'larger queues can increase latency'),
 'listen_overflows': ('TCP listen overflow', 'Check application accept rate, listen backlog and somaxconn; consider SO_REUSEPORT.', ['cat /proc/sys/net/core/somaxconn'], 'kernel and application backlog must be configured consistently'),
 'nic_rx_discards': ('NIC receive drops', 'Check driver-specific counters, ring capacity and processing CPU saturation.', ['cat /proc/net/dev'], 'sysfs rx_dropped is a general counter; hardware reasons require driver counters'),
 'tcp_close_wait': ('Application retains closed TCP sockets', 'Inspect socket ownership and application close/error handling.', ['cat /proc/net/tcp'], 'short-lived CLOSE_WAIT sockets are normal'),
 'softnet_time_squeeze': ('Receive processing budget exhausted', 'Inspect IRQ/RPS distribution and netdev_budget before increasing the budget.', ['cat /proc/sys/net/core/netdev_budget'], 'larger budgets can delay other work on the CPU'),
 'tcp_abort_on_memory': ('TCP aborted under memory pressure', 'Inspect socket memory, orphan sockets and system/cgroup memory pressure.', ['cat /proc/net/sockstat'], 'raising buffers can worsen memory exhaustion'),
 'irq_imbalance': ('Uneven network receive processing', 'Check RSS/RPS, IRQ affinity and active queue distribution.', ['cat /proc/softirqs'], 'uneven traffic can legitimately use a subset of queues'),
 'udp_rcvbuf_errors': ('UDP receive buffer overflow', 'Inspect application receive rate and socket buffer sizes.', ['cat /proc/sys/net/core/rmem_max'], 'increasing buffers cannot fix a persistently slow consumer'),
 'tcp_rcvq_drop': ('TCP receive queue drops', 'Inspect application receive latency and socket memory limits.', ['cat /proc/net/sockstat'], 'treat slow application consumption before changing buffers'),
 'tcp_zero_window_drop': ('TCP zero-window drops', 'Inspect application stalls and receive memory pressure.', ['cat /proc/net/netstat'], 'zero-window traffic can originate from peer behavior'),
 'listen_queue_saturation': ('TCP accept queue pressure', 'Increase accept throughput, inspect worker limits and validate application backlog.', ['cat /proc/sys/net/core/somaxconn'], 'a snapshot can miss short backlog spikes'),
 'gpu_nic_cross_numa': ('GPU and NIC on different NUMA nodes', 'Align GPU, NIC, application CPU and memory placement for the actual data path.', [], 'topology alone does not prove remote DMA or quantify a penalty'),
}

def diagnose(metrics, not_applicable=(), sysctls=None, cfg=None, categories=None):
    """Применяет пороговые правила и формирует сводку диагностики.

    Параметры: metrics (dict): измерения; not_applicable (Iterable[str]): неприменимые правила; sysctls (dict или None): настройки ядра; cfg (argparse.Namespace или None): контекст вызова; categories (dict или None): результаты сборщиков.
    Возвращает: dict: USE, оценки, coverage, аномалии и рекомендации; неизвестные значения не считаются нулевыми.
    """
    anomalies, missing, evaluated = [], [], []
    for name, category, warning, critical, unit in RULES:
        if name in not_applicable:
            continue
        value = metrics.get(name)
        if value is None:
            missing.append(name)
        else:
            evaluated.append(name)
            if value >= warning:
                anomalies.append({'metric': name, 'category': category, 'value': value, 'unit': unit,
                                  'threshold': critical if value >= critical else warning,
                                  'severity': 'critical' if value >= critical else 'warning'})
    resources = use_metrics(metrics)
    score = health_score(resources, anomalies)
    complete = all(metrics.get(k) is not None for k in ('cpu_utilization', 'memory_utilization', 'disk_utilization', 'tcp_retransmits'))
    advice = generate_recommendations(metrics, categories or {}, sysctls or {})
    count = len(evaluated) + len(missing)
    categories = {}
    for name, category, _, _, _ in RULES:
        if name not in not_applicable:
            entry = categories.setdefault(category, {'evaluated': 0, 'selected': 0})
            entry['selected'] += 1
            entry['evaluated'] += name in evaluated
    return {'health_score': score if complete else None, 'partial_health_score': score, 'score_version': 'linuxperf/use-2',
            'resources': resources, 'coverage': {'evaluated': len(evaluated), 'selected': count, 'ratio': len(evaluated) / count if count else None, 'categories': categories},
            'unchecked_rules': missing, 'not_applicable_rules': list(not_applicable), 'anomalies': anomalies, 'recommendations': advice}


def ai_prompt(summary, cfg, elapsed):
    """Составляет общие инструкции по интерпретации измерений.

    Параметры: summary (dict): сводка; cfg (argparse.Namespace): профиль и scope; elapsed (float): окно базового замера в секундах.
    Возвращает: str: инструкция с ограничениями достоверности; модель не вызывается.
    """
    return ('Analyze this Linux performance report. Profile=%s; baseline window=%.3fs; target PID=%s; cgroup=%s. '
            'Health score=%s; coverage=%s. Follow evidence, units, sampling windows and scope. '
            'Missing data are unknown, not zero. Correlation is not causation. Do not invent p99 from means. '
            'CPU percentage may exceed 100 for a process; cgroup quotas differ from host CPUs. '
            'Disk busy time does not imply exhaustion on NVMe. Do not sum layered block devices. '
            'Historical NUMA ratios and allocated swap do not prove current stalls. '
            'Do not execute recommendation commands automatically. Identify uncertainty, rank likely causes, '
            'and propose a reversible validation for each hypothesis. Unchecked rules: %s.' %
            (cfg.profile, elapsed, cfg.pid, cfg.cgroup, summary['health_score'], summary['coverage'], ', '.join(summary['unchecked_rules'])))


# ABI ядра Linux: константы и структуры соответствуют UAPI inet_diag.h.
def int_or_none(value):
    """Преобразует значение в целое при допустимом представлении.

    Параметры: value (object): значение для int().
    Возвращает: int или None при TypeError/ValueError.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def unescape_mount(value):
    """Раскрывает восьмеричные escape-последовательности mountinfo.

    Параметры: value (str): экранированное поле пути.
    Возвращает: str: путь с восстановленными символами.
    """
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)


def mounts(src):
    """Разбирает видимые монтирования и cgroup-контроллеры.

    Параметры: src (Source): доступ к self/mountinfo.
    Возвращает: list[dict]: mount, root, type и controllers для разобранных записей.
    """
    records = []
    for line in src.p('self/mountinfo').splitlines():
        fields = line.split()
        try:
            sep = fields.index('-')
            records.append({'root': unescape_mount(fields[3]), 'mount': unescape_mount(fields[4]),
                            'type': fields[sep + 1], 'device': unescape_mount(fields[sep + 2]),
                            'controllers': fields[sep + 3].split(',')})
        except (ValueError, IndexError):
            src.errors.append({'source': 'mountinfo', 'reason': 'parse_error'})
    return records


def cgroup_sources(src, cfg):
    """Находит каталоги контроллеров для выбранного PID или cgroup.

    Параметры: src (Source): mountinfo и membership; cfg (argparse.Namespace): выбранные PID/cgroup.
    Возвращает: dict: controller -> путь, пустое имя для v2; без доступного источника возвращается пустой словарь.
    """
    memberships = {}
    for line in src.p(str(cfg.pid or 'self') + '/cgroup').splitlines():
        fields = line.split(':', 2)
        if len(fields) == 3:
            for controller in fields[1].split(','):
                memberships[controller] = fields[2]
    paths = {}
    for mount in mounts(src):
        if mount['type'] not in ('cgroup', 'cgroup2'):
            continue
        controllers = [''] if mount['type'] == 'cgroup2' else mount['controllers']
        for controller in controllers:
            member = memberships.get(controller)
            if member is None:
                continue
            if cfg.cgroup:
                target = os.path.realpath(cfg.cgroup)
                base = os.path.realpath(mount['mount'])
                if not (target == base or target.startswith(base + '/')):
                    continue
            else:
                root = mount['root'].rstrip('/')
                if member != root and root and not member.startswith(root + '/'):
                    continue
                relative = member[len(root):].lstrip('/')
                target = os.path.join(mount['mount'], relative)
            paths[controller] = target
    # Тестовый sysfs может предоставлять единый cgroup v2 без mountinfo.
    if not paths and os.path.exists(src.sys + '/fs/cgroup/cgroup.controllers') and not cfg.cgroup:
        paths[''] = src.sys + '/fs/cgroup'
    return paths


def cgroup_snapshot(src, cfg):
    """Читает доступные лимиты и счётчики cgroup v1/v2.

    Параметры: src (Source): файловые источники; cfg (argparse.Namespace): выбор цели.
    Возвращает: dict: версия, пути, quota, память, throttling и I/O; неизвестное/безлимитное значение может быть None.
    """
    paths = cgroup_sources(src, cfg)
    unified = paths.get('')
    membership_text = src.p(str(cfg.pid or 'self') + '/cgroup')
    runtime = next((name for marker, name in [('kubepods', 'kubernetes'), ('docker', 'docker'), ('libpod', 'podman'), ('containerd', 'containerd'), ('crio', 'cri-o')] if marker in membership_text), 'none')
    identifiers = re.findall(r'[0-9a-f]{64}', membership_text)
    data = {'version': 2 if unified else 1 if paths else None, 'paths': paths, 'runtime': runtime, 'container_id': identifiers[-1] if identifiers else None}
    def read(controller, name):
        base = unified or paths.get(controller)
        return src.read(os.path.join(base, name)).strip() if base else ''
    data['cpu_stat'] = pairs(read('cpu', 'cpu.stat'))
    if unified:
        quota = read('cpu', 'cpu.max').split()
        data['quota_cores'] = divide(int_or_none(quota[0]), int_or_none(quota[1])) if len(quota) == 2 else None
        data['memory_bytes'] = int_or_none(read('memory', 'memory.current'))
        data['memory_limit_bytes'] = int_or_none(read('memory', 'memory.max'))
        data['memory_events'] = pairs(read('memory', 'memory.events'))
        data['io'] = read('io', 'io.stat')
        data['cpuset'] = read('cpuset', 'cpuset.cpus.effective')
    else:
        data['quota_cores'] = divide(int_or_none(read('cpu', 'cpu.cfs_quota_us')), int_or_none(read('cpu', 'cpu.cfs_period_us')))
        if data['quota_cores'] is not None and data['quota_cores'] < 0:
            data['quota_cores'] = None
        data['memory_bytes'] = int_or_none(read('memory', 'memory.usage_in_bytes'))
        limit = int_or_none(read('memory', 'memory.limit_in_bytes'))
        data['memory_limit_bytes'] = limit if limit is not None and limit < (1 << 60) else None
        data['memory_events'] = {'failcnt': int_or_none(read('memory', 'memory.failcnt'))}
        data['io'] = read('blkio', 'blkio.throttle.io_service_bytes')
        data['cpuset'] = read('cpuset', 'cpuset.cpus')
    return data


def parse_diag_messages(packet, sequence):
    """Разбирает порцию ответов netlink SOCK_DIAG.

    Параметры: packet (bytes): пакет с выровненными сообщениями; sequence (int): ожидаемый номер запроса.
    Возвращает: tuple[list[dict], bool]: слушатели и признак конца ответа.
    Ошибки: ValueError при некорректном сообщении; OSError при сообщении об ошибке от netlink.
    """
    rows, done = [], False
    offset = 0
    while offset + 16 <= len(packet):
        length, kind, flags, seq, port = struct.unpack_from('=IHHII', packet, offset)
        if length < 16 or offset + length > len(packet):
            raise ValueError('truncated netlink message')
        payload = packet[offset + 16:offset + length]
        offset += (length + 3) & ~3
        if seq != sequence:
            continue
        if flags & 0x10:  # NLM_F_DUMP_INTR
            raise ValueError('interrupted netlink dump')
        if kind == 2:
            if len(payload) < 4:
                raise ValueError('invalid netlink error')
            error = struct.unpack_from('=i', payload)[0]
            if error:
                raise OSError(-error, os.strerror(-error))
        elif kind == 3:
            if len(payload) >= 4 and struct.unpack_from('=i', payload)[0]:
                raise ValueError('failed netlink dump')
            done = True
        elif kind == 20:
            if len(payload) < 72:
                raise ValueError('truncated inet_diag_msg')
            family, state = payload[0], payload[1]
            recv, backlog, uid, inode = struct.unpack_from('=IIII', payload, 56)
            port = struct.unpack_from('!H', payload, 4)[0]
            addr = socket.inet_ntop(family, payload[8:12] if family == socket.AF_INET else payload[8:24])
            rows.append({'family': family, 'state': state, 'local_address': addr, 'port': port,
                         'recv_queue': recv, 'backlog': backlog, 'uid': uid, 'inode': inode,
                         'fill_pct': divide(recv, backlog, 100)})
    if offset != len(packet):
        raise ValueError('invalid netlink alignment')
    return rows, done


def listen_queues(timeout=1.):
    """Читает TCP listen backlog через SOCK_DIAG для IPv4/IPv6.

    Параметры: timeout (float): общий бюджет опроса в секундах.
    Возвращает: dict: listeners, errors и status; ошибки сокета/формата сохраняются без прерывания всего сбора.
    """
    rows, errors = [], []
    deadline = time.monotonic() + timeout
    for family in (socket.AF_INET, socket.AF_INET6):
        sequence = family + 100
        try:
            with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 4) as sock:
                sock.bind((0, 0))
                # ABI inet_diag_req_v2 + inet_diag_sockid: запрашиваем только TCP_LISTEN.
                request = struct.pack('=BBBBI', family, socket.IPPROTO_TCP, 0, 0, 1 << 10) + bytes(40) + bytes([255]) * 8
                sock.sendto(struct.pack('=IHHII', 16 + len(request), 20, 0x301, sequence, 0) + request, (0, 0))
                done = False
                while not done and not STOP:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('SOCK_DIAG timeout')
                    sock.settimeout(remaining)
                    packet, _, flags, _ = sock.recvmsg(1024 * 1024)
                    if flags & socket.MSG_TRUNC:
                        raise ValueError('netlink receive budget exhausted')
                    batch, done = parse_diag_messages(packet, sequence)
                    rows.extend(batch)
                    if len(rows) > 10000:
                        raise ValueError('socket budget exhausted')
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    return {'listeners': rows, 'errors': errors, 'status': 'partial' if rows and errors else 'unavailable' if errors else 'ok'}


def filesystem_worker(connection, path):
    """Выполняет statvfs одного mount point в изолированном процессе.

    Параметры: connection (multiprocessing.connection.Connection): канал ответа; path (str): mount point.
    Возвращает: None; сведения о блоках/inode либо ошибка передаются в канал, который затем закрывается.
    """
    try:
        fs = os.statvfs(path)
        connection.send({'size_bytes': fs.f_blocks * fs.f_frsize,
                         'available_bytes': fs.f_bavail * fs.f_frsize,
                         'used_pct': divide(fs.f_blocks - fs.f_bfree, fs.f_blocks, 100),
                         'inode_used_pct': divide(fs.f_files - fs.f_ffree, fs.f_files, 100)})
    except OSError as exc:
        connection.send({'error': str(exc)})
    finally:
        connection.close()


def filesystems(src, timeout=1.):
    """Опрашивает локальные файловые системы с ограничением времени.

    Параметры: src (Source): список монтирований; timeout (float): общий бюджет в секундах.
    Возвращает: list[dict]: данные и статусы; сетевые/pseudo mounts пропускаются, зависшие workers завершаются.
    """
    records = []
    local_types = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'tmpfs', 'overlay', 'zfs', 'vfat', 'f2fs', 'squashfs', 'ramfs'}
    deadline = time.monotonic() + timeout
    context = multiprocessing.get_context('fork')
    for mount in mounts(src)[:256]:
        record = dict(mount, status='skipped', reason='remote_or_pseudo_filesystem')
        if mount['type'] in local_types:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or STOP:
                record['reason'] = 'budget_exhausted'
            else:
                parent, child = context.Pipe(duplex=False)
                worker = context.Process(target=filesystem_worker, args=(child, mount['mount']), daemon=True)
                worker.start()
                child.close()
                try:
                    if parent.poll(min(.2, remaining)):
                        record.update(parent.recv())
                        record.update(status='error' if 'error' in record else 'ok', reason=record.get('error'))
                    else:
                        record.update(status='partial', reason='timeout')
                except EOFError:
                    record.update(status='error', reason='worker_failed')
                finally:
                    parent.close()
                    if worker.is_alive():
                        worker.terminate()
                    worker.join(.05)
                    if worker.is_alive():
                        worker.kill()
                        worker.join(.05)
        records.append(record)
    return records


def histogram_stats(histogram):
    """Дополняет гистограмму оценками по серединам buckets.

    Параметры: histogram (dict): buckets с low, high и count; изменяется на месте.
    Возвращает: dict: та же гистограмма с total_count и оценками; при нуле наблюдений процентили не добавляются.
    """
    # Midpoint — оценка внутри bucket, а не точный процентиль исходных событий.
    buckets = histogram['buckets']
    count = sum(b['count'] for b in buckets)
    histogram.update(total_count=count, method='bucket_midpoint_estimate')
    if count:
        for label, fraction in [('p50', .5), ('p90', .9), ('p99', .99), ('p999', .999)]:
            target, running = math.ceil(count * fraction), 0
            for bucket in sorted(buckets, key=lambda b: b['low']):
                running += bucket['count']
                if running >= target:
                    histogram[label] = (bucket['low'] + bucket['high']) / 2
                    break
        histogram['max'] = max(b['high'] for b in buckets if b['count'])
        histogram['mean'] = sum((b['low'] + b['high']) * .5 * b['count'] for b in buckets) / count
    return histogram


HISTOGRAM_TOOLS = set('runqlat runqlen cpudist biolatency bitesize tcprtt hardirqs softirqs ext4dist btrfsdist xfsdist nfsdist zfsdist tcpsynbl scsilatency nvmelatency'.split())
STACK_TOOLS = set('profile offcputime wakeuptime offwaketime biostacks stackcount'.split())
PERIODIC_TOOLS = set('cachestat slabratetop biotop vfsstat'.split())


def parse_tool(text, limit, name=None, exclude_pid=None):
    """Разбирает известные табличные, histogram и stack-форматы утилит.

    Параметры: text (str): stdout; limit (int): лимит событий/строк; name (str или None): инструмент; exclude_pid (Callable или None): предикат исключения PID.
    Возвращает: dict: events, rows, histograms, stacks и признаки parsed/truncated; неизвестный формат не подтверждает измерение.
    """
    histograms, events, stacks, rows = [], [], [], []
    observer_events_excluded = 0
    if name == 'nvidia-smi':
        for fields in csv.reader(text.splitlines()):
            if len(fields) < 5 or len(rows) >= limit:
                continue
            record = {'name': fields[0].strip(), 'pci_bus_id': fields[1].strip(),
                      'utilization_pct': numeric(fields[2]), 'memory_used_mib': numeric(fields[3]),
                      'memory_total_mib': numeric(fields[4])}
            if len(fields) >= 9:
                record.update(driver_version=fields[5].strip(), memory_utilization_pct=numeric(fields[6]),
                              temperature_c=numeric(fields[7]), power_watts=numeric(fields[8]))
            if len(fields) >= 10:
                record['index'] = int_or_none(fields[9])
            rows.append(record)
        return {'histograms': [], 'stacks': [], 'events': [{'details': row} for row in rows], 'rows': rows,
                'parsed': bool(rows), 'truncated': len(rows) >= limit, 'parser': 'csv', 'observer_events_excluded': 0}
    current = {'name': name or 'histogram', 'unit': None, 'device': None, 'buckets': []}
    headers, truncated, stack_frames = None, False, []
    def flush_frames():
        if stack_frames:
            if len(stacks) < 10000:
                stacks.append({'stack': ';'.join(reversed(stack_frames)), 'count': 1, 'unit': 'events', 'type': name or 'trace'})
            stack_frames.clear()
    def flush():
        nonlocal current
        if current['buckets']:
            histograms.append(histogram_stats(current))
            current = dict(current, buckets=[])
    for line in text.splitlines():
        clean = line.strip()
        if name in ('tcpdrop', 'skbdrop'):
            frame = re.match(r'^(?:(?:0x)?[0-9a-f]{8,}\s+)?([\w.$:<>~/-]+\+0x[0-9a-f]+(?:/0x[0-9a-f]+)?)$', clean)
            if frame:
                stack_frames.append(frame[1])
                continue
            if not clean:
                flush_frames()
        device = re.match(r"(?:disk|dev)\s*=\s*['\"]?([^'\"\s]+)", clean)
        if device:
            flush()
            current['device'] = device[1]
            continue
        unit = re.search(r'\b(usecs?|msecs?|nsecs?|milliseconds|microseconds|slots|bytes)\b\s*:', clean, re.I)
        if unit:
            flush()
            current['unit'] = {'usecs': 'us', 'usec': 'us', 'microseconds': 'us', 'msecs': 'ms', 'msec': 'ms', 'milliseconds': 'ms', 'nsecs': 'ns', 'nsec': 'ns'}.get(unit[1].lower(), unit[1].lower())
            continue
        bucket = re.search(r'(\d+)\s*->\s*(\d+)\s*:\s*(\d+)', clean)
        if bucket:
            if len(current['buckets']) < 4096:
                current['buckets'].append(dict(zip(('low', 'high', 'count'), map(int, bucket.groups()))))
            else:
                truncated = True
            continue
        folded = re.match(r'^(.+?)\s+(\d+)$', clean)
        if folded and (';' in folded[1] or name in STACK_TOOLS):
            if len(stacks) < 10000 and int(folded[2]) > 0:
                stacks.append({'stack': folded[1], 'count': int(folded[2]), 'type': name or 'samples', 'unit': 'us' if name in ('offcputime', 'wakeuptime', 'offwaketime') else 'samples'})
            else:
                truncated = True
            continue
        if not clean or clean.startswith(('Tracing', 'TIME', 'Detaching', 'Attaching')) and not re.match(r'^TIME\S*\s+\w+', clean):
            continue
        if re.match(r'^\d{2}:\d{2}:\d{2}$', clean):
            flush()
            continue
        fields = clean.split()
        if name == 'df' and len(fields) >= 7 and fields[5].endswith('%') and int_or_none(fields[2]) is not None:
            if len(rows) < limit:
                record = dict(zip(('filesystem', 'type', 'size_kib', 'used_kib', 'available_kib', 'used_pct', 'mount'), fields[:6] + [' '.join(fields[6:])]))
                rows.append(record)
                events.append({'details': record})
            else:
                truncated = True
            continue
        if name == 'ss' and len(fields) >= 5 and fields[0] == 'LISTEN':
            if len(rows) < limit:
                record = {'state': 'LISTEN', 'recv_queue': int_or_none(fields[1]), 'backlog': int_or_none(fields[2]), 'local_address': fields[3], 'peer_address': fields[4]}
                record['fill_pct'] = divide(record['recv_queue'], record['backlog'], 100)
                rows.append(record)
                events.append({'details': record})
            else:
                truncated = True
            continue
        if any(f in ('PID', 'COMM', 'HITS', 'HITRATIO', 'LATms', 'LAT(ms)', 'TID', 'COUNT', 'FUNC', 'READ/s', 'WRITE/s', 'ALLOCS', 'FREES', 'Recv-Q', 'Send-Q') for f in fields):
            headers = fields
            continue
        if headers and len(fields) >= len(headers):
            record = dict(zip(headers, fields[:len(headers)-1] + [' '.join(fields[len(headers)-1:])]))
            event_pid = int_or_none(record.get('PID'))
            if event_pid and exclude_pid and exclude_pid(event_pid):
                observer_events_excluded += 1
                continue
            if len(events) < limit:
                events.append({'details': record, 'pid': event_pid, 'comm': record.get('COMM')})
                rows.append(record)
                if record.get('STACK') and len(stacks) < 10000:
                    stacks.append({'stack': record['STACK'], 'count': int_or_none(record.get('ALLOCS')) or 1, 'type': 'allocation', 'unit': 'allocations'})
            else:
                truncated = True
        elif clean:
            if len(events) < limit:
                events.append({'raw': clean})
            else:
                truncated = True
    flush()
    flush_frames()
    # Часть версий biolatency выдаёт JSON вместо текстовых buckets.
    if not histograms and name in HISTOGRAM_TOOLS:
        for line in text.splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict) and isinstance(item.get('data'), list):
                    buckets = [{'low': int(b['interval'][0]), 'high': int(b['interval'][1]), 'count': int(b['count'])} for b in item['data']]
                    histograms.append(histogram_stats({'name': name, 'unit': item.get('unit'), 'device': item.get('disk'), 'buckets': buckets}))
            except (ValueError, TypeError, KeyError, IndexError):
                continue
    valid = bool(histograms) if name in HISTOGRAM_TOOLS else bool(stacks) if name in STACK_TOOLS else bool(events)
    return {'histograms': histograms, 'stacks': stacks, 'events': events, 'rows': rows,
            'truncated': truncated, 'parsed': valid, 'observer_events_excluded': observer_events_excluded, 'parser': 'histogram' if name in HISTOGRAM_TOOLS else 'folded' if name in STACK_TOOLS else 'periodic' if name in PERIODIC_TOOLS else 'tabular'}


def external_metrics(categories, src):
    """Выводит диагностические метрики из разобранных внешних результатов.

    Параметры: categories (dict): результаты сборщиков; src (Source): типы устройств из sysfs.
    Возвращает: dict: доступные метрики; пустые buckets и неизвестные единицы не используются для latency p99.
    """
    metrics = {}
    for group in categories.values():
        for entry in group:
            name = entry['collector']
            for histogram in entry.get('histograms', []):
                count, unit = histogram['total_count'], histogram.get('unit')
                # Непустая histogram учитывается даже при partial; проверяем её единицу отдельно.
                if count <= 0 or unit not in ('us', 'ms', 'ns'):
                    continue
                p99 = histogram.get('p99', 0) * {'us': .001, 'ms': 1, 'ns': .000001}[unit]
                key = None
                if name == 'runqlat':
                    key = 'runqlat_p99'
                elif name == 'biolatency' and histogram.get('device'):
                    rotational = src.s('class/block/' + histogram['device'] + '/queue/rotational').strip()
                    key = {'0': 'biolatency_p99_ssd', '1': 'biolatency_p99_hdd'}.get(rotational)
                if key:
                    metrics[key] = max(metrics.get(key, 0), p99)
            rows = entry.get('rows', [])
            if name == 'cachestat':
                hits = sum(int_or_none(r.get('HITS')) or 0 for r in rows)
                misses = sum(int_or_none(r.get('MISSES')) or 0 for r in rows)
                if hits + misses:
                    metrics['cache_miss_ratio'] = misses / (hits + misses) * 100
            if name == 'gethostlatency':
                values = []
                for row in rows:
                    for key in ('LATms', 'LAT(ms)', 'LAT(MS)'):
                        try:
                            values.append(float(row[key]))
                            break
                        except (KeyError, ValueError):
                            continue
                if values:
                    metrics['dns_latency_p99'] = sorted(values)[math.ceil(.99 * len(values)) - 1]
    return metrics


def observer_snapshot(src):
    """Снимает procfs-счётчики самой программы.

    Параметры: src (Source): доступ к self/io и self/status.
    Возвращает: dict: io и status; недоступные данные остаются пустыми.
    """
    return {'io': pairs(src.p('self/io')), 'status': pairs(src.p('self/status'))}


def enrich(src, cfg, first, last, metrics, categories, rate):
    """Дополняет результаты основного сбора системными деталями.

    Параметры: src (Source): procfs/sysfs; cfg (argparse.Namespace): параметры; first, last (dict): снимки; metrics, categories (dict): изменяемые результаты; rate (Callable): расчёт скорости по двум значениям.
    Возвращает: dict: собранные сетевые sysctl; metrics и categories изменяются на месте.
    """
    def entry(name):
        return next(r for group in categories.values() for r in group if r['collector'] == name)
    cpu = entry('cpu_utilization')['data']
    cpu['context_switches_per_sec'] = rate(first['global_stat'].get('ctxt'), last['global_stat'].get('ctxt'))
    cpu['psi'] = last['psi'].get('cpu')
    for kind, category in [('cpu', 'cpu'), ('memory', 'memory'), ('io', 'disk')]:
        old, new = first['psi'].get(kind, {}).get('some', {}), last['psi'].get(kind, {}).get('some', {})
        value = rate(int_or_none(old.get('total')), int_or_none(new.get('total')))
        metrics[kind + '_psi_interval_pct'] = scale(value, .0001)
    network = entry('network_stats')['data']
    network['listen_queues'] = cfg.baseline_queues
    network['gauge_time'] = cfg.baseline_gauge_time
    if network['listen_queues']['status'] != 'ok':
        fallback = next((r for r in categories['network'] if r['collector'] == 'ss' and r['status'] == 'ok'), None)
        if fallback and fallback.get('rows'):
            network['listen_queues'] = {'listeners': fallback['rows'], 'status': 'ok', 'backend': 'ss', 'errors': network['listen_queues']['errors']}
    metrics['listen_queue_saturation'] = maximum(r['fill_pct'] for r in network['listen_queues']['listeners']) if network['listen_queues']['status'] == 'ok' else None
    irq = []
    for cpu_id, value in last['net_rx'].items():
        irq.append(rate(first['net_rx'].get(cpu_id), value))
    good = [v for v in irq if v is not None]
    irq_deltas = [last['net_rx'][cpu] - first['net_rx'][cpu] for cpu in last['net_rx'] if cpu in first['net_rx'] and last['net_rx'][cpu] >= first['net_rx'][cpu]]
    metrics['irq_imbalance'] = (max(irq_deltas) / min(irq_deltas) if min(irq_deltas) > 0 else max(irq_deltas)) if len(irq_deltas) > 1 and max(irq_deltas) >= 100 else None
    network['net_rx_per_cpu_per_sec'] = irq
    discards = []
    for interface in network['interfaces']:
        name = interface['name']
        root = 'class/net/' + name + '/'
        interface['mtu'] = int_or_none(src.s(root + 'mtu'))
        interface['speed_mbps'] = int_or_none(src.s(root + 'speed'))
        interface['numa_node'] = int_or_none(src.s(root + 'device/numa_node'))
        interface['rx_packets_per_sec'] = rate(first['net'][name][1], last['net'][name][1])
        interface['tx_packets_per_sec'] = rate(first['net'][name][9], last['net'][name][9])
        interface['utilization_pct'] = divide(max(interface['rx_bytes_per_sec'], interface['tx_bytes_per_sec']) * 8, scale(interface['speed_mbps'], 1e6), 100) if interface['rx_bytes_per_sec'] is not None and interface['tx_bytes_per_sec'] is not None else None
        discards.append(rate(first['rx_dropped'].get(name), last['rx_dropped'].get(name)))
    metrics['nic_rx_discards'] = maximum(discards)
    network['sysctls'] = last['sysctls']
    memory = entry('memory_info')['data']
    memory['buddyinfo'] = src.p('buddyinfo')
    memory['thp_defrag'] = src.s('kernel/mm/transparent_hugepage/defrag').strip()
    memory['numa_topology'] = {os.path.basename(path): {key: src.read(path + '/' + key).strip() for key in ('cpulist', 'distance', 'meminfo')} for path in glob.glob(src.sys + '/devices/system/node/node[0-9]*')}
    devices = entry('disk_stats')['data']['devices']
    metrics['disk_average_queue'] = maximum(d['average_queue'] for d in devices)
    for device in devices:
        root = 'class/block/' + device['name'] + '/'
        device.update({key: src.s(root + 'queue/' + key).strip() for key in ('scheduler', 'nr_requests', 'rotational', 'read_ahead_kb')})
        device['is_partition'] = os.path.exists(src.sys + '/' + root + 'partition')
    container = entry('container_info')
    old, new = first['cgroup'], last['cgroup']
    container['data'] = dict(new)
    container['scope'] = 'cgroup'
    container['status'] = 'ok' if new['version'] else 'unavailable'
    container['reason'] = None if new['version'] else 'missing_source'
    # Дельты cgroup сопоставимы только при неизменной версии и путях контроллеров.
    same = old['paths'] == new['paths'] and old['version'] == new['version']
    a, b = old['cpu_stat'], new['cpu_stat']
    throttled_rate = rate(a.get('nr_throttled'), b.get('nr_throttled')) if same else None
    metrics['cpu_throttling'] = b.get('nr_throttled')
    allowed = new.get('quota_cores')
    throttled_raw = b.get('throttled_usec') if new['version'] == 2 else scale(b.get('throttled_time'), .001)
    metrics['container_cpu_utilization'] = divide(scale(throttled_raw, 1e-6), allowed, 100)
    container['data']['throttled_periods_per_sec'] = throttled_rate
    container['data']['throttled_period_pct'] = divide(throttled_rate, rate(a.get('nr_periods'), b.get('nr_periods')), 100) if same else None
    time_key = 'throttled_usec' if new['version'] == 2 else 'throttled_time'
    container['data']['throttled_seconds_per_sec'] = scale(rate(a.get(time_key), b.get(time_key)), 1e-6 if new['version'] == 2 else 1e-9) if same else None
    metrics['container_memory_usage'] = divide(new.get('memory_bytes'), new.get('memory_limit_bytes'), 100)
    if new.get('quota_cores') is not None:
        metrics['container_cpu_quota_cores'] = new['quota_cores']
    system = entry('system_info')['data']
    system['filesystems'] = filesystems(src) if src.proc == '/proc' else []
    system['boot_params'] = src.p('cmdline').strip()
    system['scope'] = 'host-visible'
    process = entry('process_info')
    process['scope'] = 'process' if cfg.pid else 'cgroup' if cfg.cgroup else 'host-visible'
    for item in {p['pid']: p for key in ('top_by_cpu', 'top_by_memory', 'top_by_io') for p in process['data'][key]}.values():
        pid = str(item['pid'])
        status = pairs(src.p(pid + '/status'))
        item['threads'] = status.get('Threads')
        try:
            item['fd_count'] = len(os.listdir(src.proc + '/' + pid + '/fd'))
        except OSError:
            item['fd_count'] = None
    metrics.update(external_metrics(categories, src))
    return network['sysctls']


SYSCTLS = '''kernel/numa_balancing kernel/sched_latency_ns kernel/sched_min_granularity_ns kernel/sched_wakeup_granularity_ns kernel/sched_numa_balancing vm/dirty_expire_centisecs vm/dirty_writeback_centisecs vm/zone_reclaim_mode net/core/default_qdisc net/ipv4/neigh/default/gc_thresh1 net/ipv4/neigh/default/gc_thresh2 vm/swappiness vm/dirty_ratio vm/dirty_background_ratio vm/overcommit_memory vm/min_free_kbytes vm/watermark_scale_factor
net/core/somaxconn net/core/rmem_max net/core/wmem_max net/core/netdev_max_backlog net/core/netdev_budget
net/ipv4/tcp_congestion_control net/ipv4/tcp_available_congestion_control net/ipv4/tcp_rmem net/ipv4/tcp_wmem
net/ipv4/tcp_tw_reuse net/ipv4/tcp_max_syn_backlog net/ipv4/ip_local_port_range net/ipv4/tcp_slow_start_after_idle
net/ipv4/tcp_fastopen net/ipv4/tcp_mem net/ipv4/tcp_syncookies net/ipv4/tcp_mtu_probing net/ipv4/tcp_fin_timeout
net/ipv4/tcp_keepalive_time net/ipv4/tcp_keepalive_intvl net/ipv4/tcp_keepalive_probes net/core/rmem_default
net/core/wmem_default net/core/netdev_budget_usecs net/ipv4/udp_mem net/ipv4/udp_rmem_min net/ipv4/udp_wmem_min
net/ipv4/neigh/default/gc_thresh3 net/netfilter/nf_conntrack_max'''.split()


def use_metrics(metrics):
    """Сопоставляет известные метрики ресурсам метода USE.

    Параметры: metrics (dict): значения диагностических метрик.
    Возвращает: dict: utilization, saturation и errors по ресурсам; единицы насыщения различаются.
    """
    resources = {}
    for category, utilization, saturation, errors in [
        ('cpu', 'cpu_utilization', 'cpu_saturation', None),
        ('memory', 'memory_utilization', 'swap_usage', None),
        ('disk', 'disk_utilization', 'disk_in_flight', None),
        ('network', None, 'tcp_wait_sockets', 'network_total_errors'),
        ('container_memory', 'container_memory_usage', None, None),
        ('container_cpu', 'container_cpu_utilization', 'cpu_throttling', None)]:
        resources[category] = {'utilization': metrics.get(utilization) if utilization else 0, 'saturation': metrics.get(saturation), 'errors': metrics.get(errors) if errors else 0}
    return resources


def health_score(resources, anomalies):
    """Вычисляет эвристическую оценку из USE и штрафов аномалий.

    Параметры: resources (dict): USE-значения; anomalies (list[dict]): обнаруженные превышения.
    Возвращает: int: оценка 0..100; доступность достаточных исходных данных проверяется отдельно в diagnose.
    """
    score = 100
    for name, values in resources.items():
        weight = {'cpu': 1.5, 'memory': 1.5, 'disk': 1., 'network': 1., 'container_cpu': 1.2, 'container_memory': 1.2}.get(name, .5)
        for key, bands in [('utilization', [(95, 15), (85, 8), (70, 3)]), ('saturation', [(50, 15), (10, 8), (1, 3)]), ('errors', [(1000, 10), (100, 5), (0, 2)])]:
            value = values[key]
            if value is None:
                continue
            for threshold, penalty in bands:
                if (value >= threshold if key == 'utilization' else value > threshold):
                    score -= int(penalty * weight)
                    break
    score -= sum(10 if a['severity'] == 'critical' else 5 for a in anomalies)
    return max(0, min(100, score))


def metric_spec(name):
    """Описывает единицы, метод и область видимости метрики.

    Параметры: name (str): имя метрики.
    Возвращает: dict: unit, method, scope, source и при необходимости estimator.
    """
    rule = next((r for r in RULES if r[0] == name), None)
    spec = {'unit': rule[4] if rule else {'cpu_saturation': '%', 'tcp_wait_sockets': 'sockets', 'network_total_errors': '/s', 'network_interface_errors_total': '/s', 'disk_in_flight': 'requests', 'disk_average_queue': 'requests', 'container_cpu_utilization': '%'}.get(name, '%' if name.endswith('_pct') else 'source-specific'),
            'method': 'counter' if name in ('cpu_throttling', 'nic_rx_discards') else 'cumulative_ratio' if name == 'numa_miss_ratio' else 'rate' if name.endswith(('_rate', '_per_sec')) or name in ('tcp_retransmits', 'cpu_throttling', 'softnet_dropped', 'listen_overflows', 'nic_rx_discards', 'softnet_time_squeeze', 'tcp_abort_on_memory', 'udp_rcvbuf_errors', 'tcp_rcvq_drop', 'tcp_zero_window_drop') else 'bucket_estimate' if 'p99' in name else 'gauge',
            'scope': 'cgroup' if name.startswith('container_') or name == 'cpu_throttling' else 'network_namespace' if rule and rule[1] == 'network' else 'host-visible',
            'source': METRIC_SOURCES.get(name, 'procfs/sysfs')}

    if 'p99' in name:
        spec['estimator'] = 'nearest_rank' if name == 'dns_latency_p99' else 'bucket_midpoint'
    return spec


METRIC_SOURCES = {
    'cpu_saturation': '/proc/loadavg', 'disk_in_flight': '/proc/diskstats', 'tcp_wait_sockets': '/proc/net/tcp,tcp6', 'network_total_errors': '/proc/net/dev,snmp', 'cpu_throttling': 'cgroup cpu.stat', 'container_memory_usage': 'cgroup memory.current/memory.max', 'nic_rx_discards': 'ethtool -S', 'gpu_nic_cross_numa': '/sys/bus/pci/devices', 'cpu_psi_pressure': '/proc/pressure/cpu', 'memory_psi_pressure': '/proc/pressure/memory', 'io_psi_pressure': '/proc/pressure/io',
    'cpu_utilization': '/proc/stat', 'cpu_iowait': '/proc/stat', 'load_average': '/proc/loadavg',
    'memory_utilization': '/proc/meminfo', 'swap_usage': '/proc/meminfo',
    'direct_reclaim_rate': '/proc/vmstat', 'compaction_stall_rate': '/proc/vmstat', 'thp_split_rate': '/proc/vmstat',
    'numa_miss_ratio': '/sys/devices/system/node/node*/numastat', 'tcp_retransmits': '/proc/net/snmp',
    'disk_utilization': '/proc/diskstats', 'disk_avg_latency': '/proc/diskstats',
    'listen_queue_saturation': 'SOCK_DIAG', 'runqlat_p99': 'runqlat', 'biolatency_p99_ssd': 'biolatency',
    'biolatency_p99_hdd': 'biolatency', 'dns_latency_p99': 'gethostlatency', 'cache_miss_ratio': 'cachestat'}


def decode_share_payload(encoded, compressed=True):
    """Декодирует и проверяет ограниченный payload публикации.

    Параметры: encoded (bytes): JSON либо gzip JSON; compressed (bool): требуется ли распаковка.
    Возвращает: dict: version, metadata и summary поддерживаемой схемы.
    Ошибки: ValueError при превышении 1 MiB/неверной схеме или JSON; OSError/EOFError при повреждённом gzip.
    """
    if len(encoded) > 1024 * 1024:
        raise ValueError('share input exceeds 1 MiB')
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:
            raw = stream.read(1024 * 1024 + 1)
    else:
        raw = encoded
    if len(raw) > 1024 * 1024:
        raise ValueError('expanded share input exceeds 1 MiB')
    payload = json.loads(raw, parse_constant=reject_json_constant)
    if not isinstance(payload, dict) or payload.get('version') != 1 or not isinstance(payload.get('metadata'), dict) or not isinstance(payload.get('summary'), dict):
        raise ValueError('invalid linuxperf share payload')
    if payload['metadata'].get('schema_version') != SCHEMA:
        raise ValueError('unsupported report schema')
    return payload


class ShareStore:
    """SQLite-хранилище сводок с ограниченным временем доступности."""
    def __init__(self, path, ttl=604800):
        """Создаёт файл/таблицу хранилища опубликованных сводок.

        Параметры: path (str): путь SQLite; ttl (int): срок доступности в секундах.
        Возвращает: None; новый файл создаётся с правами 0600.
        Ошибки: OSError или sqlite3.Error при создании/открытии.
        """
        self.path, self.ttl = path, ttl
        try:
            created = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            created = None
        if created is not None:
            os.close(created)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL)')

    def put(self, payload):
        """Сохраняет сводку и удаляет просроченные записи.

        Параметры: payload (dict): JSON-совместимая сводка.
        Возвращает: str: случайный код ссылки.
        Ошибки: sqlite3.Error при записи; TypeError при несериализуемом payload.
        """
        code = secrets.token_urlsafe(9)
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM reports WHERE created < ?', (time.time() - self.ttl,))
            db.execute('INSERT INTO reports VALUES (?, ?, ?)', (code, time.time(), json.dumps(payload)))
        return code

    def get(self, code):
        """Читает доступную по коду непросроченную сводку.

        Параметры: code (str): код ссылки из 12 разрешённых символов.
        Возвращает: dict или None при неверном/неизвестном/просроченном коде.
        Ошибки: sqlite3.Error при отказе базы.
        """
        if not re.fullmatch(r'[A-Za-z0-9_-]{12}', code):
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute('SELECT payload FROM reports WHERE id=? AND created>=?', (code, time.time() - self.ttl)).fetchone()
        return json.loads(row[0]) if row else None


def serve_reports(cfg):
    """Обслуживает локальное хранилище опубликованных сводок по HTTP.

    Параметры: cfg (argparse.Namespace): bind, port, token, public_url, storage и ttl.
    Возвращает: None после остановки; база и HTTP-сокет создаются явно этой командой.
    Ошибки: ValueError при неверных лимитах/незащищённом внешнем bind; OSError при открытии сервера.
    """
    if cfg.bind not in ('127.0.0.1', '::1', 'localhost') and (not cfg.token or not cfg.public_url):
        raise ValueError('non-loopback serving requires --token and --public-url')
    if not 1 <= cfg.port <= 65535 or not 1 <= cfg.ttl <= 31536000:
        raise ValueError('port must be 1..65535 and ttl 1..31536000 seconds')
    store = ShareStore(cfg.storage, cfg.ttl)
    base = (cfg.public_url or ('http://[::1]:%d' if cfg.bind == '::1' else 'http://127.0.0.1:%d') % cfg.port).rstrip('/')
    rates = {}
    class Handler(http.server.BaseHTTPRequestHandler):
        """HTTP-обработчик публикации сводок и чтения по коду ссылки."""
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def respond(self, status, body, content_type='application/json'):
            encoded = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            if self.path != '/api/reports':
                self.respond(404, '{"error":"not found"}')
                return
            authorization = self.headers.get('Authorization', '')
            if cfg.token and not secrets.compare_digest(authorization, 'Bearer ' + cfg.token):
                self.respond(401, '{"error":"unauthorized"}')
                return
            now = time.monotonic()
            ip = self.client_address[0]
            if len(rates) >= 1024:
                rates.clear()
            window, count = rates.get(ip, (now, 0))
            if now - window >= 60:
                window, count = now, 0
            rates[ip] = window, count + 1
            if count >= 60:
                self.respond(429, '{"error":"rate limited"}')
                return
            length = int_or_none(self.headers.get('Content-Length'))
            if length is None or not 0 < length <= 1024 * 1024:
                self.respond(413, '{"error":"invalid content length"}')
                return
            self.connection.settimeout(10)
            try:
                payload = decode_share_payload(self.rfile.read(length), self.headers.get('Content-Encoding') == 'gzip')
                code = store.put(payload)
                self.respond(201, json.dumps({'url': base + '/r/' + code}))
            except (ValueError, OSError, EOFError) as exc:
                self.respond(400, json.dumps({'error': str(exc)}))

        def do_GET(self):
            code = self.path[len('/r/'):] if self.path.startswith('/r/') else ''
            payload = store.get(code)
            if not payload:
                self.respond(404, '{"error":"not found"}')
                return
            document = export(dict(payload, categories={}), 'html')
            self.respond(200, document, 'text/html')

        def log_message(self, fmt, *args):
            logging.info('share HTTP: ' + fmt, *args)
    # Один HTTP-поток позволяет учитывать rate limit без блокировок; запросы ограничены таймаутом.
    class ReportHTTPServer(http.server.HTTPServer):
        """HTTP-сервер с IPv4/IPv6-семейством выбранного bind-адреса."""
        address_family = socket.AF_INET6 if ':' in cfg.bind else socket.AF_INET
    server = ReportHTTPServer((cfg.bind, cfg.port), Handler)
    server.timeout = .25
    logging.warning('Serving linuxperf reports at %s; storage=%s', base, cfg.storage)
    try:
        while not STOP:
            server.handle_request()
    finally:
        server.server_close()


def install_plan(os_release):
    """Выбирает пакетный менеджер и зависимости для дистрибутива.

    Параметры: os_release (str): содержимое /etc/os-release.
    Возвращает: dict: менеджер, пакеты, аргументы и ID дистрибутива; установка не выполняется.
    """
    distro = dict(line.split('=', 1) for line in os_release.splitlines() if '=' in line)
    distro_id = distro.get('ID', '').strip('"')
    family = distro_id + ' ' + distro.get('ID_LIKE', '').strip('"')
    if any(word in family.split() for word in ('debian', 'ubuntu')):
        manager, packages, args = 'apt-get', ['bpfcc-tools', 'bpftrace', 'linux-perf' if distro_id == 'debian' else 'linux-tools-common', 'iproute2', 'sysstat', 'procps', 'ethtool'], ['install', '-y']
    elif 'arch' in family.split():
        manager, packages, args = 'pacman', ['bcc', 'bcc-tools', 'bpftrace', 'perf', 'iproute2', 'sysstat', 'procps-ng', 'ethtool'], ['-S', '--needed', '--noconfirm']
    elif any(word in family.split() for word in ('suse', 'opensuse', 'opensuse-leap')):
        manager, packages, args = 'zypper', ['bcc-tools', 'bpftrace', 'perf', 'iproute2', 'sysstat', 'procps', 'ethtool'], ['--non-interactive', 'install']
    else:
        manager = 'dnf' if trusted_tool('dnf') else 'yum'
        packages, args = ['bcc-tools', 'bpftrace', 'perf', 'iproute', 'sysstat', 'procps-ng', 'ethtool'], ['install', '-y']
    if manager == 'apt-get':
        packages += ['python3-bpfcc', 'linux-headers-' + os.uname().release]
        packages += ['linux-headers-amd64'] if distro_id == 'debian' and os.uname().machine == 'x86_64' else ['linux-headers-generic'] if distro_id != 'debian' else []
        if distro_id != 'debian':
            packages += ['linux-tools-' + os.uname().release, 'linux-tools-generic']
    elif manager in ('dnf', 'yum'):
        release = os.uname().release
        # В РЕД ОС 7.3 серия 6.1 LT использует пакет kernel-lt, поэтому нужен kernel-lt-devel.
        devel = 'kernel-lt-devel-' if distro_id == 'redos' and release.startswith('6.1.') and '.el7.3' in release else 'kernel-devel-'
        packages += ['python3-bcc', devel + release]
    elif manager == 'pacman':
        packages += ['python-bcc', 'linux-headers']
    return {'distro': distro_id, 'manager': manager, 'packages': packages, 'args': args}


def install_tools(dry_run=False):
    """Устанавливает зависимости по одному либо показывает план.

    Параметры: dry_run (bool): вернуть план без установки.
    Возвращает: dict: план или исходы установки со статусом.
    Ошибки: PermissionError без root при реальной установке; ValueError при отсутствии менеджера.
    """
    plan = install_plan(read_text_bounded('/etc/os-release'))
    if dry_run:
        return dict(plan, command=[plan['manager']] + plan['args'] + plan['packages'], executed=False)
    if os.geteuid() != 0:
        raise PermissionError('install requires root; collect never installs packages')
    path = trusted_tool(plan['manager'])
    if not path:
        raise ValueError('package manager is unavailable: ' + plan['manager'])
    outcomes = []
    for package in plan['packages']:
        if STOP:
            break
        logging.warning('Installing %s with %s', package, plan['manager'])
        output = command(path, plan['args'] + [package], 3600)
        outcomes.append({'package': package, **output})
    return dict(plan, executed=True, status='partial' if STOP or any(o['reason'] for o in outcomes) else 'ok', outcomes=outcomes)


def share_report(report, api_url=None, timeout=10., token=None):
    """Создаёт локальный HTML URL либо отправляет сводку выбранному сервису.

    Параметры: report (dict): отчёт; api_url (str или None): явный endpoint, без него сеть не используется; timeout (float): секунды HTTP; token (str или None): Bearer token.
    Возвращает: str: data:text/html URL с полным отчётом либо URL опубликованной сводки.
    Ошибки: ValueError для неверного URL/ответа; OSError при сетевом отказе.
    """
    if not api_url:
        document = export(report, 'html').encode('utf-8')
        return 'data:text/html;charset=utf-8;base64,' + base64.b64encode(document).decode('ascii')
    parts = urllib.parse.urlsplit(api_url)
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password:
        raise ValueError('api-url must be an http(s) URL without embedded credentials')
    payload = {'version': 1, 'metadata': report['metadata'], 'summary': report['summary']}
    body = gzip.compress(json.dumps(payload, allow_nan=False).encode('utf-8'), mtime=0)
    request = urllib.request.Request(api_url, data=body, headers={'Content-Type': 'application/json', 'Content-Encoding': 'gzip'}, method='POST')
    if token:
        request.add_header('Authorization', 'Bearer ' + token)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        encoded = response.read(65537)
    if len(encoded) > 65536:
        raise ValueError('share response exceeds budget')
    reply = json.loads(encoded)
    if not isinstance(reply, dict):
        raise ValueError('share response must be a JSON object')
    url = reply.get('url')
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError('share service must return {"url": "https://..."}')
    return url


def compare_inventory(report):
    """Разворачивает метрики и данные устройств для сравнения.

    Параметры: report (dict): исходный отчёт.
    Возвращает: dict: плоские ключи метрик, USE, устройств и histogram p99.
    """
    values = dict(report.get('metrics', {}))
    for resource, fields in report.get('summary', {}).get('resources', {}).items():
        for name, value in fields.items():
            values['use.' + resource + '.' + name] = value
    for group in report.get('categories', {}).values():
        for entry in group:
            data = entry.get('data') or {}
            if not isinstance(data, dict):
                continue
            for field in ('devices', 'interfaces'):
                for entity in data.get(field, []):
                    identity = entity.get('name')
                    if not identity:
                        continue
                    for key, value in entity.items():
                        if key.endswith(('_per_sec', '_pct', '_ms', '_iops')) or key in ('average_queue', 'in_flight'):
                            values[entry['collector'] + '.' + identity + '.' + key] = value
            for histogram in entry.get('histograms', []):
                for percentile in ('p50', 'p90', 'p99', 'p999'):
                    values['histogram.' + entry['collector'] + '.' + str(histogram.get('device')) + '.' + str(histogram.get('unit')) + '.' + percentile] = histogram.get(percentile)
    return values


def classify_changes(changes):
    """Подсчитывает направленные изменения сопоставимых метрик.

    Параметры: changes (list[dict]): записи сравнения, изменяются на месте.
    Возвращает: tuple[int, int]: число регрессий и улучшений; записи дополняются направлением и значимостью.
    """
    regressions = improvements = 0
    for change in changes:
        if not change['comparable']:
            change.update(direction='unknown', significance='unknown')
            continue
        difference, percent = change['delta'], change['percent_change']
        magnitude = abs(percent) if percent is not None else (100 if difference else 0)
        change['significance'] = 'high' if magnitude >= 50 else 'medium' if magnitude >= 10 else 'low'
        higher_is_better = any(word in change['metric'] for word in ('available', 'free_bytes', 'health'))
        bad = difference < 0 if higher_is_better else difference > 0
        change['direction'] = 'unchanged' if abs(difference) < .1 and magnitude < 1 else 'regression' if bad else 'improvement'
        regressions += change['direction'] == 'regression'
        improvements += change['direction'] == 'improvement'
    return regressions, improvements


def generate_recommendations(metrics, categories, sysctls):
    """Формирует рекомендации по 35 условиям без выполнения команд.

    Параметры: metrics (dict): измерения; categories (dict): данные источников; sysctls (dict): настройки ядра.
    Возвращает: list[dict]: рекомендации в заданном порядке с priority, type, evidence, командами и настройками сохранения.
    """
    def data(name):
        return next((r['data'] for group in categories.values() for r in group if r['collector'] == name), {}) or {}
    cpu, mem, net, disk = data('cpu_utilization'), data('memory_info'), data('network_stats'), data('disk_stats')
    protocol = net.get('protocol_counters', {})
    selected = []
    def integer(path):
        return int_or_none(sysctls.get(path))
    def gt(path, boundary):
        value = integer(path)
        return value is not None and value > boundary
    def low(path, boundary):
        value = integer(path)
        return value is not None and 0 < value < boundary
    def active(metric, boundary=0):
        value = metrics.get(metric)
        return value is not None and value > boundary
    def add(index, condition, evidence, arguments=None):
        if condition:
            selected.append((index, evidence, arguments or {}))
    thp = re.search(r'\[([^\]]+)\]', mem.get('thp', ''))
    thp = thp[1] if thp else mem.get('thp', '')
    add(0, active('load_average', 2), {'load_per_cpu': metrics.get('load_average')})
    add(1, gt('kernel/sched_latency_ns', 24000000), {'sched_latency_ns': integer('kernel/sched_latency_ns')})
    add(2, gt('vm/swappiness', 30) and active('swap_usage'), {'swappiness': integer('vm/swappiness'), 'swap_usage_pct': metrics.get('swap_usage')})
    add(3, gt('vm/dirty_ratio', 20), {'dirty_ratio': integer('vm/dirty_ratio')})
    add(4, integer('vm/overcommit_memory') == 0, {'overcommit_memory': integer('vm/overcommit_memory')})
    add(5, active('direct_reclaim_rate'), {'direct_reclaim_rate': metrics.get('direct_reclaim_rate')})
    add(6, active('thp_split_rate', 1) and thp == 'always', {'thp_split_rate': metrics.get('thp_split_rate'), 'thp': thp})
    for node, values in mem.get('numa', {}).items():
        ratio = divide(values.get('numa_miss'), values.get('numa_hit', 0) + values.get('numa_miss', 0), 100)
        if ratio is not None and ratio > 5:
            number = int(node.replace('node', ''))
            add(7, True, {'node': node, 'miss_ratio': ratio}, {'title': (number, ratio), 'commands': (number, number)})
            break
    add(8, active('compaction_stall_rate', 1), {'compaction_stall_rate': metrics.get('compaction_stall_rate')})
    add(9, bool(sysctls.get('net/ipv4/tcp_congestion_control')) and sysctls['net/ipv4/tcp_congestion_control'] != 'bbr', {'congestion_control': sysctls.get('net/ipv4/tcp_congestion_control')})
    add(10, active('tcp_retransmits', 1), {'retransmits_per_sec': metrics.get('tcp_retransmits')})
    add(11, low('net/core/somaxconn', 4096), {'somaxconn': integer('net/core/somaxconn')})
    for index, path in [(12, 'net/ipv4/tcp_rmem'), (13, 'net/ipv4/tcp_wmem')]:
        values = sysctls.get(path, '').split()
        add(index, len(values) == 3 and int_or_none(values[2]) is not None and int(values[2]) < 4194304, {path: sysctls.get(path)})
    add(14, integer('net/ipv4/tcp_tw_reuse') == 0 and active('tcp_timewait', 1000), {'timewait': metrics.get('tcp_timewait')})
    add(15, low('net/ipv4/tcp_max_syn_backlog', 4096), {'syn_backlog': integer('net/ipv4/tcp_max_syn_backlog')})
    maximum = integer('net/netfilter/nf_conntrack_max')
    add(16, active('conntrack_usage_pct', 70) and maximum is not None, {'usage_pct': metrics.get('conntrack_usage_pct'), 'max': maximum}, {'commands': (2 * maximum,) if maximum else (), 'persistent': (2 * maximum,) if maximum else ()})
    for interface in net.get('interfaces', []):
        counters = interface.get('driver_counters', {})
        discards = sum(v for k, v in counters.items() if 'discard' in k.lower() and isinstance(v, int))
        current, maximum = interface.get('ring_rx_current'), interface.get('ring_rx_max')
        add(17, current is not None and maximum is not None and 0 < current < maximum / 2 and discards > 0, {'interface': interface['name'], 'rx_discards': discards, 'ring_current': current, 'ring_max': maximum}, {'title': (interface['name'],), 'commands': (interface['name'], maximum)})
    add(18, protocol.get('TcpExt:ListenOverflows', 0) > 0, {'ListenOverflows': protocol.get('TcpExt:ListenOverflows')})
    add(19, low('net/core/netdev_max_backlog', 5000) and net.get('softnet_counters', {}).get('dropped', 0) not in (0, None), {'netdev_max_backlog': integer('net/core/netdev_max_backlog')})
    add(20, low('net/core/rmem_max', 16777216), {'rmem_max': integer('net/core/rmem_max'), 'wmem_max': integer('net/core/wmem_max')})
    ports = sysctls.get('net/ipv4/ip_local_port_range', '').split()
    add(21, len(ports) == 2 and all(int_or_none(x) is not None for x in ports) and int(ports[1]) - int(ports[0]) < 40000, {'port_range': ports})
    add(22, integer('net/ipv4/tcp_slow_start_after_idle') == 1, {'tcp_slow_start_after_idle': 1})
    tfo = integer('net/ipv4/tcp_fastopen')
    add(23, tfo is not None and 0 <= tfo < 3, {'tcp_fastopen': tfo})
    add(24, low('net/core/netdev_budget', 600) and net.get('softnet_counters', {}).get('time_squeeze', 0) not in (None, 0), {'netdev_budget': integer('net/core/netdev_budget'), 'netdev_budget_usecs': integer('net/core/netdev_budget_usecs')})
    add(25, protocol.get('Udp:RcvbufErrors', 0) > 0 and low('net/core/rmem_max', 26214400), {'udp_rcvbuf_errors': protocol.get('Udp:RcvbufErrors'), 'rmem_max': integer('net/core/rmem_max')})
    add(26, net.get('established_recvq_saturated', 0) > 0, {'established_recvq_saturated': net.get('established_recvq_saturated')})
    for listener in net.get('listen_queues', {}).get('listeners', []):
        fill = listener.get('fill_pct')
        if fill is not None and fill >= 70:
            add(27, True, listener, {'title': (listener.get('local_address', '?'), fill), 'commands': (max(listener.get('backlog', 0) * 2, 65535),)})
            break
    add(28, active('tcp_zero_window_drop'), {'zero_window_drop_per_sec': metrics.get('tcp_zero_window_drop')})
    arp = integer('net/ipv4/neigh/default/gc_thresh3')
    add(29, arp is not None and 0 < arp <= 1024, {'arp_gc_thresh3': arp})
    add(30, protocol.get('TcpExt:PruneCalled', 0) > 0, {'PruneCalled': protocol.get('TcpExt:PruneCalled')})
    for device in disk.get('devices', []):
        match = re.search(r'\[([^\]]+)\]', device.get('scheduler', ''))
        scheduler = match[1] if match else device.get('scheduler', '')
        for index, rotational, excluded in [(31, '0', ('mq-deadline', 'none')), (32, '1', ('bfq',))]:
            add(index, device.get('rotational') == rotational and bool(scheduler) and scheduler not in excluded, {'device': device['name'], 'scheduler': scheduler, 'rotational': rotational}, {'title': (device['name'],), 'commands': (device['name'],), 'persistent': (device['name'],)})
    add(33, thp == 'always', {'transparent_hugepage': thp})
    add(34, mem.get('total_bytes', 0) > 16 * 1024 ** 3 and low('vm/min_free_kbytes', 65536), {'min_free_kbytes': integer('vm/min_free_kbytes'), 'total_bytes': mem.get('total_bytes')})
    results = []
    for index, evidence, arguments in sorted(selected, key=lambda row: row[0]):
        row = dict(RECOMMENDATION_CATALOG[index])
        for field in ('title', 'commands', 'persistent'):
            values = row.get(field, '') if field == 'title' else list(row.get(field, []))
            args = arguments.get(field, ())
            def render(text):
                if re.search(r'%(?:\.\d+)?[sdf]', text):
                    number = len(re.findall(r'%(?:\.\d+)?[sdf]', text))
                    return text % tuple(args[:number]) if len(args) >= number else text
                return text
            row[field] = render(values) if field == 'title' else [render(v) for v in values]
        row.update(id='recommendation_%02d' % index, priority=len(results) + 1, evidence=evidence,
                   assumptions='Validate workload suitability, kernel support, resource budget and rollback before applying.',
                   scope='host-visible')
        results.append(row)
    return results


def numeric(value):
    """Преобразует числовую строку для табличного парсера.

    Параметры: value (object): исходное значение.
    Возвращает: float или None при неверном/нечисловом значении либо NaN/Infinity.
    """
    try:
        number = float(str(value).strip().rstrip('%'))
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def aggregate_events(events, field, top=10):
    """Группирует события и вычисляет краткую статистику задержек.

    Параметры: events (list[dict]): события; field (str): ключ группировки; top (int): число верхних групп.
    Возвращает: dict: total_count и top_by_count со счётчиками и доступными задержками.
    """
    groups = {}
    for event in events:
        details = event.get('details', {})
        value = details.get(field)
        if value is None:
            continue
        bucket = groups.setdefault(str(value), {'key': str(value), 'count': 0, 'sample': details, 'latencies': []})
        bucket['count'] += 1
        latency = numeric(details.get('latency_ms'))
        if latency is not None:
            bucket['latencies'].append(latency)
    result = sorted(groups.values(), key=lambda v: (-v['count'], v['key']))
    for row in result:
        latencies = row.pop('latencies')
        if latencies:
            row['avg_latency_ms'] = sum(latencies) / len(latencies)
            row['max_latency_ms'] = max(latencies)
    return {'total_count': sum(r['count'] for r in result), 'top_by_count': result[:top]}


EVENT_FIELDS = {
    'PID': 'pid', 'TID': 'tid', 'COMM': 'comm', 'PCOMM': 'comm', 'SADDR': 'laddr', 'LADDR': 'laddr',
    'DADDR': 'daddr', 'RADDR': 'daddr', 'LPORT': 'lport', 'SPORT': 'lport', 'RPORT': 'dport', 'DPORT': 'dport',
    'LAT(ms)': 'latency_ms', 'LATms': 'latency_ms', 'MS': 'latency_ms', 'LAT(us)': 'latency_us',
    'DISK': 'disk', 'DEV': 'disk', 'FILENAME': 'filename', 'FILE': 'filename', 'PATH': 'filename',
    'RET': 'return_value', 'FD': 'fd', 'BYTES': 'bytes', 'SIZE': 'bytes', 'COUNT': 'count', 'STATE': 'state'}


def normalize_events(name, parsed):
    """Нормализует известные поля событий и связанные представления.

    Параметры: name (str): инструмент; parsed (dict): результат parse_tool, изменяется на месте.
    Возвращает: None; добавляются доступные адреса, порты и нормализованные поля.
    """
    for event in parsed['events']:
        details = event.get('details')
        if not details:
            continue
        normalized = {}
        for key, value in details.items():
            target = EVENT_FIELDS.get(key, key.lower().replace('/', '_per_'))
            val = numeric(value)
            normalized[target] = val if target in ('latency_ms', 'latency_us') else int(val) if val is not None and target in ('pid', 'tid', 'lport', 'dport', 'fd', 'bytes', 'count', 'return_value') else value
        if 'latency_us' in normalized and normalized['latency_us'] is not None:
            normalized['latency_ms'] = normalized['latency_us'] / 1000
        for key, side in [('saddr:sport', 'l'), ('laddr:lport', 'l'), ('daddr:dport', 'd'), ('raddr:rport', 'd')]:
            endpoint = normalized.get(key)
            if isinstance(endpoint, str) and ':' in endpoint:
                address, port = endpoint.rsplit(':', 1)
                normalized[side + 'addr'] = address.strip('[]')
                normalized[side + 'port'] = int_or_none(port)
        event['details'] = normalized
        event['pid'] = normalized.get('pid', event.get('pid'))
        event['comm'] = normalized.get('comm', event.get('comm'))
    field = 'daddr' if name.startswith(('tcp', 'udp')) else 'filename' if name in ('opensnoop', 'fileslower', 'filelife', 'statsnoop') else 'disk' if name in ('biosnoop', 'biotop') else 'comm'
    parsed['aggregation'] = aggregate_events(parsed['events'], field)
    parsed['parser_variant'] = name


def parse_ethtool(data):
    """Объединяет ответы ethtool по интерфейсам в общие поля.

    Параметры: data (dict): interface -> ответы команд -i/-g/-k/-c/-S.
    Возвращает: dict: нормализованные свойства, ring sizes и driver counters.
    """
    normalized = {}
    for interface, commands in data.items():
        item = {'features': {}, 'driver_counters': {}}
        for flag, output in commands.items():
            text = output.get('stdout', '')
            if flag == '-i':
                item.update({k.strip().replace('-', '_'): v.strip() for k, v in re.findall(r'^([^:\n]+):\s*(.*)$', text, re.M)})
            elif flag == '-g':
                section = None
                for line in text.splitlines():
                    if 'Pre-set maximums' in line:
                        section = 'max'
                    elif 'Current hardware settings' in line:
                        section = 'current'
                    match = re.match(r'\s*(RX|TX):\s*(\d+)', line)
                    if match and section:
                        item['ring_' + match[1].lower() + '_' + section] = int(match[2])
            elif flag == '-k':
                item['features'] = {key.strip(): value == 'on' for key, value in re.findall(r'^\s*([\w-]+):\s*(on|off)', text, re.M)}
            elif flag == '-c':
                item['coalescing'] = pairs(text)
            elif flag == '-S':
                item['driver_counters'] = pairs(text)
        normalized[interface] = item
    return normalized


def restore_metrics(src, cfg, first, last, metrics, categories):
    """Дополняет отчёт расширенными метриками и свойствами устройств.

    Параметры: src (Source): источники; cfg (argparse.Namespace): параметры; first, last (dict): снимки; metrics, categories (dict): изменяемые результаты.
    Возвращает: None; обновляет metrics и data существующих сборщиков.
    """
    def data(name):
        return next(r['data'] for group in categories.values() for r in group if r['collector'] == name)
    cpu, memory, network = data('cpu_utilization'), data('memory_info'), data('network_stats')
    cpu['load_avg_1'], cpu['load_avg_5'], cpu['load_avg_15'] = [numeric(x) for x in (last['load'] + [None] * 3)[:3]]
    cpu['scheduler'] = {key: int_or_none(last['sysctls'].get('kernel/' + key)) for key in ('sched_latency_ns', 'sched_min_granularity_ns', 'sched_wakeup_granularity_ns', 'sched_numa_balancing')}
    cpu['scheduler']['numa_balancing'] = int_or_none(last['sysctls'].get('kernel/numa_balancing'))
    cpu['psi'] = last['psi'].get('cpu', {})
    memory['psi'] = last['psi'].get('memory', {})
    memory['vm_parameters'] = {key: int_or_none(last['sysctls'].get('vm/' + key)) for key in ('dirty_expire_centisecs', 'dirty_writeback_centisecs', 'zone_reclaim_mode', 'watermark_scale_factor', 'min_free_kbytes', 'swappiness', 'overcommit_memory', 'dirty_ratio', 'dirty_background_ratio')}
    network['socket_memory'] = last['socket_memory']
    network['socket_memory_bytes'] = {name: {protocol: scale(values.get('mem'), os.sysconf('SC_PAGE_SIZE')) for protocol, values in protocols.items() if 'mem' in values} for name, protocols in last['socket_memory'].items()}
    network['softnet_counters'] = {'dropped': last['softnet'], 'time_squeeze': last['squeeze']}
    network['established_recvq_saturated'] = sum(int(line.split()[4].split(':')[1], 16) > 65536 for line in last['tcp_text'].splitlines() if len(line.split()) > 4 and line.split()[3] == '01')
    ethtool = next((r for r in categories['network'] if r['collector'] == 'ethtool' and isinstance(r['data'], dict)), None)
    nic_details = parse_ethtool(ethtool['data']) if ethtool else {}
    for interface in network['interfaces']:
        interface.update(nic_details.get(interface['name'], {}))
        counters = interface.get('driver_counters', {})
        interface['rx_discards'] = sum(value for key, value in counters.items() if key in ('rx_discards', 'rx_total_ring_discards') and isinstance(value, int)) if counters else None
        interface['rx_buffer_errors'] = sum(value for key, value in counters.items() if key in ('rx_buf_errors', 'rx_total_buf_errors') and isinstance(value, int)) if counters else None
        for attribute in ('rx', 'tx'):
            interface[attribute + '_queues'] = len(glob.glob(src.sys + '/class/net/' + interface['name'] + '/queues/' + attribute + '-*'))
    metrics['nic_rx_dropped_per_sec'] = metrics.get('nic_rx_discards')
    metrics['nic_rx_discards'] = maximum(interface.get('rx_discards') for interface in network['interfaces'])
    system = data('system_info')
    system['block_devices'] = []
    for path in glob.glob(src.sys + '/block/*'):
        sectors = int_or_none(src.read(path + '/size'))
        rotational = int_or_none(src.read(path + '/queue/rotational'))
        system['block_devices'].append({'name': os.path.basename(path), 'size_bytes': scale(sectors, 512),
                                        'model': src.read(path + '/device/model').strip(), 'rotational': rotational,
                                        'type': 'hdd' if rotational == 1 else 'ssd' if rotational == 0 else 'unknown'})
    data('disk_stats')['psi'] = last['psi'].get('io', {})
    memory['total_bytes'] = scale(last['meminfo'].get('MemTotal'), 1024)


def build_ai_context(summary, cfg, elapsed, categories, metadata=None):
    """Готовит инструкции модели с качеством и ограничениями измерений.

    Параметры: summary (dict): диагностика; cfg (argparse.Namespace): параметры; elapsed (float): базовое окно в секундах; categories (dict): результаты; metadata (dict или None): окна и накладные расходы.
    Возвращает: dict: prompt, методология, справочник гипотез и правила интерпретации; сеть и модель не вызываются.
    """
    patterns = [
        'Treat cumulative counters as history; use interval rates for active errors.',
        'High swap allocation does not establish current swap IO.',
        'MemFree excludes reclaimable cache; use MemAvailable.',
        'Load includes uninterruptible tasks, not only runnable CPU demand.',
        'Per-process CPU can exceed 100% across cores.',
        'Host CPU count differs from cgroup quota and cpuset.',
        'Steal time indicates hypervisor scheduling interference.',
        'IOwait alone does not identify a slow device.',
        'Disk busy time does not measure all NVMe parallel capacity.',
        'Do not sum layered devices and partitions as independent IO.',
        'An idle device has unknown average latency, not measured zero latency.',
        'Mean latency does not determine p99 or p999.',
        'Bucket percentiles are estimates; inspect observation counts.',
        'Tracing overhead can perturb workload behavior.',
        'A snapshot can miss short queue spikes.',
        'Interface drops require driver and queue context.',
        'Retransmits can originate from remote or local loss.',
        'TIME_WAIT is a normal socket state; inspect port pressure.',
        'CLOSE_WAIT may identify a slow application close path.',
        'Socket buffers consume kernel memory; larger is not always better.',
        'Zero-window events may indicate an application unable to consume data.',
        'PSI is stall time, not resource utilization.',
        'NUMA allocation ratios are not measurements of memory access latency.',
        'GPU/NIC topology alone does not establish remote DMA.',
        'A memleak trace needs allocation lifetime context.',
        'Missing data are unknown and cannot certify health.',
        'Do not execute tuning commands without validating workload and rollback.',
    ]
    metadata = metadata or {}
    rows = [r for group in categories.values() for r in group]
    tools = [r for r in rows if r['backend'] in ('external', 'native_ebpf')]
    counts = {status: sum(r['status'] == status for r in tools)
              for status in ('ok', 'partial', 'unavailable', 'skipped', 'error')}
    failures = {}
    for row in tools:
        if row.get('reason'):
            failures.setdefault(row['reason'], []).append(row['collector'])
    empty = [r['collector'] for r in tools if r['status'] in ('ok', 'partial') and
             not (r.get('events') or r.get('stacks') or r.get('histograms'))]
    prompt = ai_prompt(summary, cfg, elapsed)
    prompt += '\nSystem: %s, kernel=%s, CPUs=%s.\n' % (os.uname().nodename, os.uname().release, os.cpu_count())
    prompt += 'COLLECTION QUALITY: external/native collector counts=' + json.dumps(counts, separators=(',', ':'))
    prompt += '; recorded failure reasons=' + json.dumps(failures, separators=(',', ':'))
    prompt += '; no parsed events/stacks/histograms=' + json.dumps(empty, separators=(',', ':'))
    prompt += '. Empty event output may mean no events; it does not prove a tool failure or a healthy system. Do not guess causes of missing data.\n'
    if cfg.external_tools == 'auto' or cfg.native_ebpf == 'auto':
        prompt += ('COLLECTION WINDOWS: baseline was sampled before tracing; later samples and traces may include observer load. '
                   'Baseline CPU is not whole-run CPU. Two phases do not eliminate observer effects. ')
    else:
        prompt += 'COLLECTION WINDOWS: external tools and native eBPF were disabled. '
    prompt += 'Baseline=%.3fs; requested=%gs; actual=%ss; observed=%ss. Inspect per-collector timestamps and completion status.\n' % (
        elapsed, cfg.duration, metadata.get('actual_duration', 'unknown'), metadata.get('observed_window_seconds', 'unknown'))
    overhead = metadata.get('observer_overhead', {})
    prompt += 'OBSERVER OVERHEAD: ' + json.dumps({key: overhead.get(key) for key in (
        'cpu_user_ms', 'cpu_system_ms', 'children_user_ms', 'children_system_ms', 'peak_rss_bytes')}, separators=(',', ':'))
    prompt += '. CPU values are CPU-time milliseconds, not utilization percentages. Peak RSS covers the collector itself, not combined child memory. Kernel tracing overhead is not fully attributed here.\n'
    usable = [r for r in tools if r['status'] == 'ok']
    stacks = [r['collector'] for r in usable if any(s.get('count', 0) > 0 for s in r.get('stacks', []))]
    histograms = [r['collector'] for r in usable if any(h.get('total_count', 0) > 0 for h in r.get('histograms', []))]
    if stacks:
        prompt += 'Usable stack sources: %s. Inspect hot paths and contention; separate workload stacks from diagnostic tools.\n' % ', '.join(stacks)
    if histograms:
        prompt += 'Usable histogram sources: %s. Inspect tail latency and distribution shape only after checking units, bucket counts and observation windows.\n' % ', '.join(histograms)
    prompt += 'Use metric_specs for units; USE resource values are not universally percentages. Health score is not collection quality.\n'
    prompt += 'Anomalies: ' + json.dumps(summary['anomalies'], separators=(',', ':'))
    prompt += ('\nAnswer in the user language, within 500 words. First state collection limitations, then up to three likely problems ranked by impact. '
               'For each give evidence (collector/metric, value, unit, window), confidence, and one concrete read-only validation command. '
               'Separate observed facts from hypotheses; state when evidence is insufficient. '
               'Suggest tuning only when justified, with production risk and rollback. Do not enumerate unrelated failure patterns.')
    prompt += ('\nREFERENCE HYPOTHESES (optional, not a checklist): '
               'Select only hypotheses supported by measurements in this report. '
               'Do not work through or reproduce the entire list. A matching pattern is not a proven cause; '
               'cite evidence and a validation check before drawing conclusions. '
               'If none are supported, say so briefly without forcing a match.\n')
    prompt += '\n'.join(ANTI_PATTERNS)
    return {'methodology': 'USE Method (Utilization, Saturation, Errors)', 'known_patterns': ANTI_PATTERNS, 'interpretation_rules': patterns, 'prompt': prompt}


class ObserverTracker:
    """Учёт PID и последних I/O-счётчиков сборщика и его потомков."""
    def __init__(self, src):
        """Начинает учёт с PID самой программы.

        Параметры: src (Source): доступ к procfs.
        Возвращает: None.
        """
        self.src, self.pids, self.snapshots = src, {os.getpid()}, {}
        self.lock = threading.RLock()

    def register(self, pid):
        """Регистрирует PID дочерней диагностической команды.

        Параметры: pid (int): PID процесса.
        Возвращает: None.
        """
        with self.lock:
            self.pids.add(pid)

    def is_observer(self, pid, parent=None):
        """Проверяет принадлежность PID к диагностике и запоминает потомков.

        Параметры: pid (int): проверяемый PID; parent (int или None): известный PPID, иначе читается procfs.
        Возвращает: bool: PID уже известен либо его родитель известен.
        """
        with self.lock:
            if pid in self.pids:
                return True
            if parent is None:
                stat_text = self.src.p(str(pid) + '/stat')
                end = stat_text.rfind(')')
                fields = stat_text[end + 2:].split()
                parent = int_or_none(fields[1]) if end >= 0 and len(fields) > 1 else None
            if parent in self.pids:
                self.pids.add(pid)
                return True
            return False

    def snapshot(self):
        """Обновляет последние доступные I/O-счётчики известных PID.

        Возвращает: None; старые счётчики сохраняются, если процесс уже завершился.
        """
        with self.lock:
            for pid in list(self.pids):
                value = pairs(self.src.p(str(pid) + '/io'))
                if value:
                    self.snapshots[pid] = value

    def io_totals(self):
        """Суммирует известные I/O-счётчики дочерних процессов.

        Возвращает: dict: read_bytes/write_bytes без PID самой программы; это последние доступные счётчики, не отдельные дельты.
        """
        return {key: sum(v.get(key, 0) for pid, v in self.snapshots.items() if pid != os.getpid()) for key in ('read_bytes', 'write_bytes')}


def parse_sockstat(text):
    """Разбирает статистику сокетов по протоколам.

    Параметры: text (str): содержимое sockstat или sockstat6.
    Возвращает: dict: протокол -> поля/значения; неверные числовые значения становятся None.
    """
    data = {}
    for line in text.splitlines():
        fields = line.replace(':', '').split()
        if fields:
            data[fields[0]] = {k: int_or_none(v) for k, v in zip(fields[1::2], fields[2::2])}
    return data


def tool_duration(cfg, name):
    """Выбирает окно инструмента с учётом профиля и override.

    Параметры: cfg (argparse.Namespace): профиль и длительность; name (str): инструмент.
    Возвращает: float или int: секунды; явный duration имеет приоритет над отдельным окном стеков.
    """
    if getattr(cfg, 'duration_overridden', False):
        return cfg.duration
    if name in STACK_TOOLS:
        return {'quick': 10, 'standard': 15, 'deep': 30}[cfg.profile]
    return cfg.duration


def tracepoint_layout(text):
    """Извлекает смещения полей события retransmit из tracefs format.

    Параметры: text (str): описание полей tracepoint.
    Возвращает: dict: имя поля -> (смещение, размер) в байтах.
    Ошибки: ValueError, если обязательные поля не найдены.
    """
    fields = {}
    for declaration, offset, size in re.findall(r'field:([^;]+);\s*offset:(\d+);\s*size:(\d+);', text):
        name = declaration.strip().split()[-1].split('[')[0].lstrip('*')
        offset, size = int(offset), int(size)
        if offset < 4096 and size in (1, 2, 4, 8, 16):
            fields[name] = (offset, size)
    if any(name not in fields for name in ('sport', 'dport', 'family', 'saddr', 'daddr')):
        raise ValueError('tcp_retransmit_skb tracepoint lacks required fields')
    return fields


def bpf_instruction(code, dst=0, src=0, offset=0, immediate=0):
    """Упаковывает одну инструкцию eBPF в бинарный формат.

    Параметры: code, dst, src, offset, immediate (int): opcode, регистры, смещение и константа.
    Возвращает: bytes: 8 байт инструкции.
    Ошибки: struct.error при выходе поля за допустимый диапазон.
    """
    return struct.pack('<BBhi', code, dst | (src << 4), offset, immediate)


def retrans_program(layout, map_fd, pid=None, kprobe=False):
    """Строит eBPF-байткод retransmit без компилятора и ELF.

    Параметры: layout (dict): смещения/размеры полей; map_fd (int): ringbuf FD; pid (int или None): фильтр текущего PID; kprobe (bool): читать sock через pt_regs вместо tracepoint.
    Возвращает: bytes: программа для little-endian x86_64 с выровненными чтениями контекста.
    """
    instructions = []
    def emit(*args):
        instructions.append(bpf_instruction(*args))
    emit(0xbf, 6, 1)  # callee-saved tracepoint context
    for offset in range(-80, 0, 8):
        emit(0x7a, 10, 0, offset, 0)
    emit(0x85, 0, 0, 0, 14)  # bpf_get_current_pid_tgid
    emit(0x77, 0, 0, 0, 32)
    emit(0x63, 10, 0, -72)
    # Смещение PID-ветки станет известно после построения программы; патчим его в конце.
    branch = None
    if pid:
        branch = len(instructions)
        emit(0x55, 0, 0, 0, pid)
    emit(0x85, 0, 0, 0, 5)  # ktime_get_ns
    emit(0x7b, 10, 0, -80)
    if kprobe:
        emit(0x79, 8, 6, 112)  # x86_64 pt_regs.di: first function argument (struct sock *)
    for name, destination in [('family', 12), ('sport', 14), ('dport', 16), ('state', 18), ('saddr', 20), ('daddr', 24), ('saddr_v6', 28), ('daddr_v6', 44)]:
        if name not in layout:
            continue
        offset, size = layout[name]
        # В tracepoint state занимает int; для нашего ABI нужны только младшие 16 бит.
        width = min(size, 2) if name == 'state' else size
        if kprobe:
            emit(0xbf, 1, 10)
            emit(0x07, 1, 0, 0, -80 + destination)
            emit(0xb7, 2, 0, 0, width)
            emit(0xbf, 3, 8)
            emit(0x07, 3, 0, 0, offset)
            emit(0x85, 0, 0, 0, 113)
            if name == 'dport':
                emit(0x69, 0, 10, -80 + destination)
                emit(0xdc, 0, 0, 0, 16)
                emit(0x6b, 10, 0, -80 + destination)
            continue
        # Поля tracepoint бывают невыровненными, например saddr со смещением 34.
        # Verifier отвергает невыровненный LDX даже на x86_64: разбиваем чтение
        # на части, выровненные одновременно по адресу контекста и стека.
        step = 0
        while step < width:
            remaining = width - step
            source_offset = offset + step
            destination_offset = -80 + destination + step
            size_part = next(size for size in (4, 2, 1) if size <= remaining and source_offset % size == 0 and destination_offset % size == 0)
            load = {1: 0x71, 2: 0x69, 4: 0x61}[size_part]
            store = {1: 0x73, 2: 0x6b, 4: 0x63}[size_part]
            emit(load, 0, 6, source_offset)
            emit(store, 10, 0, destination_offset)
            step += size_part
    emit(0xbf, 1, 10)
    emit(0x07, 1, 0, 0, -20)  # comm at byte 60
    emit(0xb7, 2, 0, 0, 16)
    emit(0x85, 0, 0, 0, 16)  # get_current_comm
    emit(0x18, 1, 1, 0, map_fd)  # BPF_PSEUDO_MAP_FD, two instructions
    emit(0, 0, 0, 0, 0)
    emit(0xbf, 2, 10)
    emit(0x07, 2, 0, 0, -80)
    emit(0xb7, 3, 0, 0, 80)
    emit(0xb7, 4, 0, 0, 0)
    emit(0x85, 0, 0, 0, 130)  # bpf_ringbuf_output
    end = len(instructions)
    emit(0xb7, 0, 0, 0, 0)
    emit(0x95)
    if branch is not None:
        instructions[branch] = bpf_instruction(0x55, 0, 0, end - branch - 1, pid)
    return b''.join(instructions)


def decode_retrans_event(data):
    """Декодирует бинарную запись native retransmit в сетевое событие.

    Параметры: data (bytes): запись ABI встроенной BPF-программы.
    Возвращает: dict: время, PID, comm, адреса, порты и состояние.
    Ошибки: ValueError при короткой записи или неизвестном семействе адресов.
    """
    if len(data) < 80:
        raise ValueError('short native retransmit record')
    timestamp, pid, family, sport, dport, state = struct.unpack_from('<QIHHHH', data)
    if family == socket.AF_INET:
        source, destination = data[20:24], data[24:28]
    elif family == socket.AF_INET6:
        source, destination = data[28:44], data[44:60]
    else:
        raise ValueError('unknown socket family')
    return {'time': utc(), 'monotonic_ns': timestamp, 'pid': pid,
            'comm': data[60:76].split(b'\0', 1)[0].decode('utf-8', 'replace'),
            'details': {'laddr': socket.inet_ntop(family, source), 'daddr': socket.inet_ntop(family, destination),
                        'lport': sport, 'dport': dport, 'state': state, 'family': family,
                        'pid_semantics': 'current execution context; not necessarily socket owner'}}


def native_capability():
    """Проверяет наличие предпосылок native backend без загрузки BPF.

    Возвращает: dict: архитектура, tracefs и кандидат BTF/kprobe; успешная загрузка не гарантируется.
    """
    root = next((p for p in ('/sys/kernel/tracing', '/sys/kernel/debug/tracing') if os.path.isfile(p + '/events/tcp/tcp_retransmit_skb/format')), None)
    return {'backend': 'native_ebpf_tracepoint', 'architecture_supported': os.uname().machine == 'x86_64' and sys.byteorder == 'little',
            'tracefs': root, 'btf_kprobe': os.path.isfile('/sys/kernel/btf/vmlinux') and os.path.isfile('/sys/bus/event_source/devices/kprobe/type'), 'status': 'candidate' if (root or os.path.isfile('/sys/kernel/btf/vmlinux')) and os.uname().machine == 'x86_64' else 'unavailable',
            'note': 'Load/attach permissions and ringbuf support are determined at runtime'}


class KernelBTF:
    """Разбор BTF ядра и смещений полей структур без libbpf."""
    def __init__(self, raw):
        """Разбирает заголовок, строки и поддерживаемые типы BTF.

        Параметры: raw (bytes): двоичный BTF.
        Возвращает: None.
        Ошибки: ValueError при неверном заголовке, неизвестном или усечённом типе.
        """
        if len(raw) < 24:
            raise ValueError('short BTF header')
        magic, version, flags, header, offset, length, string_offset, string_length = struct.unpack_from('<HBBIIIII', raw)
        if magic != 0xeb9f or version != 1 or header + offset + length > len(raw) or header + string_offset + string_length > len(raw):
            raise ValueError('invalid BTF header')
        self.strings = raw[header + string_offset:header + string_offset + string_length]
        self.types = [None]
        cursor, end = header + offset, header + offset + length
        while cursor < end:
            if cursor + 12 > end:
                raise ValueError('truncated BTF type')
            name, info, value = struct.unpack_from('<III', raw, cursor)
            kind, count, bitfield = (info >> 24) & 31, info & 65535, bool(info >> 31)
            cursor += 12
            sizes = {0: 0, 1: 4, 2: 0, 3: 12, 4: 12 * count, 5: 12 * count, 6: 8 * count,
                     7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 0, 13: 8 * count, 14: 4,
                     15: 12 * count, 16: 0, 17: 4, 18: 0, 19: 12 * count}
            if kind not in sizes or cursor + sizes[kind] > end:
                raise ValueError('unsupported or truncated BTF kind %d' % kind)
            members = []
            if kind in (4, 5):
                for i in range(count):
                    member_name, member_type, member_offset = struct.unpack_from('<III', raw, cursor + i * 12)
                    width = member_offset >> 24 if bitfield else 0
                    member_offset = member_offset & 0xffffff if bitfield else member_offset
                    members.append((member_name, member_type, member_offset, width))
            self.types.append((name, kind, value, members))
            cursor += sizes[kind]
        self.structs = {self.string(t[0]): i for i, t in enumerate(self.types) if t and t[1] == 4 and t[3]}

    def string(self, offset):
        """Читает строку BTF по смещению в таблице строк.

        Параметры: offset (int): байтовое смещение.
        Возвращает: str: декодированная строка.
        Ошибки: ValueError при недопустимом смещении.
        """
        if not 0 <= offset < len(self.strings):
            raise ValueError('invalid BTF string')
        end = self.strings.find(b'\0', offset)
        return self.strings[offset:end].decode('utf-8', 'replace')

    def resolve(self, type_id):
        """Пропускает typedef и квалификаторы в цепочке типов.

        Параметры: type_id (int): индекс существующего типа BTF.
        Возвращает: int: индекс базового типа.
        Ошибки: ValueError при пустой/циклической цепочке; IndexError при неверном индексе.
        """
        visited = set()
        while type_id and type_id not in visited:
            visited.add(type_id)
            record = self.types[type_id]
            if record[1] not in (8, 9, 10, 11, 18):
                return type_id
            type_id = record[2]
        raise ValueError('invalid BTF type chain')

    def member(self, type_id, name, depth=0):
        """Находит поле структуры, включая анонимные вложения.

        Параметры: type_id (int): тип структуры; name (str): поле; depth (int): текущая глубина поиска.
        Возвращает: tuple[int, int]: байтовое смещение и ID типа.
        Ошибки: KeyError для отсутствующего поля; ValueError для bitfield, невыровненного поля или глубины более 16.
        """
        if depth > 16:
            raise ValueError('BTF anonymous nesting budget exceeded')
        type_id = self.resolve(type_id)
        record = self.types[type_id]
        for member_name, member_type, bits, width in record[3]:
            if self.string(member_name) == name:
                if bits % 8 or width:
                    raise ValueError('bitfield cannot be read as an aligned scalar')
                return bits // 8, member_type
        for member_name, member_type, bits, width in record[3]:
            if member_name == 0:
                try:
                    offset, target = self.member(member_type, name, depth + 1)
                    return bits // 8 + offset, target
                except KeyError:
                    continue
        raise KeyError(name)

    def sock_layout(self):
        """Строит расположение полей сокета с учётом __sk_common.

        Возвращает: dict: имя поля -> (смещение, размер). IPv6-поля необязательны.
        Ошибки: ValueError/KeyError при отсутствии необходимых структур или полей.
        """
        common = self.structs.get('sock_common')
        if common is None:
            raise ValueError('sock_common is absent from kernel BTF')
        layout = {}
        for name, member, size in [('sport', 'skc_num', 2), ('dport', 'skc_dport', 2), ('family', 'skc_family', 2),
                                   ('state', 'skc_state', 1), ('saddr', 'skc_rcv_saddr', 4), ('daddr', 'skc_daddr', 4),
                                   ('saddr_v6', 'skc_v6_rcv_saddr', 16), ('daddr_v6', 'skc_v6_daddr', 16)]:
            try:
                layout[name] = (self.member(common, member)[0], size)
            except KeyError:
                if size != 16:
                    raise ValueError('required socket field is absent: ' + member)
        # Смещение __sk_common берём из BTF, а не предполагаем равным нулю.
        sock = self.structs.get('sock')
        base = self.member(sock, '__sk_common')[0] if sock else 0
        return {name: (base + offset, size) for name, (offset, size) in layout.items()}


def kernel_sock_layout():
    """Получает смещения sock_common из опубликованного BTF ядра.

    Возвращает: dict: расположение полей struct sock.
    Ошибки: OSError при чтении BTF; ValueError при превышении 32 MiB или неверной структуре.
    """
    with open('/sys/kernel/btf/vmlinux', 'rb') as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('kernel BTF exceeds input budget')
    return KernelBTF(raw).sock_layout()


class BPFVerifierError(OSError):
    """Отказ verifier с его журналом; EACCES не всегда означает нехватку прав."""
    def __init__(self, error, message, log):
        """Сохраняет журнал отклонённой BPF-программы в исключении.

        Параметры: error (int): errno; message (str): системное сообщение; log (str): журнал verifier.
        Возвращает: None; журнал доступен через verifier_log.
        """
        self.verifier_log = log
        super().__init__(error, '%s; verifier: %s' % (message, log))


class NativeBPF:
    """Владение FD и mmap встроенной BPF-трассировки на x86_64."""
    def __init__(self):
        """Проверяет ABI, готовит syscall и учёт ресурсов.

        Возвращает: None; пытается поднять только лимит memlock текущего процесса.
        Ошибки: OSError на неподдерживаемой архитектуре; отказ изменения лимита лишь журналируется.
        """
        if os.uname().machine != 'x86_64' or sys.byteorder != 'little':
            raise OSError(errno.ENOTSUP, 'native backend currently supports little-endian x86_64')
        soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
        try:
            if os.geteuid() == 0:
                resource.setrlimit(resource.RLIMIT_MEMLOCK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
            elif soft != hard:
                resource.setrlimit(resource.RLIMIT_MEMLOCK, (hard, hard))
        except (OSError, ValueError) as exc:
            logging.debug('Cannot raise process memlock limit: %s', exc)
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.syscall.restype = ctypes.c_long
        self.fds, self.maps = [], []

    def syscall(self, number, *args):
        """Вызывает Linux syscall и преобразует errno в исключение.

        Параметры: number (int): номер syscall; args (tuple): аргументы ABI ctypes.
        Возвращает: int: неотрицательный результат.
        Ошибки: OSError при отрицательном результате.
        """
        value = self.libc.syscall(ctypes.c_long(number), *args)
        if value < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return value

    def bpf(self, operation, attr):
        """Передаёт сериализованный bpf_attr в syscall BPF.

        Параметры: operation (int): команда BPF; attr (bytes или bytearray): её ABI-структура.
        Возвращает: int: результат syscall.
        Ошибки: OSError при отказе ядра.
        """
        buf = ctypes.create_string_buffer(bytes(attr))
        return self.syscall(321, ctypes.c_int(operation), ctypes.byref(buf), ctypes.c_uint(len(attr)))

    def open(self, layout, trace_id, pid=None, kprobe=False):
        """Создаёт ringbuf, загружает программу и подключает perf event.

        Параметры: layout (dict): поля события/сокета; trace_id (int): ID tracepoint или тип PMU; pid (int или None): PID-фильтр; kprobe (bool): режим подключения.
        Возвращает: None; ресурсы учитываются для последующего close даже при частичном отказе.
        Ошибки: OSError/BPFVerifierError при загрузке/attach; ValueError при недопустимом наборе CPU.
        """
        attr = bytearray(72)
        struct.pack_into('<IIII', attr, 0, 27, 0, 0, 262144)
        try:
            map_fd = self.bpf(0, attr)
        except OSError as exc:
            raise OSError(exc.errno, 'BPF_MAP_CREATE ringbuf failed: %s; memlock=%s' % (exc.strerror, resource.getrlimit(resource.RLIMIT_MEMLOCK)))
        self.fds.append(map_fd)
        code = ctypes.create_string_buffer(retrans_program(layout, map_fd, pid, kprobe))
        license_text = ctypes.create_string_buffer(b'GPL\0')
        verifier = ctypes.create_string_buffer(65536)
        attr = bytearray(120)
        struct.pack_into('<IIQQIIQ', attr, 0, 2 if kprobe else 5, len(code.raw[:-1]) // 8, ctypes.addressof(code), ctypes.addressof(license_text), 1, len(verifier), ctypes.addressof(verifier))
        try:
            program_fd = self.bpf(5, attr)
        except OSError as exc:
            log = verifier.value.decode('utf-8', 'replace')[-8192:]
            if log.strip():
                raise BPFVerifierError(exc.errno, exc.strerror, log)
            raise
        self.fds.append(program_fd)
        online = read_text_bounded('/sys/devices/system/cpu/online').strip()
        cpus = []
        for item in online.split(','):
            bounds = item.split('-')
            cpus.extend(range(int(bounds[0]), int(bounds[-1]) + 1))
        if len(cpus) > 4096:
            raise ValueError('native CPU budget exceeded')
        symbol = ctypes.create_string_buffer(b'tcp_retransmit_skb\0')
        if not cpus:
            raise ValueError('no online CPU available for native attachment')
        # Tracing callback глобален: одного perf-подключения достаточно для всех CPU.
        # Повторное подключение той же программы может дать EEXIST.
        # Выбор CPU здесь нужен для perf_event_open, а не для фильтрации событий.
        for cpu in cpus[:1]:
            attr = ctypes.create_string_buffer(128)
            struct.pack_into('<IIQQQQQ', attr, 0, trace_id if kprobe else 2, 128, 0 if kprobe else trace_id, 1, 0, 0, 1)
            if kprobe:
                struct.pack_into('<Q', attr, 56, ctypes.addressof(symbol))
            try:
                fd = self.syscall(298, ctypes.byref(attr), ctypes.c_int(-1), ctypes.c_int(cpu), ctypes.c_int(-1), ctypes.c_ulong(8))
            except OSError as exc:
                raise OSError(exc.errno, 'perf_event_open cpu=%d: %s' % (cpu, exc.strerror)) from exc
            self.fds.append(fd)
            for operation, value, stage in ((0x40042408, program_fd, 'PERF_EVENT_IOC_SET_BPF'), (0x2400, 0, 'PERF_EVENT_IOC_ENABLE')):
                try:
                    fcntl.ioctl(fd, operation, value)
                except OSError as exc:
                    raise OSError(exc.errno, '%s cpu=%d: %s' % (stage, cpu, exc.strerror)) from exc
        page = os.sysconf('SC_PAGE_SIZE')
        self.consumer = mmap.mmap(map_fd, page, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        self.maps.append(self.consumer)
        self.producer = mmap.mmap(map_fd, page + 2 * 262144, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ, offset=page)
        self.maps.append(self.producer)
        self.page = page

    def read(self):
        """Читает завершённые записи ringbuf и продвигает consumer.

        Возвращает: list[bytes]: записи без discarded/busy; busy останавливает текущий проход.
        Ошибки: ValueError при недопустимом размере записи.
        """
        consumer = struct.unpack_from('<Q', self.consumer)[0]
        producer = struct.unpack_from('<Q', self.producer)[0]
        records = []
        # Двойное отображение producer позволяет читать запись через границу кольца.
        while consumer < producer:
            offset = self.page + (consumer & (262144 - 1))
            length = struct.unpack_from('<I', self.producer, offset)[0]
            # BUSY означает незавершённую запись: её нельзя пропускать до следующего чтения.
            if length & (1 << 31):
                break
            size = length & ((1 << 30) - 1)
            if size > 262144 - 8:
                raise ValueError('invalid ringbuf record size')
            if not length & (1 << 30):
                records.append(bytes(self.producer[offset + 8:offset + 8 + size]))
            # Восемь байт заголовка и округление полной записи до границы 8 байт ABI.
            consumer += (size + 8 + 7) & ~7
        struct.pack_into('<Q', self.consumer, 0, consumer)
        return records

    def close(self):
        """Освобождает mmap и FD в обратном порядке создания.

        Возвращает: None; после успешного закрытия списки ресурсов очищаются.
        Ошибки: OSError при закрытии FD.
        """
        for mapping in reversed(self.maps):
            mapping.close()
        for fd in reversed(self.fds):
            os.close(fd)
        self.maps.clear()
        self.fds.clear()


def read_text_bounded(path):
    """Читает ограниченный фрагмент UTF-8 файла.

    Параметры: path (str): путь к файлу.
    Возвращает: str: до 65536 символов.
    Ошибки: OSError при чтении; UnicodeError при неверном UTF-8.
    """
    with open(path, encoding='utf-8') as stream:
        return stream.read(65536)


def native_tcpretrans(cfg, deadline):
    """Собирает retransmit-события native backend и освобождает ресурсы.

    Параметры: cfg (argparse.Namespace): PID, cgroup и лимиты; deadline (float): монотонный дедлайн.
    Возвращает: dict: результат с событиями/ошибками; отказ verifier отделён от отсутствия прав, lost_events пока неизвестен.
    """
    entry = result('tcpretrans', 'network', None, backend='native_ebpf', status='unavailable')
    entry.update(start_time=utc(), events=[], scope='host-visible', attach_point='tcp/tcp_retransmit_skb', lost_events=None)
    if cfg.cgroup:
        entry['filter_limitation'] = 'Native retransmit tracing is system-wide; --cgroup filters process/cgroup metrics only'
    loader = None
    try:
        capability = native_capability()
        kprobe = not capability['tracefs']
        if kprobe:
            if not capability.get('btf_kprobe'):
                raise OSError(errno.ENOENT, 'tracepoint format and kernel BTF/kprobe PMU are unavailable')
            layout = kernel_sock_layout()
            trace_id = int(read_text_bounded('/sys/bus/event_source/devices/kprobe/type'))
            entry['attach_point'] = 'kprobe/tcp_retransmit_skb'
        else:
            root = capability['tracefs'] + '/events/tcp/tcp_retransmit_skb/'
            layout = tracepoint_layout(read_text_bounded(root + 'format'))
            trace_id = int(read_text_bounded(root + 'id'))
        if STOP or time.monotonic() >= deadline:
            entry.update(status='skipped', reason='interrupted' if STOP else 'budget_exhausted')
            return entry
        loader = NativeBPF()
        if kprobe:
            loader.open(layout, trace_id, cfg.pid, kprobe=True)
        else:
            loader.open(layout, trace_id, cfg.pid)
        if progress(cfg):
            progress(cfg).begin('tcpretrans')
        while not STOP and time.monotonic() < deadline and len(entry['events']) < cfg.max_events:
            for record in loader.read():
                try:
                    event = decode_retrans_event(record)
                except ValueError as exc:
                    if len(entry.setdefault('errors', [])) < 10:
                        entry['errors'].append(str(exc))
                    continue
                if event['pid'] not in getattr(cfg, 'observer_pids', {os.getpid()}):
                    entry['events'].append(event)
                if len(entry['events']) >= cfg.max_events:
                    break
            time.sleep(min(.02, max(0, deadline - time.monotonic())))
        entry.update(status='partial' if STOP or entry.get('errors') else 'ok', reason='interrupted' if STOP else 'parse_error' if entry.get('errors') else None,
                     truncated=len(entry['events']) >= cfg.max_events)
        entry['aggregation'] = aggregate_events(entry['events'], 'daddr')
    except (OSError, ValueError) as exc:
        entry['reason'] = 'verifier_rejected' if isinstance(exc, BPFVerifierError) else 'permission_denied' if isinstance(exc, OSError) and exc.errno in (1, 13) else 'unsupported'
        if isinstance(exc, BPFVerifierError):
            entry['verifier_log'] = exc.verifier_log
        entry['errors'] = [str(exc)]
    finally:
        if loader:
            loader.close()
        entry['end_time'] = utc()
    return entry


ANTI_PATTERNS = ['P1: CPU saturation with single-threaded bottleneck (load_avg > num_cpus but one CPU at 100%)',
 'P2: Memory pressure cascade (high dirty_ratio -> write stalls -> iowait -> apparent CPU saturation)',
 'P3: Swap death spiral (swap active + high major faults -> exponential performance degradation)',
 'P4: Network retransmit storm (cubic congestion control + high RTT -> throughput collapse)',
 'P5: Disk I/O amplification (random reads on rotational -> queue depth explosion)',
 'P6: Lock contention hotspot (futex_wait in stack traces -> serialized processing)',
 'P7: Container CPU throttling (cfs_quota too low -> periodic latency spikes)',
 'P8: NUMA imbalance (cross-node memory access -> 2-3x latency penalty)',
 'P9: IRQ imbalance (all interrupts on CPU 0 -> single-core bottleneck)',
 'P10: File descriptor exhaustion (approaching ulimit -> EMFILE errors)',
 'P11: Conntrack table overflow (nf_conntrack_max -> packet drops)',
 'P12: TIME_WAIT accumulation (short-lived connections -> port exhaustion)',
 'P13: Dirty page writeback storm (vm.dirty_ratio too high -> periodic I/O stalls)',
 'P14: THP defragmentation stall (transparent hugepages + fragmented memory -> allocation latency)',
 'P15: Scheduler migration overhead (processes bouncing between NUMA nodes)',
 'P16: I/O scheduler mismatch (using cfq on SSD instead of none/mq-deadline)',
 'P17: TCP buffer autotune failure (rmem/wmem too small for high-BDP links)',
 'P18: cgroup memory thrashing (near limit -> constant reclaim -> high PSI)',
 'P19: Kernel softlockup (debug logging storm -> RCU stall)',
 'P20: DNS resolution blocking (gethostlatency spikes -> application timeout cascade)',
 'P21: AppArmor per-packet overhead (LSM hooks on high-PPS workloads)',
 'P22: Per-process resource leak (FD count growing, RSS growing without release -> eventual OOM/EMFILE)',
 'P23: Application thread pool exhaustion (all threads blocked on I/O or locks -> request queuing)',
 'P24: Kafka/message-broker fsync storm (frequent fsync on rotational storage -> I/O queue saturation -> '
 'cascading latency to all co-located containers)',
 'P25: Docker log I/O contention (dockerd JSON-log writer + Fluent Bit log reader competing for same disk -> '
 'container stdout blocking -> application hangs)',
 'P26: HDD I/O scheduler mismatch (mq-deadline on rotational under containerized mixed workload -> no I/O '
 'fairness, use BFQ instead)',
 'P27: Page cache dirty write amplification (0% cache hit + high dirty page rate -> all I/O is '
 'write-through, no read caching benefit)']

RECOMMENDATION_CATALOG = [{'category': 'cpu',
  'type': 'fix',
  'title': 'CPU saturation detected — investigate high-CPU processes',
  'expected_impact': 'Identify CPU-bound bottleneck',
  'source': 'Brendan Gregg, Systems Performance ch.6',
  'commands': ['python3 linuxperf.py collect --profile deep --focus stacks'],
  'persistent': []},
 {'category': 'cpu',
  'type': 'optimization',
  'title': 'Reduce CFS scheduling latency for interactive workloads',
  'expected_impact': 'Lower tail latency for latency-sensitive workloads',
  'source': 'Linux kernel CFS documentation',
  'commands': ['sysctl -w kernel.sched_latency_ns=6000000',
               'sysctl -w kernel.sched_min_granularity_ns=750000'],
  'persistent': ["echo 'kernel.sched_latency_ns=6000000' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'kernel.sched_min_granularity_ns=750000' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'memory',
  'type': 'fix',
  'title': 'Reduce swappiness for database/latency-sensitive workloads',
  'expected_impact': 'Reduce swap-induced latency spikes',
  'source': 'Brendan Gregg, Systems Performance ch.7',
  'commands': ['sysctl -w vm.swappiness=10'],
  'persistent': ["echo 'vm.swappiness=10' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'memory',
  'type': 'fix',
  'title': 'Lower dirty_ratio to prevent write stalls',
  'expected_impact': 'Reduce periodic write stalls on heavy I/O workloads',
  'source': 'Linux kernel documentation (vm.dirty_ratio)',
  'commands': ['sysctl -w vm.dirty_ratio=10', 'sysctl -w vm.dirty_background_ratio=5'],
  'persistent': ["echo 'vm.dirty_ratio=10' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'vm.dirty_background_ratio=5' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'memory',
  'type': 'optimization',
  'title': 'Consider disabling memory overcommit for production',
  'expected_impact': 'Prevent OOM kills by enforcing commit limit',
  'source': 'Linux kernel documentation',
  'commands': ['sysctl -w vm.overcommit_memory=2'],
  'persistent': ["echo 'vm.overcommit_memory=2' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'memory',
  'type': 'fix',
  'title': 'Direct reclaim active — increase watermark reserves',
  'expected_impact': 'Trigger kswapd earlier, prevent applications from blocking on page reclaim',
  'source': 'Linux VM subsystem, Brendan Gregg Systems Performance ch.7',
  'commands': ['sysctl -w vm.watermark_scale_factor=200', 'sysctl -w vm.min_free_kbytes=131072'],
  'persistent': ["echo 'vm.watermark_scale_factor=200' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'vm.min_free_kbytes=131072' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'memory',
  'type': 'fix',
  'title': 'THP splits detected with THP=always — switch to madvise',
  'expected_impact': 'Eliminate THP compaction stalls and TLB thrashing from forced splits',
  'source': 'Linux THP documentation, PostgreSQL/MySQL best practices',
  'commands': ['echo madvise > /sys/kernel/mm/transparent_hugepage/enabled',
               'echo defer+madvise > /sys/kernel/mm/transparent_hugepage/defrag'],
  'persistent': []},
 {'category': 'memory',
  'type': 'fix',
  'title': 'NUMA node %d has %.1f%% miss ratio — cross-node memory access',
  'expected_impact': 'Reduce cross-NUMA memory access (30-50% latency penalty per hop)',
  'source': 'Linux NUMA, Brendan Gregg Systems Performance ch.7',
  'commands': ['# Pin critical processes to correct NUMA node:',
               '# numactl --cpunodebind=%d --membind=%d <command>',
               '# Or enable automatic NUMA balancing:',
               'sysctl -w kernel.numa_balancing=1'],
  'persistent': ["echo 'kernel.numa_balancing=1' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'memory',
  'type': 'fix',
  'title': 'Compaction stalls detected — memory fragmented',
  'expected_impact': 'Reduce allocation latency from memory fragmentation',
  'source': 'Linux VM compaction, kernel mm documentation',
  'commands': ['echo 1 > /proc/sys/vm/compact_memory', 'sysctl -w vm.extfrag_threshold=500'],
  'persistent': []},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Enable BBR congestion control',
  'expected_impact': '2-3x throughput on high-BDP links, lower retransmits',
  'source': 'Google BBR paper, Brendan Gregg Systems Performance ch.10',
  'commands': ['sysctl -w net.core.default_qdisc=fq', 'sysctl -w net.ipv4.tcp_congestion_control=bbr'],
  'persistent': ["echo 'net.core.default_qdisc=fq' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'net.ipv4.tcp_congestion_control=bbr' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Investigate TCP retransmissions',
  'expected_impact': 'Identify network path issues causing packet loss',
  'source': 'Brendan Gregg, Systems Performance ch.10',
  'commands': ['python3 linuxperf.py collect --profile deep --focus network'],
  'persistent': []},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Increase listen backlog for high-traffic servers',
  'expected_impact': 'Prevent connection drops under burst load',
  'source': 'Linux networking documentation',
  'commands': ['sysctl -w net.core.somaxconn=4096'],
  'persistent': ["echo 'net.core.somaxconn=4096' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Increase TCP receive buffer sizes',
  'expected_impact': 'Better throughput on high-BDP paths',
  'source': 'Brendan Gregg, Systems Performance ch.10',
  'commands': ["sysctl -w net.ipv4.tcp_rmem='4096 87380 6291456'"],
  'persistent': ["echo 'net.ipv4.tcp_rmem=4096 87380 6291456' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Increase TCP send buffer sizes',
  'expected_impact': 'Better throughput on high-BDP paths',
  'source': 'Brendan Gregg, Systems Performance ch.10',
  'commands': ["sysctl -w net.ipv4.tcp_wmem='4096 65536 6291456'"],
  'persistent': ["echo 'net.ipv4.tcp_wmem=4096 65536 6291456' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Enable TIME_WAIT socket reuse',
  'expected_impact': 'Reduce TIME_WAIT socket accumulation on busy servers',
  'source': 'Brendan Gregg, Systems Performance ch.10',
  'commands': ['sysctl -w net.ipv4.tcp_tw_reuse=1'],
  'persistent': ["echo 'net.ipv4.tcp_tw_reuse=1' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Increase SYN backlog for high-connection-rate servers',
  'expected_impact': 'Handle connection bursts without SYN drops',
  'source': 'Brendan Gregg, Systems Performance ch.10',
  'commands': ['sysctl -w net.ipv4.tcp_max_syn_backlog=8192'],
  'persistent': ["echo 'net.ipv4.tcp_max_syn_backlog=8192' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Conntrack table approaching capacity',
  'expected_impact': 'Prevent conntrack table full drops',
  'source': 'Linux conntrack documentation',
  'commands': ['sysctl -w net.netfilter.nf_conntrack_max=%d'],
  'persistent': ["echo 'net.netfilter.nf_conntrack_max=%d' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Increase ring buffer on %s (rx_discards detected)',
  'expected_impact': 'Reduce NIC-level packet drops during traffic bursts',
  'source': 'Brendan Gregg, Systems Performance ch.10',
  'commands': ['ethtool -G %s rx %d'],
  'persistent': []},
 {'category': 'network',
  'type': 'fix',
  'title': 'Listen queue overflows detected — increase backlog and enable SO_REUSEPORT',
  'expected_impact': 'Eliminate accept queue overflow drops under burst load',
  'source': 'Linux networking, SO_REUSEPORT documentation',
  'commands': ['sysctl -w net.core.somaxconn=65535', '# For nginx: listen 80 reuseport backlog=8192;'],
  'persistent': ["echo 'net.core.somaxconn=65535' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Increase netdev_max_backlog (softnet drops detected)',
  'expected_impact': 'Reduce packet drops between NIC and kernel processing',
  'source': 'RHEL Network Performance Tuning, Brendan Gregg Systems Performance ch.10',
  'commands': ['sysctl -w net.core.netdev_max_backlog=10000'],
  'persistent': ["echo 'net.core.netdev_max_backlog=10000' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Increase socket buffer maximums (rmem_max/wmem_max)',
  'expected_impact': 'Allow applications to request larger socket buffers (required for high-BDP and UDP '
                     'workloads)',
  'source': 'ESnet Fasterdata, RHEL Network Tuning Guide',
  'commands': ['sysctl -w net.core.rmem_max=16777216', 'sysctl -w net.core.wmem_max=16777216'],
  'persistent': ["echo 'net.core.rmem_max=16777216' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'net.core.wmem_max=16777216' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Expand ephemeral port range',
  'expected_impact': 'More ports for outbound connections (prevents EADDRNOTAVAIL under load)',
  'source': 'RHEL 9 Network Performance Tuning',
  'commands': ["sysctl -w net.ipv4.ip_local_port_range='1024 65535'"],
  'persistent': ["echo 'net.ipv4.ip_local_port_range=1024 65535' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Disable TCP slow start after idle for persistent connections',
  'expected_impact': 'Prevent congestion window reset on idle keepalive connections',
  'source': 'Cloudflare TCP optimization, RFC 7661',
  'commands': ['sysctl -w net.ipv4.tcp_slow_start_after_idle=0'],
  'persistent': ["echo 'net.ipv4.tcp_slow_start_after_idle=0' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Enable TCP Fast Open (client + server)',
  'expected_impact': 'Save 1 RTT on reconnections (especially for web servers)',
  'source': 'RHEL 9 Network Tuning, Linux tcp(7)',
  'commands': ['sysctl -w net.ipv4.tcp_fastopen=3'],
  'persistent': ["echo 'net.ipv4.tcp_fastopen=3' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Increase netdev_budget (time_squeeze detected)',
  'expected_impact': 'Allow kernel more time/packets per NAPI poll cycle',
  'source': 'Brendan Gregg USE Method, Packagecloud Linux Networking Stack',
  'commands': ['sysctl -w net.core.netdev_budget=600', 'sysctl -w net.core.netdev_budget_usecs=8000'],
  'persistent': ["echo 'net.core.netdev_budget=600' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'net.core.netdev_budget_usecs=8000' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Increase rmem_max for UDP workloads (RcvbufErrors detected)',
  'expected_impact': 'Allow UDP sockets to use larger receive buffers, prevent drops',
  'source': 'Packagecloud Linux Networking Stack Monitoring',
  'commands': ['sysctl -w net.core.rmem_max=26214400'],
  'persistent': ["echo 'net.core.rmem_max=26214400' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'Application not consuming TCP data fast enough (Recv-Q saturation)',
  'expected_impact': 'Prevent TCP zero-window stalls and improve application throughput',
  'source': 'Linux TCP socket buffers, Brendan Gregg Systems Performance ch.10',
  'commands': ["ss -tnp | awk '$2 > 65536 {print}'",
               '# Identify the process and optimize its read loop or add worker threads'],
  'persistent': []},
 {'category': 'network',
  'type': 'fix',
  'title': 'Accept queue %s is %.0f%% full — enable SO_REUSEPORT',
  'expected_impact': 'Distribute accept() across threads, prevent SYN drops',
  'source': 'Linux SO_REUSEPORT, Cloudflare SYN packet handling',
  'commands': ['# Enable SO_REUSEPORT so each worker thread gets its own accept queue:',
               '# nginx: listen <port> reuseport;',
               '# Go:    net.ListenConfig{Control: func(...) { unix.SetsockoptInt(fd, unix.SOL_SOCKET, '
               'unix.SO_REUSEPORT, 1) }}',
               'sysctl -w net.core.somaxconn=%d'],
  'persistent': []},
 {'category': 'network',
  'type': 'fix',
  'title': 'TCP zero-window drops detected — application not consuming data fast enough',
  'expected_impact': 'Larger receive buffers give the application more headroom before window closes',
  'source': 'Linux TCP flow control, Brendan Gregg Systems Performance ch.10',
  'commands': ["sysctl -w net.ipv4.tcp_rmem='4096 131072 16777216'",
               '# Profile the application: is read() blocking on disk, locks, or compute?'],
  'persistent': ["echo 'net.ipv4.tcp_rmem=4096 131072 16777216' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'optimization',
  'title': 'Increase ARP neighbor table for container/K8s environments',
  'expected_impact': "Prevent 'neighbour table overflow' errors in large subnets or container environments",
  'source': 'Kubernetes networking, Linux neigh(7)',
  'commands': ['sysctl -w net.ipv4.neigh.default.gc_thresh1=2048',
               'sysctl -w net.ipv4.neigh.default.gc_thresh2=4096',
               'sysctl -w net.ipv4.neigh.default.gc_thresh3=8192'],
  'persistent': ["echo 'net.ipv4.neigh.default.gc_thresh1=2048' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'net.ipv4.neigh.default.gc_thresh2=4096' >> /etc/sysctl.d/99-linuxperf.conf",
                 "echo 'net.ipv4.neigh.default.gc_thresh3=8192' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'network',
  'type': 'fix',
  'title': 'TCP memory pressure detected (PruneCalled) — increase tcp_mem',
  'expected_impact': 'Prevent kernel from pruning TCP receive buffers under high connection count',
  'source': 'Linux TCP memory management, Brendan Gregg Systems Performance ch.10',
  'commands': ["sysctl -w net.ipv4.tcp_mem='1048576 2097152 4194304'"],
  'persistent': ["echo 'net.ipv4.tcp_mem=1048576 2097152 4194304' >> /etc/sysctl.d/99-linuxperf.conf"]},
 {'category': 'disk',
  'type': 'optimization',
  'title': 'Switch %s to mq-deadline scheduler (SSD)',
  'expected_impact': 'Lower latency for SSD workloads',
  'source': 'Brendan Gregg, Systems Performance ch.9',
  'commands': ['echo mq-deadline > /sys/block/%s/queue/scheduler'],
  'persistent': ['echo \'ACTION=="add|change", KERNEL=="%s", ATTR{queue/scheduler}="mq-deadline"\' >> '
                 '/etc/udev/rules.d/60-scheduler.rules']},
 {'category': 'disk',
  'type': 'optimization',
  'title': 'Switch %s to BFQ scheduler (HDD)',
  'expected_impact': 'Better I/O fairness for HDD workloads',
  'source': 'Brendan Gregg, Systems Performance ch.9',
  'commands': ['echo bfq > /sys/block/%s/queue/scheduler'],
  'persistent': ['echo \'ACTION=="add|change", KERNEL=="%s", ATTR{queue/scheduler}="bfq"\' >> '
                 '/etc/udev/rules.d/60-scheduler.rules']},
 {'category': 'memory',
  'type': 'optimization',
  'title': 'Consider disabling THP for latency-sensitive workloads',
  'expected_impact': 'Eliminate THP compaction stalls and latency spikes',
  'source': 'Brendan Gregg, Systems Performance ch.7',
  'commands': ['echo madvise > /sys/kernel/mm/transparent_hugepage/enabled'],
  'persistent': ["echo 'echo madvise > /sys/kernel/mm/transparent_hugepage/enabled' >> /etc/rc.local"]},
 {'category': 'memory',
  'type': 'optimization',
  'title': 'Increase vm.min_free_kbytes for large memory system',
  'expected_impact': 'Reduce direct reclaim stalls under memory pressure',
  'source': 'Brendan Gregg, Systems Performance ch.7',
  'commands': ['sysctl -w vm.min_free_kbytes=131072'],
  'persistent': ["echo 'vm.min_free_kbytes=131072' >> /etc/sysctl.d/99-linuxperf.conf"]}]

PID_TOOLS = ['runqlat', 'cpudist', 'ext4slower', 'fileslower', 'tcpconnlat', 'gethostlatency', 'profile', 'offcputime', 'opensnoop', 'killsnoop', 'statsnoop', 'capable', 'filelife', 'runqslower', 'tcpconnect', 'tcpaccept', 'tcplife', 'ext4dist', 'xfsdist', 'stackcount', 'biotop', 'syscount', 'funccount', 'memleak']

# Пороговый каталог: неизвестные значения не подменяются измеренным нулём.
RULES = [('cpu_utilization', 'cpu', 80.0, 95.0, '%'),
 ('cpu_iowait', 'cpu', 10.0, 30.0, '%'),
 ('load_average', 'cpu', 2.0, 4.0, 'per_cpu'),
 ('memory_utilization', 'memory', 85.0, 95.0, '%'),
 ('swap_usage', 'memory', 10.0, 50.0, '%'),
 ('memory_psi_pressure', 'memory', 5.0, 25.0, '%'),
 ('direct_reclaim_rate', 'memory', 10.0, 1000.0, 'pages/s'),
 ('compaction_stall_rate', 'memory', 1.0, 100.0, '/s'),
 ('thp_split_rate', 'memory', 1.0, 100.0, '/s'),
 ('numa_miss_ratio', 'memory', 5.0, 20.0, '%'),
 ('tcp_retransmits', 'network', 10.0, 50.0, '/s'),
 ('tcp_timewait', 'network', 5000.0, 20000.0, 'sockets'),
 ('disk_utilization', 'disk', 70.0, 90.0, '%'),
 ('cpu_throttling', 'container', 100.0, 1000.0, 'periods'),
 ('container_memory_usage', 'container', 80.0, 95.0, '%'),
 ('biolatency_p99_ssd', 'disk', 5.0, 25.0, 'ms'),
 ('biolatency_p99_hdd', 'disk', 50.0, 200.0, 'ms'),
 ('runqlat_p99', 'cpu', 10.0, 50.0, 'ms'),
 ('dns_latency_p99', 'network', 50.0, 200.0, 'ms'),
 ('cache_miss_ratio', 'memory', 5.0, 15.0, '%'),
 ('cpu_psi_pressure', 'cpu', 5.0, 25.0, '%'),
 ('io_psi_pressure', 'disk', 10.0, 50.0, '%'),
 ('disk_avg_latency', 'disk', 5.0, 50.0, 'ms'),
 ('network_errors_per_sec', 'network', 10.0, 100.0, '/s'),
 ('conntrack_usage_pct', 'network', 70.0, 90.0, '%'),
 ('softnet_dropped', 'network', 1.0, 100.0, '/s'),
 ('listen_overflows', 'network', 1.0, 100.0, '/s'),
 ('nic_rx_discards', 'network', 100.0, 10000.0, 'packets'),
 ('tcp_close_wait', 'network', 1.0, 100.0, 'sockets'),
 ('softnet_time_squeeze', 'network', 1.0, 100.0, '/s'),
 ('tcp_abort_on_memory', 'network', 0.1, 1.0, '/s'),
 ('irq_imbalance', 'network', 5.0, 20.0, 'ratio'),
 ('udp_rcvbuf_errors', 'network', 1.0, 100.0, '/s'),
 ('tcp_rcvq_drop', 'network', 1.0, 100.0, '/s'),
 ('tcp_zero_window_drop', 'network', 1.0, 50.0, '/s'),
 ('listen_queue_saturation', 'network', 70.0, 90.0, '%'),
 ('gpu_nic_cross_numa', 'system', 1.0, 1.0, 'pairs')]

# Command specifications are embedded: deployment requires only this file.
# Endless tracers intentionally omit duration flags and use command() SIGINT.
# biosnoop -d filters a disk; stackcount needs a probe pattern and -D duration.
TOOLS = {'runqlat': ('cpu', ['-m', '{duration}', '1']),
 'runqlen': ('cpu', ['{duration}', '1']),
 'cpudist': ('cpu', ['{duration}', '1']),
 'biolatency': ('disk', ['-D', '{duration}', '1']),
 'biosnoop': ('disk', []),
 'ext4slower': ('disk', ['1']),
 'fileslower': ('disk', ['1']),
 'bitesize': ('disk', ['{duration}', '1']),
 'tcpconnlat': ('network', []),
 'tcpretrans': ('network', []),
 'tcprtt': ('network', ['-d', '{duration}']),
 'gethostlatency': ('network', []),
 'tcpdrop': ('network', []),
 'tcpstates': ('network', []),
 'profile': ('stacktrace', ['-af', '{duration}']),
 'offcputime': ('stacktrace', ['-fK', '{duration}']),
 'cachestat': ('memory', ['{duration}', '1']),
 'execsnoop': ('process', []),
 'hardirqs': ('cpu', ['{duration}', '1']),
 'softirqs': ('cpu', ['{duration}', '1']),
 'opensnoop': ('process', ['-d', '{duration}']),
 'killsnoop': ('process', []),
 'threadsnoop': ('process', []),
 'syncsnoop': ('process', []),
 'exitsnoop': ('process', []),
 'statsnoop': ('process', []),
 'capable': ('process', []),
 'filelife': ('disk', []),
 'mountsnoop': ('disk', []),
 'btrfsslower': ('disk', ['1']),
 'xfsslower': ('disk', ['1']),
 'nfsslower': ('disk', ['1']),
 'zfsslower': ('disk', ['1']),
 'mdflush': ('disk', []),
 'runqslower': ('cpu', ['10000']),
 'cpufreq': ('cpu', []),
 'cpuunclaimed': ('cpu', ['{duration}', '1']),
 'tcpconnect': ('network', []),
 'tcpaccept': ('network', []),
 'tcplife': ('network', []),
 'udpconnect': ('network', []),
 'sofdsnoop': ('network', []),
 'sockstat': ('network', []),
 'skbdrop': ('network', []),
 'oomkill': ('memory', []),
 'shmsnoop': ('memory', []),
 'drsnoop': ('memory', []),
 'numamove': ('memory', []),
 'llcstat': ('cpu', ['{duration}']),
 'ext4dist': ('disk', ['{duration}', '1']),
 'btrfsdist': ('disk', ['{duration}', '1']),
 'xfsdist': ('disk', ['{duration}', '1']),
 'nfsdist': ('disk', ['{duration}', '1']),
 'zfsdist': ('disk', ['{duration}', '1']),
 'tcpsynbl': ('network', []),
 'scsilatency': ('disk', ['{duration}', '1']),
 'nvmelatency': ('disk', ['{duration}', '1']),
 'wakeuptime': ('stacktrace', ['-f', '{duration}']),
 'offwaketime': ('stacktrace', ['-fK', '{duration}']),
 'biostacks': ('stacktrace', ['-f', '{duration}']),
 'stackcount': ('stacktrace', ['-f', '-K', '-D', '{duration}', 't:sched:sched_switch']),
 'biotop': ('disk', ['{duration}', '1']),
 'slabratetop': ('memory', ['{duration}', '1']),
 'vfsstat': ('disk', ['{duration}', '1']),
 'syscount': ('process', ['-d', '{duration}']),
 'funccount': ('cpu', ['-d', '{duration}', 'tcp_*']),
 'memleak': ('memory', ['-a', '{duration}']),
 'ss': ('network', ['-ltn']),
 'ethtool': ('network', ['--version']),
 'nvidia-smi': ('system',
                ['--query-gpu=name,pci.bus_id,utilization.gpu,memory.used,memory.total,driver_version,utilization.memory,temperature.gpu,power.draw,index',
                 '--format=csv,noheader,nounits']),
 'dmesg': ('system', ['--level=err,warn', '--nopager']),
 'df': ('system', ['-P', '-T'])}

if __name__ == "__main__":
    sys.exit(main())
