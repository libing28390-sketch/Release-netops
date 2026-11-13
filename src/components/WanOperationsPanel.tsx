import { useEffect, useState } from 'react';
import { Download, FileText, Loader2, Plus, Save, ShieldCheck, Trash2 } from 'lucide-react';
import DateTimePicker from './DateTimePicker';

type Link = { id: string; link_name: string };
type Target = { id: string; target_name: string; probe_type?: string };
type Binding = { id: string; link_id: string; target_id: string; link_name?: string; target_name?: string; route_mode: string; source_ip?: string; priority?: number; enabled?: boolean };
type Report = { id: string; report_id?: string; report_type: string; status: string; period_start: string; period_end: string; result?: { link_metrics?: Array<Record<string, unknown>>; alerts?: Array<Record<string, unknown>>; probe_availability?: Array<Record<string, unknown>> } };
type GroupMember = { link_id: string; role: 'primary' | 'backup' | 'load_balanced'; priority?: number; weight?: number };
type Group = { id: string; group_name: string; mode: string; health_status?: string; switch_status?: string; members?: Array<Record<string, unknown>> };
const auth = () => { const token = localStorage.getItem('netops_token'); return token ? { Authorization: `Bearer ${token}` } : {}; };

const WanOperationsPanel: React.FC = () => {
  const [links, setLinks] = useState<Link[]>([]);
  const [targets, setTargets] = useState<Target[]>([]);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [maintenance, setMaintenance] = useState<Array<Record<string, unknown>>>([]);
  const [capacity, setCapacity] = useState<Array<Record<string, any>>>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [maintenanceLinkId, setMaintenanceLinkId] = useState('');
  const [bindingLinkId, setBindingLinkId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [routeMode, setRouteMode] = useState('default');
  const [sourceIp, setSourceIp] = useState('');
  const [windowName, setWindowName] = useState('出口链路维护');
  const [startsAt, setStartsAt] = useState('');
  const [endsAt, setEndsAt] = useState('');
  const [recurrence, setRecurrence] = useState('once');
  const [groupName, setGroupName] = useState('');
  const [groupMode, setGroupMode] = useState<'primary_backup' | 'load_balanced'>('primary_backup');
  const [groupMembers, setGroupMembers] = useState<Record<string, GroupMember['role']>>({});
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true); setError('');
    try {
      const responses = await Promise.all([
        fetch('/api/monitoring/wan-links?page_size=100', { headers: auth() }),
        fetch('/api/monitoring/outbound-targets', { headers: auth() }),
        fetch('/api/monitoring/wan-probe-bindings', { headers: auth() }),
        fetch('/api/monitoring/wan-maintenance-windows', { headers: auth() }),
        fetch('/api/monitoring/wan-capacity-recommendations', { headers: auth() }),
        fetch('/api/monitoring/wan-reports?limit=10', { headers: auth() }),
        fetch('/api/monitoring/wan-link-groups', { headers: auth() }),
      ]);
      if (responses.some((response) => !response.ok)) throw new Error('运维数据加载失败');
      const [link, target, binding, windows, recommendations, report, group] = await Promise.all(responses.map((response) => response.json()));
      setLinks(link.items || []); setTargets(target.items || []); setBindings(binding.items || []); setMaintenance(windows.items || []); setCapacity(recommendations.items || []); setReports(report.items || []); setGroups(group.items || []);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, []);

  const saveMaintenance = async () => {
    if (!startsAt || !endsAt || new Date(endsAt) <= new Date(startsAt)) { setMessage('请填写有效的维护时间范围'); return; }
    const response = await fetch('/api/monitoring/wan-maintenance-windows', { method: 'POST', headers: { ...auth(), 'Content-Type': 'application/json' }, body: JSON.stringify({ name: windowName, link_id: maintenanceLinkId, starts_at: new Date(startsAt).toISOString(), ends_at: new Date(endsAt).toISOString(), recurrence, reason: 'planned maintenance' }) });
    setMessage(response.ok ? '维护窗口已保存' : '维护窗口保存失败'); if (response.ok) void load();
  };

  const deleteMaintenance = async (id: string) => {
    const response = await fetch(`/api/monitoring/wan-maintenance-windows/${encodeURIComponent(id)}`, { method: 'DELETE', headers: auth() });
    if (response.ok) void load(); else setMessage('维护窗口删除失败');
  };

  const bindTarget = async () => {
    if (!bindingLinkId || !targetId) { setMessage('请选择链路和探测目标'); return; }
    const response = await fetch('/api/monitoring/wan-probe-bindings', { method: 'POST', headers: { ...auth(), 'Content-Type': 'application/json' }, body: JSON.stringify({ link_id: bindingLinkId, target_id: targetId, route_mode: routeMode, source_ip: sourceIp }) });
    setMessage(response.ok ? '探测目标已绑定' : '探测绑定失败'); if (response.ok) void load();
  };

  const deleteBinding = async (id: string) => {
    const response = await fetch(`/api/monitoring/wan-probe-bindings/${encodeURIComponent(id)}`, { method: 'DELETE', headers: auth() });
    setMessage(response.ok ? '探测绑定已删除' : '探测绑定删除失败'); if (response.ok) void load();
  };

  const saveGroup = async () => {
    const members: GroupMember[] = Object.entries(groupMembers).map(([link_id, role], index) => ({ link_id, role, priority: index + 1, weight: 1 }));
    if (!groupName.trim() || !members.length) { setMessage('请输入线路组名称并至少选择一条链路'); return; }
    const response = await fetch('/api/monitoring/wan-link-groups', { method: 'POST', headers: { ...auth(), 'Content-Type': 'application/json' }, body: JSON.stringify({ group_name: groupName.trim(), mode: groupMode, members }) });
    setMessage(response.ok ? '线路组已保存' : '线路组保存失败');
    if (response.ok) { setGroupName(''); setGroupMembers({}); void load(); }
  };

  const report = async (type: 'daily' | 'weekly' | 'monthly') => {
    const end = new Date(); const start = new Date(end); start.setDate(end.getDate() - (type === 'daily' ? 1 : type === 'weekly' ? 7 : 30));
    const response = await fetch('/api/monitoring/wan-reports', { method: 'POST', headers: { ...auth(), 'Content-Type': 'application/json' }, body: JSON.stringify({ report_type: type, period_start: start.toISOString(), period_end: end.toISOString() }) });
    const body = await response.json().catch(() => ({}));
    setMessage(response.ok ? `${type} 报告已生成` : body?.detail?.message || '报告生成失败'); if (response.ok) void load();
  };

  const exportReport = async (reportId: string) => {
    const response = await fetch(`/api/monitoring/wan-reports/${encodeURIComponent(reportId)}/export`, { method: 'POST', headers: auth() });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) { setMessage('报告导出失败'); return; }
    const blob = new Blob([JSON.stringify(body.item?.result || body.item || {}, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${reportId}.json`; anchor.click(); URL.revokeObjectURL(url); setMessage('报告已导出'); void load();
  };

  return (
    <section className="rounded-2xl border border-[var(--card-border)] bg-[var(--card-bg)] p-4 shadow-sm md:p-5">
      <div className="flex items-center justify-between"><div><p className="text-[10px] font-bold uppercase tracking-[0.18em] text-amber-600">WAN operations</p><h2 className="mt-1 text-xl font-extrabold text-[var(--app-text)]">运维、绑定与报告</h2><p className="mt-1 text-xs text-[var(--muted-text)]">维护抑制、探针证据、线路组和可追溯报告</p></div>{loading && <Loader2 className="animate-spin text-[var(--muted-text)]" size={16} />}</div>
      {error && <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>}
      <p className="mt-3 rounded-xl border border-dashed border-amber-200 bg-amber-50/50 px-3 py-2 text-xs text-amber-800">先在“出口链路”中创建并完成采集，再配置探测绑定和线路组；报告、容量建议及统计样本会在有链路数据后自动生成。</p>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-[var(--card-border)] p-3"><p className="flex items-center gap-2 text-xs font-bold"><ShieldCheck size={14} />维护窗口</p><div className="mt-3 grid gap-2 sm:grid-cols-2"><input value={windowName} onChange={(event) => setWindowName(event.target.value)} placeholder="窗口名称" className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" /><select value={maintenanceLinkId} onChange={(event) => setMaintenanceLinkId(event.target.value)} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">全站点/全链路</option>{links.map((link) => <option key={link.id} value={link.id}>{link.link_name}</option>)}</select><DateTimePicker value={startsAt} onChange={setStartsAt} language="zh" placeholder="选择开始时间" /><DateTimePicker value={endsAt} onChange={setEndsAt} language="zh" placeholder="选择结束时间" /><select value={recurrence} onChange={(event) => setRecurrence(event.target.value)} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="once">一次性</option><option value="daily">每日</option><option value="weekly">每周</option><option value="monthly">每月</option></select></div><button type="button" onClick={() => void saveMaintenance()} className="mt-3 inline-flex items-center gap-1 rounded-lg bg-amber-600 px-3 py-2 text-xs font-bold text-white"><Save size={13} />保存窗口</button><div className="mt-3 space-y-1 text-[11px] text-[var(--muted-text)]">{maintenance.slice(0, 5).map((item) => <p key={String(item.id)} className="flex items-center justify-between gap-2"><span>{String(item.name)} · {String(item.starts_at)} ~ {String(item.ends_at)} · {String(item.recurrence || 'once')}</span><button type="button" onClick={() => void deleteMaintenance(String(item.id))} aria-label="删除维护窗口" className="text-rose-600"><Trash2 size={12} /></button></p>)}</div></div>
        <div className="rounded-xl border border-[var(--card-border)] p-3"><p className="flex items-center gap-2 text-xs font-bold"><Plus size={14} />探测绑定</p><div className="mt-3 grid gap-2 sm:grid-cols-2"><select value={bindingLinkId} onChange={(event) => setBindingLinkId(event.target.value)} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">选择链路</option>{links.map((link) => <option key={link.id} value={link.id}>{link.link_name}</option>)}</select><select value={targetId} onChange={(event) => setTargetId(event.target.value)} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="">选择探测目标</option>{targets.map((target) => <option key={target.id} value={target.id}>{target.target_name} · {target.probe_type}</option>)}</select><select value={routeMode} onChange={(event) => setRouteMode(event.target.value)} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="default">默认路由（证据不足）</option><option value="source_ip">指定来源 IP</option></select>{routeMode === 'source_ip' && <input value={sourceIp} onChange={(event) => setSourceIp(event.target.value)} placeholder="来源 IP" className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" />}</div><button type="button" onClick={() => void bindTarget()} className="mt-3 rounded-lg bg-violet-600 px-3 py-2 text-xs font-bold text-white">保存绑定</button><div className="mt-3 space-y-1 text-[11px] text-[var(--muted-text)]">{bindings.slice(0, 8).map((binding) => <p key={binding.id} className="flex items-center justify-between gap-2"><span>{binding.link_name || binding.link_id} → {binding.target_name || binding.target_id} · {binding.route_mode}</span><button type="button" onClick={() => void deleteBinding(binding.id)} aria-label="删除探测绑定" className="text-rose-600"><Trash2 size={12} /></button></p>)}{!bindings.length && <span>暂无已绑定探测目标</span>}</div><div className="mt-5 flex flex-wrap gap-2"><button type="button" onClick={() => void report('daily')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] px-3 py-2 text-xs font-bold"><FileText size={13} />日报</button><button type="button" onClick={() => void report('weekly')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] px-3 py-2 text-xs font-bold"><FileText size={13} />周报</button><button type="button" onClick={() => void report('monthly')} className="inline-flex items-center gap-1 rounded-lg border border-[var(--card-border)] px-3 py-2 text-xs font-bold"><FileText size={13} />月报</button></div></div>
      </div>
      {message && <p className="mt-3 text-xs font-bold text-cyan-700">{message}</p>}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-[var(--card-border)] p-3"><p className="text-xs font-bold">线路组管理</p><div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto]"><input value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="新线路组名称" className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs" /><select value={groupMode} onChange={(event) => setGroupMode(event.target.value as 'primary_backup' | 'load_balanced')} className="rounded-lg border border-[var(--card-border)] bg-[var(--card-bg)] px-2 py-2 text-xs"><option value="primary_backup">主备</option><option value="load_balanced">负载均衡</option></select></div><div className="mt-2 grid gap-1">{links.slice(0, 30).map((link) => <label key={link.id} className="flex items-center gap-2 text-[11px] text-[var(--muted-text)]"><input type="checkbox" checked={Boolean(groupMembers[link.id])} onChange={(event) => setGroupMembers((current) => { const next = { ...current }; if (event.target.checked) next[link.id] = groupMode === 'load_balanced' ? 'load_balanced' : 'primary'; else delete next[link.id]; return next; })} />{link.link_name}<select value={groupMembers[link.id] || (groupMode === 'load_balanced' ? 'load_balanced' : 'primary')} disabled={!groupMembers[link.id]} onChange={(event) => setGroupMembers((current) => ({ ...current, [link.id]: event.target.value as GroupMember['role'] }))} className="ml-auto rounded border border-[var(--card-border)] bg-[var(--card-bg)] px-1 py-0.5 text-[10px]"><option value="primary">primary</option><option value="backup">backup</option><option value="load_balanced">load_balanced</option></select></label>)}</div><button type="button" onClick={() => void saveGroup()} className="mt-3 inline-flex items-center gap-1 rounded-lg bg-cyan-700 px-3 py-2 text-xs font-bold text-white"><Save size={13} />保存线路组</button>{groups.length ? <div className="mt-3 space-y-2">{groups.slice(0, 6).map((group) => <div key={group.id} className="rounded-lg bg-black/[0.03] px-3 py-2 text-xs"><b>{group.group_name}</b><span className="ml-2 text-[var(--muted-text)]">{group.mode} · {group.health_status || 'unknown'} · {group.switch_status || 'standby'} · {group.members?.length || 0} 条</span></div>)}</div> : <p className="mt-2 text-xs text-[var(--muted-text)]">暂无线路组</p>}</div>
        <div className="rounded-xl border border-[var(--card-border)] p-3"><p className="text-xs font-bold">容量建议</p>{capacity.length ? <div className="mt-2 grid gap-2">{capacity.slice(0, 6).map((item) => <div key={String(item.id)} className="rounded-lg bg-black/[0.03] px-3 py-2 text-xs"><b>{String(item.recommendation)}</b><span className="ml-2 text-[var(--muted-text)]">{String(item.status)} · {String(item.evidence?.window_days || '--')}天 · 置信度 {String(item.confidence ?? '--')}</span></div>)}</div> : <p className="mt-2 text-xs text-[var(--muted-text)]">暂无容量建议</p>}</div>
      </div>
      <div className="mt-4 rounded-xl border border-[var(--card-border)] p-3"><div className="flex items-center justify-between"><p className="text-xs font-bold">报告预览与导出</p><Download size={14} className="text-[var(--muted-text)]" /></div>{reports.length ? <div className="mt-2 space-y-2">{reports.slice(0, 5).map((item) => <div key={item.id || item.report_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-black/[0.03] px-3 py-2 text-xs"><span><b>{item.report_type}</b> · {item.status} · {item.period_start} ~ {item.period_end}<br /><span className="text-[10px] text-[var(--muted-text)]">链路 {item.result?.link_metrics?.length || 0} · 告警 {item.result?.alerts?.length || 0} · 探测样本 {item.result?.probe_availability?.length || 0}</span></span>{(item.id || item.report_id) && <button type="button" onClick={() => void exportReport(String(item.id || item.report_id))} className="inline-flex items-center gap-1 font-bold text-cyan-700"><Download size={12} />导出</button>}</div>)}</div> : <p className="mt-2 text-xs text-[var(--muted-text)]">暂无报告</p>}</div>
    </section>
  );
};

export default WanOperationsPanel;
