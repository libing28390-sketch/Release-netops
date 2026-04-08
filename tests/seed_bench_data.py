"""
NetPilot 压测数据灌入脚本
灌入 500 台网络设备 + 1000 台服务器 + 关联数据（告警、审计、合规、配置快照）
直接写 DB，不走 API。
"""
import os
import sys
import uuid
import random
import json
from datetime import datetime, timedelta, timezone

# 确保可以 import backend 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
from database import get_db_connection

# ── 常量 ─────────────────────────────────────────────────────
SITES = [
    'BJ-DC1', 'BJ-DC2', 'SH-DC1', 'SH-DC2', 'GZ-DC1',
    'SZ-DC1', 'CD-DC1', 'WH-DC1', 'NJ-DC1', 'HZ-DC1',
]
ROLES = ['core', 'distribution', 'access', 'border', 'wan', 'spine', 'leaf']
PLATFORMS = [
    ('cisco_ios', 'Cisco', ['ISR4451', 'ISR4331', 'C9300-48P', 'C9200-24T', 'C3850-48T']),
    ('cisco_nxos', 'Cisco', ['N9K-C93180YC', 'N9K-C9336C', 'N5K-C5672UP']),
    ('cisco_xe', 'Cisco', ['C9300-48U', 'C9500-40X', 'ASR1001-X']),
    ('huawei_vrp', 'Huawei', ['S5735-L48T4X', 'S6730-H48X6C', 'CE6881-48S6CQ', 'NE40E-X8']),
    ('hp_comware', 'H3C', ['S6850-56HF', 'S12508M-AF', 'MSR3620-XS']),
    ('arista_eos', 'Arista', ['DCS-7050CX3-32S', 'DCS-7280CR3-32P4', 'DCS-7020TR-48']),
    ('juniper_junos', 'Juniper', ['QFX5120-48T', 'EX4300-48MP', 'MX204']),
]
DEPARTMENTS = ['网络运维', '数据中心', '安全', '系统运维', 'IT支持', '研发', '测试']
DATACENTERS = ['北京IDC-A', '北京IDC-B', '上海IDC-A', '广州IDC', '深圳IDC']
SERVER_VENDORS = ['Dell', 'HPE', 'Lenovo', 'Huawei', 'Inspur', 'Supermicro']
SERVER_MODELS = [
    'PowerEdge R750', 'PowerEdge R650', 'ProLiant DL380 Gen10',
    'ProLiant DL360 Gen10', 'ThinkSystem SR650 V2', 'FusionServer 2288H V6',
    'NF5280M6', 'X11DPH-T',
]
COMPLIANCE_RULES = [
    ('NTP_CHECK', '未配置NTP同步', 'ntp', 'NTP服务器未配置或不可达'),
    ('ACL_CHECK', '缺少管理面ACL', 'security', '管理接口未配置访问控制列表'),
    ('SNMPv3_CHECK', '使用SNMPv2c', 'security', 'SNMP使用v2c社区字符串，建议升级v3'),
    ('SYSLOG_CHECK', '未配置Syslog', 'logging', '未配置远程Syslog服务器'),
    ('BANNER_CHECK', '缺少登录Banner', 'security', '未配置登录警告Banner'),
    ('OSPF_AUTH', 'OSPF未启用认证', 'routing', 'OSPF邻居未配置MD5认证'),
    ('BGP_PASSWORD', 'BGP未配置密码', 'routing', 'BGP邻居未配置TCP MD5认证'),
    ('UNUSED_INTF', '存在未关闭的空接口', 'security', '空闲接口未shutdown'),
]
ALERT_TITLES = [
    ('CPU利用率超过阈值', 'threshold', 'warning'),
    ('内存利用率超过阈值', 'threshold', 'warning'),
    ('接口 GigabitEthernet0/1 Down', 'interface', 'major'),
    ('接口 GigabitEthernet0/2 Flapping', 'interface', 'warning'),
    ('设备不可达', 'reachability', 'critical'),
    ('BGP邻居断开', 'protocol', 'critical'),
    ('OSPF邻居状态变化', 'protocol', 'major'),
    ('配置变更检测', 'config', 'warning'),
    ('电源冗余丢失', 'hardware', 'major'),
    ('风扇故障', 'hardware', 'critical'),
]
AUDIT_EVENTS = [
    ('device.backup', 'config', 'info', '执行配置备份'),
    ('device.connect', 'connection', 'info', '设备连接测试'),
    ('user.login', 'auth', 'info', '用户登录成功'),
    ('user.login_failed', 'auth', 'warning', '用户登录失败'),
    ('device.create', 'inventory', 'info', '创建设备'),
    ('device.update', 'inventory', 'info', '更新设备信息'),
    ('automation.execute', 'automation', 'info', '执行自动化任务'),
    ('compliance.scan', 'compliance', 'info', '执行合规扫描'),
    ('alert.acknowledge', 'alert', 'info', '确认告警'),
    ('config.restore', 'config', 'warning', '配置回滚操作'),
]


