import logging
import json
import re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection
from services.inspection_service import _execute_shell_script

logger = logging.getLogger(__name__)

# Server platforms (Linux)
_SERVER_PLATFORMS = {'linux', 'ubuntu', 'centos', 'debian', 'redhat'}

def record_device_telemetry_snapshot() -> dict:
    """
    Scheduled background task:
    1. Query all online Linux servers.
    2. Concurrently execute the comprehensive inspection script 'insp_linux_full' on each server.
    3. Parse the --- METRICS --- section.
    4. Store the raw metrics in `device_telemetry_samples`.
    5. Clean up old samples (older than 7 days) and run rollup for older data.
    """
    conn = get_db_connection()
    try:
        # Check if insp_linux_full script exists
        script_row = conn.execute("SELECT content FROM scripts WHERE id = ?", ("insp_linux_full",)).fetchone()
        if not script_row:
            logger.warning("[Telemetry] 'insp_linux_full' script not found. Telemetry collection skipped.")
            return {'success': False, 'message': 'insp_linux_full script not found'}
        script_content = script_row['content']

        # Query online Linux devices
        # platform field is text, check case-insensitively
        devices = []
        rows = conn.execute("SELECT * FROM devices WHERE status = 'online'").fetchall()
        for r in rows:
            d = dict(r)
            plat = str(d.get('platform') or '').lower()
            category = str(d.get('device_category') or '').lower()
            if plat in _SERVER_PLATFORMS or 'server' in category:
                devices.append(d)

        if not devices:
            return {'success': True, 'message': 'No online Linux servers found', 'samples_added': 0}

        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        
        # Concurrently execute
        results = []
        max_workers = min(10, len(devices))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_execute_shell_script, d['ip_address'], script_content, d): d
                for d in devices
            }
            for fut in as_completed(futures):
                d = futures[fut]
                try:
                    output = fut.result()
                    results.append((d, output))
                except Exception as e:
                    logger.error(f"[Telemetry] Failed to collect telemetry for {d.get('hostname') or d['ip_address']}: {e}")
                    results.append((d, f"ERROR: {str(e)}"))

        # Parse and insert
        samples_inserted = 0
        insert_rows = []
        for d, output in results:
            if "ERROR:" in output:
                logger.warning(f"[Telemetry] SSH failed for {d.get('hostname') or d['ip_address']}: {output}")
                continue

            # Parse metrics from --- METRICS --- block
            parsed_metrics = {}
            metrics_block_started = False
            for line in output.splitlines():
                line = line.strip()
                if line == "--- METRICS ---":
                    metrics_block_started = True
                    continue
                if metrics_block_started:
                    if line.startswith("==="):
                        metrics_block_started = False
                        continue
                    if ":" in line:
                        parts = line.split(":", 1)
                        m_key = parts[0].strip()
                        m_val_str = parts[1].strip()
                        try:
                            parsed_metrics[m_key] = float(m_val_str)
                        except ValueError:
                            parsed_metrics[m_key] = m_val_str

            if not parsed_metrics:
                logger.warning(f"[Telemetry] No metrics parsed from {d.get('hostname') or d['ip_address']}")
                continue

            def _get_float(key):
                val = parsed_metrics.get(key)
                if val is None or val == '':
                    return None
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            def _get_int(key):
                val = parsed_metrics.get(key)
                if val is None or val == '':
                    return None
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    return None

            insert_rows.append((
                ts,
                d['id'],
                _get_float('cpu_load'),
                _get_float('cpu_util'),
                _get_float('mem_avail'),
                _get_float('swap_util'),
                _get_float('io_wait'),
                _get_float('io_latency'),
                _get_float('disk_util'),
                _get_float('inode_util'),
                _get_int('tcp_conns'),
                _get_float('tcp_retrans'),
                _get_int('tcp_estab'),
                _get_int('tcp_time_wait'),
                _get_int('tcp_close_wait'),
                _get_int('tcp_syn_recv'),
                _get_int('tcp_listen'),
                _get_int('process_health'),
                _get_int('service_sshd') or 0,
                _get_int('service_crond') or 0,
                _get_int('service_docker') or 0
            ))

        if insert_rows:
            conn.executemany(
                '''
                INSERT INTO device_telemetry_samples (
                    ts, device_id, cpu_load, cpu_util, mem_avail, swap_util,
                    io_wait, io_latency, disk_util, inode_util, tcp_conns, tcp_retrans,
                    tcp_estab, tcp_time_wait, tcp_close_wait, tcp_syn_recv, tcp_listen,
                    process_health, service_sshd, service_crond, service_docker
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ts, device_id) DO UPDATE SET
                    cpu_load=excluded.cpu_load,
                    cpu_util=excluded.cpu_util,
                    mem_avail=excluded.mem_avail,
                    swap_util=excluded.swap_util,
                    io_wait=excluded.io_wait,
                    io_latency=excluded.io_latency,
                    disk_util=excluded.disk_util,
                    inode_util=excluded.inode_util,
                    tcp_conns=excluded.tcp_conns,
                    tcp_retrans=excluded.tcp_retrans,
                    tcp_estab=excluded.tcp_estab,
                    tcp_time_wait=excluded.tcp_time_wait,
                    tcp_close_wait=excluded.tcp_close_wait,
                    tcp_syn_recv=excluded.tcp_syn_recv,
                    tcp_listen=excluded.tcp_listen,
                    process_health=excluded.process_health,
                    service_sshd=excluded.service_sshd,
                    service_crond=excluded.service_crond,
                    service_docker=excluded.service_docker
                ''',
                insert_rows
            )
            conn.commit()
            samples_inserted = len(insert_rows)

        # Enforce retention (7 days for raw samples)
        now_dt = datetime.now(timezone.utc)
        raw_cutoff = (now_dt - timedelta(days=7)).replace(microsecond=0).isoformat()
        conn.execute("DELETE FROM device_telemetry_samples WHERE ts < ?", (raw_cutoff,))
        conn.commit()

        # Perform rollups
        _run_device_telemetry_rollup(conn)

        return {'success': True, 'samples_added': samples_inserted}
    except Exception as e:
        logger.error(f"[Telemetry] Exception in record_device_telemetry_snapshot: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()

def _run_device_telemetry_rollup(conn):
    """
    Rolls up raw samples from the past 2 hours into the hourly table.
    Enforces the hourly retention window of 90 days.
    """
    now = datetime.now(timezone.utc)
    # Rollup past 2 hours to ensure completeness
    rollup_start = (now - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0).isoformat()
    rollup_cutoff = (now - timedelta(days=90)).replace(microsecond=0).isoformat()

    conn.execute(
        '''
        INSERT INTO device_telemetry_hourly (
            ts_hour, device_id, samples,
            avg_cpu_load, max_cpu_load,
            avg_cpu_util, max_cpu_util,
            avg_mem_avail, max_mem_avail,
            avg_swap_util, max_swap_util,
            avg_io_wait, max_io_wait,
            avg_io_latency, max_io_latency,
            avg_disk_util, max_disk_util,
            avg_inode_util, max_inode_util,
            avg_tcp_conns, max_tcp_conns,
            avg_tcp_retrans, max_tcp_retrans,
            avg_tcp_estab, max_tcp_estab,
            avg_tcp_time_wait, max_tcp_time_wait,
            avg_tcp_close_wait, max_tcp_close_wait,
            avg_tcp_syn_recv, max_tcp_syn_recv,
            avg_tcp_listen, max_tcp_listen,
            avg_process_health
        )
        SELECT
            substr(ts, 1, 13) || ':00:00+00:00' AS ts_hour,
            device_id,
            COUNT(*) AS samples,
            AVG(cpu_load), MAX(cpu_load),
            AVG(cpu_util), MAX(cpu_util),
            AVG(mem_avail), MAX(mem_avail),
            AVG(swap_util), MAX(swap_util),
            AVG(io_wait), MAX(io_wait),
            AVG(io_latency), MAX(io_latency),
            AVG(disk_util), MAX(disk_util),
            AVG(inode_util), MAX(inode_util),
            AVG(tcp_conns), MAX(tcp_conns),
            AVG(tcp_retrans), MAX(tcp_retrans),
            AVG(tcp_estab), MAX(tcp_estab),
            AVG(tcp_time_wait), MAX(tcp_time_wait),
            AVG(tcp_close_wait), MAX(tcp_close_wait),
            AVG(tcp_syn_recv), MAX(tcp_syn_recv),
            AVG(tcp_listen), MAX(tcp_listen),
            AVG(process_health)
        FROM device_telemetry_samples
        WHERE ts >= ?
        GROUP BY ts_hour, device_id
        ON CONFLICT(ts_hour, device_id) DO UPDATE SET
            samples=excluded.samples,
            avg_cpu_load=excluded.avg_cpu_load, max_cpu_load=excluded.max_cpu_load,
            avg_cpu_util=excluded.avg_cpu_util, max_cpu_util=excluded.max_cpu_util,
            avg_mem_avail=excluded.avg_mem_avail, max_mem_avail=excluded.max_mem_avail,
            avg_swap_util=excluded.avg_swap_util, max_swap_util=excluded.max_swap_util,
            avg_io_wait=excluded.avg_io_wait, max_io_wait=excluded.max_io_wait,
            avg_io_latency=excluded.avg_io_latency, max_io_latency=excluded.max_io_latency,
            avg_disk_util=excluded.avg_disk_util, max_disk_util=excluded.max_disk_util,
            avg_inode_util=excluded.avg_inode_util, max_inode_util=excluded.max_inode_util,
            avg_tcp_conns=excluded.avg_tcp_conns, max_tcp_conns=excluded.max_tcp_conns,
            avg_tcp_retrans=excluded.avg_tcp_retrans, max_tcp_retrans=excluded.max_tcp_retrans,
            avg_tcp_estab=excluded.avg_tcp_estab, max_tcp_estab=excluded.max_tcp_estab,
            avg_tcp_time_wait=excluded.avg_tcp_time_wait, max_tcp_time_wait=excluded.max_tcp_time_wait,
            avg_tcp_close_wait=excluded.avg_tcp_close_wait, max_tcp_close_wait=excluded.max_tcp_close_wait,
            avg_tcp_syn_recv=excluded.avg_tcp_syn_recv, max_tcp_syn_recv=excluded.max_tcp_syn_recv,
            avg_tcp_listen=excluded.avg_tcp_listen, max_tcp_listen=excluded.max_tcp_listen,
            avg_process_health=excluded.avg_process_health
        ''',
        (rollup_start,)
    )
    conn.commit()

    conn.execute("DELETE FROM device_telemetry_hourly WHERE ts_hour < ?", (rollup_cutoff,))
    conn.commit()
