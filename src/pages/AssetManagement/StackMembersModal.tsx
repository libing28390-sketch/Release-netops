import React, { useCallback, useEffect, useState } from 'react';
import { Download, Layers, RefreshCw, Replace, Upload, X } from 'lucide-react';
import { useEscapeClose } from '../../hooks/useEscapeClose';

export interface StackMemberRecord {
  id: string;
  asset_id: string;
  member_number: number;
  physical_asset_tag: string;
  serial_number: string;
  model: string;
  rack_id: string | null;
  rack_name: string;
  u_start: number | null;
  u_height: number;
  status: 'active' | 'replaced' | 'retired';
  entity_index: number | null;
  last_reconciled_at: string | null;
  reconciliation_status: 'unverified' | 'matched' | 'missing_in_snmp' | 'sn_mismatch';
  replaced_by_id: string | null;
  retired_at: string | null;
  notes: string;
}

interface ImportPreviewItem {
  row_number: number;
  action: 'create' | 'update' | 'existing' | 'conflict';
  stack_asset_tag: string;
  member_number: number | null;
  physical_asset_tag: string;
  serial_number: string;
  rack_name: string;
  u_start: number | null;
  u_height: number;
  conflicts: Array<{ row_number: number; field: string; message: string }>;
}

interface ImportPreviewResult {
  summary: { total: number; create: number; update: number; existing: number; conflict: number };
  items: ImportPreviewItem[];
  conflicts: Array<{ row_number: number; field: string; message: string }>;
  can_commit: boolean;
}

interface ReconcileResult {
  matched_members: Array<{ member_number: number; serial_number: string; entity_index: number }>;
  missing_members: Array<{ member_number: number; serial_number: string }>;
  mismatched_members: Array<{ member_number: number; registered_sn: string; observed_sn: string }>;
  unregistered_chassis: Array<{ entity_index: number; serial_number: string; model: string }>;
}

interface StackMembersModalProps {
  mode: 'import' | 'members';
  asset?: { id: string; asset_tag?: string; hostname?: string; management_ip?: string } | null;
  language: string;
  onClose: () => void;
  onChanged?: () => void;
}

const TEMPLATE_CSV = [
  'stack_asset_tag,member_number,physical_asset_tag,serial_number,model,rack_name,u_start,u_height,notes',
  'WH-ACC-STACK01,1,PHY-S6850-01A,SN-STACK-01A,S6850-56HF,RACK-A01,40,1,Master chassis',
  'WH-ACC-STACK01,2,PHY-S6850-01B,SN-STACK-01B,S6850-56HF,RACK-A01,39,1,Standby chassis',
].join('\n');

export function parseStackMemberCsv(text: string) {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length < 2) return [];
  const headers = lines[0].split(',').map((h) => h.trim().toLowerCase());
  const rows: Array<Record<string, unknown>> = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cols = lines[i].split(',').map((c) => c.trim());
    const record: Record<string, unknown> = { row_number: i + 1 };
    headers.forEach((header, idx) => {
      const value = cols[idx] ?? '';
      if (header === 'member_number' || header === 'u_start' || header === 'u_height') {
        record[header] = value ? Number(value) : undefined;
      } else {
        record[header] = value;
      }
    });
    rows.push(record);
  }
  return rows;
}