def _uid():
    return str(uuid.uuid4())


def _rand_ip(prefix_idx):
    """生成 10.{prefix_idx}.x.x 段的 IP"""
    return f"10.{prefix_idx}.{random.randint(1,254)}.{random.randint(1,254)}"


def _rand_time(days_back=30):
    """过去 N 天内的随机时间"""
    dt = datetime.now(timezone.utc) - timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )
    return dt.replace(microsecond=0).isoformat()


def _fake_config(hostname, platform, vendor):
    """生成 200-400 行的模拟配置"""
    lines = [
        f"! Configuration for {hostname}",
        f"! Platform: {platform}",
        f"! Generated: {datetime.now().isoformat()}",
        "!",
        f"hostname {hostname}",
        "!",
    ]
    # 接口
    for i in range(random.randint(8, 48)):
        lines.extend([
            f"interface GigabitEthernet0/{i}",
            f" description Link-{random.choice(['Uplink','Server','User','WAN','Unused'])}",
            f" ip address 192.168.{random.randint(1,254)}.{random.randint(1,254)} 255.255.255.0",
            " no shutdown" if random.random() > 0.2 else " shutdown",
            "!",
        ])
    # 路由
    lines.extend([
        "router ospf 1",
        f" router-id {random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
        " network 10.0.0.0 0.255.255.255 area 0",
        "!",
        "ip route 0.0.0.0 0.0.0.0 10.0.0.1",
        "!",
        f"ntp server 10.0.0.{random.randint(1,5)}",
        f"snmp-server community {random.choice(['public','netops-ro','monitor'])} RO",
        "!",
        "end",
    ])
    return "\n".join(lines)