export default function StackMembersModal({
  mode,
  asset,
  language,
  onClose,
  onChanged,
}: StackMembersModalProps) {
  const zh = language === 'zh';
  const [activeTab, setActiveTab] = useState<'members' | 'import'>(mode);
  const [members, setMembers] = useState<StackMemberRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reconciling, setReconciling] = useState(false);
  const [reconcileResult, setReconcileResult] = useState<ReconcileResult | null>(null);
  const [replacingMember, setReplacingMember] = useState<StackMemberRecord | null>(null);
  const [replaceForm, setReplaceForm] = useState({ new_serial_number: '', new_physical_asset_tag: '', new_model: '', notes: '' });
  const [replaceSaving, setReplaceSaving] = useState(false);

  const [csvText, setCsvText] = useState('');
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [committing, setCommitting] = useState(false);

  useEscapeClose(!committing && !replaceSaving, onClose);

  const authHeaders = useCallback((): Record<string, string> => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, []);

  const loadMembers = useCallback(async () => {
    if (!asset?.id) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`/api/assets/${encodeURIComponent(asset.id)}/stack-members?include_history=true`, {
        headers: authHeaders(),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`);
      setMembers(Array.isArray(payload.items) ? payload.items : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [asset?.id, authHeaders]);

  useEffect(() => {
    if (activeTab === 'members' && asset?.id) {
      void loadMembers();
    }
  }, [activeTab, asset?.id, loadMembers]);

  const handleReconcile = async () => {
    if (!asset?.id || reconciling) return;
    setReconciling(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch(`/api/assets/${encodeURIComponent(asset.id)}/stack-members/reconcile-snmp`, {
        method: 'POST',
        headers: authHeaders(),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`);
      setReconcileResult(payload as ReconcileResult);
      setNotice(zh
        ? `SNMP 对账完成：匹配 ${payload.matched_members?.length ?? 0}，缺失 ${payload.missing_members?.length ?? 0}，未登记机箱 ${payload.unregistered_chassis?.length ?? 0}。`
        : `SNMP reconciliation complete: ${payload.matched_members?.length ?? 0} matched, ${payload.missing_members?.length ?? 0} missing, ${payload.unregistered_chassis?.length ?? 0} unregistered.`);
      await loadMembers();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReconciling(false);
    }
  };

  const handleReplaceSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!replacingMember || replaceSaving) return;
    setReplaceSaving(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch(`/api/assets/stack-members/${encodeURIComponent(replacingMember.id)}/replace`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(replaceForm),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`);
      setReplacingMember(null);
      setReplaceForm({ new_serial_number: '', new_physical_asset_tag: '', new_model: '', notes: '' });
      setNotice(zh ? `成员 #${replacingMember.member_number} 换机完成，已继承原机柜 U 位并保留旧机箱退网记录。` : `Member #${replacingMember.member_number} replaced; rack position inherited.`);
      await loadMembers();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReplaceSaving(false);
    }
  };

  const handleDownloadCsvTemplate = () => {
    const blob = new Blob([`\uFEFF${TEMPLATE_CSV}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'stack-members-template.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const handlePreviewImport = async () => {
    const parsedRows = parseStackMemberCsv(csvText);
    if (parsedRows.length === 0) {
      setError(zh ? '请先上传或粘贴包含表头和至少一行成员数据的 CSV。' : 'Provide CSV text with a header row and at least one member row.');
      return;
    }
    setPreviewLoading(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/assets/stack-members/import-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ rows: parsedRows }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`);
      setPreview(payload as ImportPreviewResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleCommitImport = async () => {
    if (!preview?.can_commit || committing) return;
    const parsedRows = parseStackMemberCsv(csvText);
    setCommitting(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch('/api/assets/stack-members/import-commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ rows: parsedRows }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.detail || `HTTP ${res.status}`);
      setNotice(zh
        ? `导入成功：新增 ${payload.created ?? 0}，更新 ${payload.updated ?? 0}，未变更 ${payload.unchanged ?? 0}。`
        : `Import committed: ${payload.created ?? 0} created, ${payload.updated ?? 0} updated, ${payload.unchanged ?? 0} unchanged.`);
      setPreview(null);
      if (asset?.id) await loadMembers();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCommitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[85] flex items-center justify-center bg-black/50 p-4" role="presentation">
      <section
        role="dialog"
        aria-modal="true"
        aria-label={zh ? '堆叠成员台账管理' : 'Stack Member Inventory'}
        className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
              <Layers size={18} />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">
                {zh ? '堆叠成员台账与导入' : 'Stack Member Inventory & Import'}
              </h2>
              {asset && (
                <p className="text-xs text-slate-500">
                  {asset.hostname || asset.asset_tag || asset.id} {asset.management_ip ? `· ${asset.management_ip}` : ''}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {asset?.id && (
              <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-xs">
                <button
                  type="button"
                  onClick={() => setActiveTab('members')}
                  className={`rounded-md px-2.5 py-1 font-semibold ${activeTab === 'members' ? 'bg-white text-indigo-700 shadow-xs' : 'text-slate-600'}`}
                >
                  {zh ? '成员台账' : 'Members'}
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('import')}
                  className={`rounded-md px-2.5 py-1 font-semibold ${activeTab === 'import' ? 'bg-white text-indigo-700 shadow-xs' : 'text-slate-600'}`}
                >
                  {zh ? '成员导入' : 'Import'}
                </button>
              </div>
            )}
            <button type="button" onClick={onClose} aria-label={zh ? '关闭' : 'Close'} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto p-5 text-xs">
          {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-rose-700">{error}</div>}
          {notice && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-emerald-700">{notice}</div>}

          {activeTab === 'members' && asset?.id && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-slate-500">
                  {zh ? '一组堆叠保持单一管理入口，以下为各物理机箱的独立台账、机柜位置与 SNMP 对账状态。' : 'Logical stack shares one management IP while each chassis maintains its own inventory record and rack coordinates.'}
                </p>
                <button
                  type="button"
                  disabled={reconciling}
                  onClick={() => void handleReconcile()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  <RefreshCw size={13} className={reconciling ? 'animate-spin' : ''} />
                  {zh ? 'SNMP 对账' : 'Reconcile SNMP'}
                </button>
              </div>

              {reconcileResult && reconcileResult.unregistered_chassis.length > 0 && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-amber-900">
                  <div className="font-bold">{zh ? '发现未登记的 SNMP 机箱：' : 'Unregistered SNMP chassis detected:'}</div>
                  <ul className="mt-1 list-disc pl-4">
                    {reconcileResult.unregistered_chassis.map((c) => (
                      <li key={`${c.entity_index}-${c.serial_number}`}>
                        Entity #{c.entity_index} · SN: <code className="font-mono">{c.serial_number || '—'}</code> ({c.model || '—'})
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {loading ? (
                <div className="py-10 text-center text-slate-400">{zh ? '加载成员台账中…' : 'Loading stack members…'}</div>
              ) : members.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 py-10 text-center text-slate-500">
                  {zh ? '尚未录入堆叠成员台账，可切换至“成员导入”批量导入。' : 'No stack members recorded yet. Switch to Import to add chassis records.'}
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-slate-200">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-slate-100 bg-slate-50 text-[10px] font-bold uppercase text-slate-500">
                      <tr>
                        <th className="px-3 py-2.5">{zh ? '成员号' : 'Slot'}</th>
                        <th className="px-3 py-2.5">{zh ? '物理资产编号' : 'Physical Tag'}</th>
                        <th className="px-3 py-2.5">SN</th>
                        <th className="px-3 py-2.5">{zh ? '型号' : 'Model'}</th>
                        <th className="px-3 py-2.5">{zh ? '机柜 / U位' : 'Rack / U'}</th>
                        <th className="px-3 py-2.5">{zh ? '状态 / SNMP对账' : 'Status / SNMP'}</th>
                        <th className="px-3 py-2.5 text-right">{zh ? '操作' : 'Action'}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {members.map((m) => (
                        <tr key={m.id} className={m.status !== 'active' ? 'bg-slate-50/70 text-slate-400' : ''}>
                          <td className="px-3 py-2.5 font-mono font-bold">#{m.member_number}</td>
                          <td className="px-3 py-2.5 font-mono">{m.physical_asset_tag || '—'}</td>
                          <td className="px-3 py-2.5 font-mono">{m.serial_number || '—'}</td>
                          <td className="px-3 py-2.5">{m.model || '—'}</td>
                          <td className="px-3 py-2.5">
                            {m.rack_name || '—'}{m.u_start ? ` · U${m.u_start} (${m.u_height}U)` : ''}
                          </td>
                          <td className="px-3 py-2.5">
                            <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${
                              m.status !== 'active'
                                ? 'bg-slate-200 text-slate-600'
                                : m.reconciliation_status === 'matched'
                                  ? 'bg-emerald-50 text-emerald-700'
                                  : m.reconciliation_status === 'missing_in_snmp' || m.reconciliation_status === 'sn_mismatch'
                                    ? 'bg-amber-50 text-amber-800'
                                    : 'bg-slate-100 text-slate-600'
                            }`}>
                              {m.status !== 'active'
                                ? (zh ? '已替换退网' : 'Replaced')
                                : m.reconciliation_status === 'matched'
                                  ? (zh ? `已对账 (Entity ${m.entity_index})` : `Matched (Entity ${m.entity_index})`)
                                  : m.reconciliation_status === 'missing_in_snmp'
                                    ? (zh ? 'SNMP 缺失（保留台账）' : 'Missing in SNMP')
                                    : m.reconciliation_status === 'sn_mismatch'
                                      ? (zh ? 'SN 不一致' : 'SN mismatch')
                                      : (zh ? '未对账' : 'Unverified')}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            {m.status === 'active' ? (
                              <button
                                type="button"
                                onClick={() => {
                                  setReplacingMember(m);
                                  setReplaceForm({
                                    new_serial_number: '',
                                    new_physical_asset_tag: '',
                                    new_model: m.model || '',
                                    notes: '',
                                  });
                                }}
                                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 font-semibold text-slate-700 hover:bg-slate-50"
                              >
                                <Replace size={12} />
                                {zh ? '更换机箱' : 'Replace'}
                              </button>
                            ) : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {replacingMember && (
                <form onSubmit={handleReplaceSubmit} className="space-y-3 rounded-xl border border-indigo-200 bg-indigo-50/40 p-4">
                  <div className="font-bold text-indigo-900">
                    {zh
                      ? `更换成员 #${replacingMember.member_number}（旧 SN: ${replacingMember.serial_number || '—'}，将继承机柜 ${replacingMember.rack_name || '—'} U${replacingMember.u_start || '—'}）`
                      : `Replace Member #${replacingMember.member_number} (Old SN: ${replacingMember.serial_number || '—'})`}
                  </div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <input
                      required
                      placeholder={zh ? '新机箱 SN *' : 'New Serial Number *'}
                      value={replaceForm.new_serial_number}
                      onChange={(e) => setReplaceForm((p) => ({ ...p, new_serial_number: e.target.value }))}
                      className="h-9 rounded-lg border border-slate-200 bg-white px-2.5 text-xs"
                    />
                    <input
                      placeholder={zh ? '新物理资产编号' : 'New Physical Asset Tag'}
                      value={replaceForm.new_physical_asset_tag}
                      onChange={(e) => setReplaceForm((p) => ({ ...p, new_physical_asset_tag: e.target.value }))}
                      className="h-9 rounded-lg border border-slate-200 bg-white px-2.5 text-xs"
                    />
                    <input
                      placeholder={zh ? '型号（留空沿用）' : 'Model (optional)'}
                      value={replaceForm.new_model}
                      onChange={(e) => setReplaceForm((p) => ({ ...p, new_model: e.target.value }))}
                      className="h-9 rounded-lg border border-slate-200 bg-white px-2.5 text-xs"
                    />
                  </div>
                  <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => setReplacingMember(null)} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-600">
                      {zh ? '取消' : 'Cancel'}
                    </button>
                    <button type="submit" disabled={replaceSaving} className="rounded-lg bg-indigo-600 px-3 py-1.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                      {replaceSaving ? (zh ? '提交中…' : 'Saving…') : (zh ? '确认换机' : 'Confirm Replace')}
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}

          {activeTab === 'import' && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-slate-500">
                  {zh ? '每台物理机箱填一行，通过 stack_asset_tag 关联到已导入的逻辑堆叠网络设备；重复导入幂等。' : 'One row per physical chassis linked by stack_asset_tag. Re-imports are idempotent.'}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleDownloadCsvTemplate}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <Download size={13} />
                    {zh ? '下载成员模板 CSV' : 'Download CSV Template'}
                  </button>
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-50">
                    <Upload size={13} />
                    {zh ? '读取 CSV 文件' : 'Load CSV File'}
                    <input
                      type="file"
                      accept=".csv,text/csv"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        void file.text().then((txt) => {
                          setCsvText(txt.replace(/^\uFEFF/, ''));
                          setPreview(null);
                        });
                      }}
                    />
                  </label>
                </div>
              </div>

              <textarea
                rows={6}
                aria-label={zh ? '堆叠成员 CSV 内容' : 'Stack members CSV content'}
                placeholder={TEMPLATE_CSV}
                value={csvText}
                onChange={(e) => { setCsvText(e.target.value); setPreview(null); }}
                className="w-full rounded-xl border border-slate-200 p-3 font-mono text-[11px] text-slate-700 outline-none focus:border-indigo-400"
              />

              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  disabled={previewLoading || !csvText.trim()}
                  onClick={() => void handlePreviewImport()}
                  className="rounded-lg border border-indigo-200 bg-indigo-50 px-3.5 py-1.5 font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
                >
                  {previewLoading ? (zh ? '校验中…' : 'Validating…') : (zh ? '预览校验' : 'Preview & Validate')}
                </button>
                <button
                  type="button"
                  disabled={committing || !preview?.can_commit}
                  onClick={() => void handleCommitImport()}
                  className="rounded-lg bg-indigo-600 px-3.5 py-1.5 font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {committing ? (zh ? '导入中…' : 'Committing…') : (zh ? '确认导入成员' : 'Commit Import')}
                </button>
              </div>

              {preview && (
                <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
                  <div className="flex flex-wrap items-center gap-3 font-semibold text-slate-700">
                    <span>{zh ? `总计 ${preview.summary.total}` : `Total ${preview.summary.total}`}</span>
                    <span className="text-emerald-700">{zh ? `新增 ${preview.summary.create}` : `Create ${preview.summary.create}`}</span>
                    <span className="text-blue-700">{zh ? `更新 ${preview.summary.update}` : `Update ${preview.summary.update}`}</span>
                    <span className="text-slate-500">{zh ? `已有未变更 ${preview.summary.existing}` : `Unchanged ${preview.summary.existing}`}</span>
                    <span className="text-rose-700">{zh ? `冲突 ${preview.summary.conflict}` : `Conflicts ${preview.summary.conflict}`}</span>
                  </div>
                  {preview.conflicts.length > 0 && (
                    <ul role="alert" className="list-disc space-y-0.5 pl-4 text-rose-700">
                      {preview.conflicts.map((c, idx) => (
                        <li key={idx}>
                          {zh ? `第 ${c.row_number} 行 (${c.field})：${c.message}` : `Row ${c.row_number} (${c.field}): ${c.message}`}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