def seed_devices(conn, count=500):
    """灌入网络设备"""
    print(f"  灌入 {count} 台网络设备...")
    devices = []
    for i in range(count):
        plat_info = random.choice(PLATFORMS)
        platform, vendor, models = plat_info
        did = _uid()
        hostname = f"{random.choice(['SW','RT','FW','CR','DS','AS'])}-{random.choice(SITES)}-{i+1:04d}"
        status = random.choices(['online', 'offline'], weights=[90, 10])[0]
        devices.append((
            did, hostname, _rand_ip(random.randint(1, 50)), platform, status,
            random.choice(['compliant', 'non-compliant', 'unknown']),
            f"SN{random.randint(100000,999999)}", random.choice(models),
            f"{random.randint(12,17)}.{random.randint(1,9)}.{random.randint(1,4)}",
            random.choice(ROLES), random.choice(SITES),
            f"{random.randint(1,365)}d {random.randint(0,23)}h",
            'ssh', '', '',  # connection_method, username, password
            '', '[]',  # current_config, config_history
            random.randint(5, 95) if status == 'online' else 0,
            random.randint(20, 90) if status == 'online' else 0,
            '[]', 'public', 161, '[]', '[]',
            random.randint(25, 55), random.choice(['ok', 'warning']),
            random.choice(['redundant', 'single', 'ok']),
            hostname, random.choice(SITES), 'netops@example.com',
        ))

    conn.executemany(
        '''INSERT OR IGNORE INTO devices
           (id, hostname, ip_address, platform, status, compliance,
            sn, model, version, role, site, uptime,
            connection_method, username, password,
            current_config, config_history,
            cpu_usage, memory_usage, interface_data,
            snmp_community, snmp_port, cpu_history, memory_history,
            temp, fan_status, psu_status,
            sys_name, sys_location, sys_contact)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        devices,
    )
    conn.commit()
    print(f"    -> {count} 台设备已写入")
    return [(d[0], d[1], d[3]) for d in devices]  # (id, hostname, platform)


def seed_servers(conn, count=1000):
    """灌入服务器资产"""
    print(f"  灌入 {count} 台服务器...")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    servers = []
    for i in range(count):
        vendor = random.choice(SERVER_VENDORS)
        dc = random.choice(DATACENTERS)
        servers.append((
            _uid(), 'server',
            f"ASSET-SRV-{i+1:05d}",
            f"SRV-SN-{random.randint(100000,999999)}",
            vendor, random.choice(SERVER_MODELS),
            f"srv-{dc[:2].lower()}-{i+1:04d}",
            dc,
            f"R{random.randint(1,20):02d}",
            f"U{random.randint(1,42)}",
            _rand_ip(random.randint(100, 200)),
            _rand_ip(random.randint(100, 200)),
            random.choice(['compute', 'storage', 'database', 'web', 'middleware']),
            str(random.randint(100, 4000)),
            '', '',
            random.choices(['active', 'maintenance', 'decommissioned'], weights=[85, 10, 5])[0],
            f"2023-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            f"2027-{random.randint(1,12):02d}-{random.randint(1,28):02d}",
            random.choice(DEPARTMENTS),
            '', now, now,
        ))

    conn.executemany(
        '''INSERT OR IGNORE INTO physical_assets
           (id, asset_type, asset_tag, serial_number, vendor, model,
            hostname, datacenter, rack, rack_unit,
            management_ip, business_ip, device_role, vlan,
            uplink_switch, uplink_port, status,
            purchase_date, warranty_expiry, department,
            notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        servers,
    )
    conn.commit()
    print(f"    -> {count} 台服务器已写入")


def seed_config_snapshots(conn, device_list):
    """每台设备灌入 3 份配置快照"""
    count = len(device_list) * 3
    print(f"  灌入 {count} 份配置快照...")
    rows = []
    for did, hostname, platform in device_list:
        vendor = [p[1] for p in PLATFORMS if p[0] == platform][0] if any(p[0] == platform for p in PLATFORMS) else 'Unknown'
        for j in range(3):
            ts = _rand_time(days_back=30)
            config_text = _fake_config(hostname, platform, vendor)
            rows.append((
                _uid(), did, hostname, vendor, ts,
                random.choice(['scheduled', 'manual', 'change']),
                'system', '', '', len(config_text),
            ))
    conn.executemany(
        '''INSERT OR IGNORE INTO config_snapshots
           (id, device_id, hostname, vendor, timestamp, trigger, author, tag, file_path, size)
           VALUES (?,?,?,?,?,?,?,?,?,?)''',
        rows,
    )
    conn.commit()
    print(f"    -> {count} 份快照已写入")


def seed_alerts(conn, device_list, open_count=500, resolved_count=1500):
    """灌入告警"""
    total = open_count + resolved_count
    print(f"  灌入 {total} 条告警 (open={open_count}, resolved={resolved_count})...")
    rows = []
    for i in range(total):
        did, hostname, _ = random.choice(device_list)
        title_tmpl, source, severity = random.choice(ALERT_TITLES)
        is_resolved = i >= open_count
        created = _rand_time(days_back=30 if is_resolved else 7)
        rows.append((
            _uid(),
            f"{source}:{hostname}:{i}",
            source, severity,
            f"[{hostname}] {title_tmpl}",
            f"设备 {hostname} 触发告警: {title_tmpl}",
            did, '',
            created,
            _rand_time(days_back=7) if is_resolved else None,
            'resolved' if is_resolved else random.choice(['open', 'acknowledged']),
            '', '', '', '', created,
        ))
    conn.executemany(
        '''INSERT OR IGNORE INTO alert_events
           (id, dedupe_key, source, severity, title, message,
            device_id, interface_name, created_at, resolved_at,
            workflow_status, assignee, ack_by, ack_at, note, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        rows,
    )
    conn.commit()
    print(f"    -> {total} 条告警已写入")


def seed_audit_events(conn, count=5000):
    """灌入审计日志"""
    print(f"  灌入 {count} 条审计日志...")
    rows = []
    for i in range(count):
        evt = random.choice(AUDIT_EVENTS)
        rows.append((
            _uid(), evt[0], evt[1], evt[2], 'completed',
            'user-admin', 'admin', 'Administrator', f"192.168.1.{random.randint(1,254)}",
            random.choice(['device', 'config', 'user', 'job']),
            _uid(), f"target-{i}",
            '', '', '', '', evt[3], '{}', _rand_time(days_back=30),
        ))
    conn.executemany(
        '''INSERT OR IGNORE INTO audit_events
           (id, event_type, category, severity, status,
            actor_id, actor_username, actor_role, source_ip,
            target_type, target_id, target_name,
            device_id, job_id, execution_id, snapshot_id,
            summary, details_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        rows,
    )
    conn.commit()
    print(f"    -> {count} 条审计日志已写入")


def seed_compliance_findings(conn, device_list, count=800):
    """灌入合规缺陷"""
    print(f"  灌入 {count} 条合规缺陷...")
    rows = []
    for i in range(count):
        did, hostname, _ = random.choice(device_list)
        rule = random.choice(COMPLIANCE_RULES)
        status = random.choices(['open', 'remediated'], weights=[60, 40])[0]
        first_seen = _rand_time(days_back=60)
        rows.append((
            _uid(),
            f"{rule[0]}:{did}:{i}",
            rule[0], did, None,
            random.choice(['high', 'medium', 'low']),
            rule[2], rule[1], rule[3],
            status, '', '', '',
            '', '', first_seen, _rand_time(days_back=7),
            _rand_time(days_back=3) if status == 'remediated' else None,
        ))
    conn.executemany(
        '''INSERT OR IGNORE INTO compliance_findings
           (id, fingerprint, rule_id, device_id, run_id,
            severity, category, title, description,
            status, observed_value, evidence, remediation,
            owner, note, first_seen_at, last_seen_at, resolved_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        rows,
    )
    conn.commit()
    print(f"    -> {count} 条合规缺陷已写入")


def main():
    print("=" * 60)
    print("  NetPilot 压测数据灌入")
    print("=" * 60)

    conn = get_db_connection()
    try:
        # 先检查现有数量
        existing = conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
        print(f"\n  当前设备数: {existing}")

        device_list = seed_devices(conn, count=500)
        seed_servers(conn, count=1000)
        seed_config_snapshots(conn, device_list)
        seed_alerts(conn, device_list, open_count=500, resolved_count=1500)
        seed_audit_events(conn, count=5000)
        seed_compliance_findings(conn, device_list, count=800)

        # 验证
        print("\n  === 灌入后数据统计 ===")
        for table in ['devices', 'physical_assets', 'config_snapshots', 'alert_events', 'audit_events', 'compliance_findings']:
            cnt = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            print(f"    {table}: {cnt}")
        print("\n  Done!")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
