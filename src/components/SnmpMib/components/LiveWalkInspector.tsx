import React, { useState, useMemo } from 'react';
import { Activity, Download, Copy, Search, Check, Sparkles, Server } from 'lucide-react';
import { apiRequest } from '../../../api/http';

export type SnmpWalkVersion = '1' | '2c';
export type SnmpWalkTargetStatus = 'idle' | 'loading' | 'matched' | 'multiple' | 'none' | 'error';

export interface SnmpWalkResult {
  host: string;
  oid: string;
  version: SnmpWalkVersion;
  port: number;
  status: 'ok' | 'no_data' | string;
  message: string;
  row_count: number;
  truncated: boolean;
  rows: Array<{ oid: string; value: string }>;
}

export interface CandidateDevice {
  device_id: string;
  hostname: string;
  ip_address?: string;
}

interface LiveWalkInspectorProps {
  zh: boolean;
  candidateDevices?: CandidateDevice[];
  fallbackOid?: string;
  saving?: boolean;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  onBackfillOid: (metricKey: string, oid: string) => void;
}

const inputClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 font-mono text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const selectClass =
  'w-full rounded-md border border-black/8 bg-transparent px-2 py-1.5 text-[10px] outline-none focus:border-[#00bceb]/55 dark:border-white/10';
const tinyLabelClass = 'mb-1 block text-[9px] text-black/45 dark:text-white/45';

export const LiveWalkInspector: React.FC<LiveWalkInspectorProps> = ({
  zh,
  candidateDevices = [],
  fallbackOid = '',
  saving = false,
  showToast,
  onBackfillOid,
}) => {
  const [walkTesting, setWalkTesting] = useState(false);
  const [walkIp, setWalkIp] = useState('');
  const [walkDeviceId, setWalkDeviceId] = useState('');
  const [walkTargetStatus, setWalkTargetStatus] = useState<SnmpWalkTargetStatus>('idle');
  const [walkTargetLabel, setWalkTargetLabel] = useState('');
  const [walkTargetError, setWalkTargetError] = useState('');
  const [walkVersion, setWalkVersion] = useState<SnmpWalkVersion>('2c');
  const [walkOid, setWalkOid] = useState('');
  const [walkMaxRows] = useState(2000);
  const [walkResult, setWalkResult] = useState<SnmpWalkResult | null>(null);
  const [filterKeyword, setFilterKeyword] = useState('');
  const [copySuccess, setCopySuccess] = useState(false);

  // Quick select a device from candidate inventory
  const handleSelectCandidate = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const devId = e.target.value;
    if (!devId) return;
    const dev = candidateDevices.find(item => item.device_id === devId);
    if (!dev) return;

    const ip = dev.ip_address || '';
    setWalkDeviceId(dev.device_id);
    setWalkIp(ip);
    setWalkTargetStatus('matched');
    setWalkTargetLabel(`${dev.hostname}${ip ? ` (${ip})` : ''}`);
    setWalkTargetError('');
    showToast(
      zh
        ? `已选中样例设备：${dev.hostname}${ip ? ` (${ip})` : ''}`
        : `Selected sample device: ${dev.hostname}`,
      'info',
    );
  };

  const clearWalkTargetConfirmation = (value: string) => {
    setWalkIp(value);
    setWalkDeviceId('');
    setWalkTargetStatus('idle');
    setWalkTargetLabel('');
    setWalkTargetError('');
    setWalkResult(null);
  };

  const confirmSnmpWalkTarget = async () => {
    const query = walkIp.trim();
    if (!query) {
      showToast(zh ? '请输入设备 IP 后按回车确认' : 'Enter a device IP and press Enter to confirm', 'error');
      return;
    }
    setWalkTargetStatus('loading');
    setWalkTargetError('');
    try {
      const response = await apiRequest<{ success: boolean; data: { ip: string; device_id: string; hostname?: string } }>(
        `/api/platform-registry/snmp-walk-target?ip=${encodeURIComponent(query)}`,
      );
      const targetIp = String(response.data?.ip || '').trim();
      if (!targetIp) throw new Error(zh ? '资产未返回有效 IP' : 'The asset did not return a valid IP');
      setWalkIp(targetIp);
      setWalkDeviceId(String(response.data.device_id || ''));
      setWalkTargetLabel([response.data.hostname, targetIp].filter(Boolean).join(' / '));
      setWalkTargetStatus('matched');
      showToast(zh ? `已确认 IP：${targetIp}` : `IP confirmed: ${targetIp}`, 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : zh ? '未找到该 IP' : 'IP not found';
      setWalkDeviceId('');
      setWalkTargetLabel('');
      setWalkTargetStatus('none');
      setWalkTargetError(message);
      showToast(zh ? '未找到该 IP，请先在资产管理中录入' : 'IP not found; add it in asset management first', 'error');
    }
  };

  const executeSnmpWalk = async () => {
    const oid = walkOid.trim() || fallbackOid;
    if (!walkIp.trim() && !walkDeviceId) {
      showToast(zh ? '请先选择样例设备或输入 IP' : 'Select a device or enter an IP first', 'error');
      return;
    }
    if (!walkDeviceId) {
      // If user typed IP but didn't press enter, try auto-confirm first
      await confirmSnmpWalkTarget();
      return;
    }
    if (!oid) {
      showToast(zh ? '请输入或配置起始探测 OID' : 'Enter an OID to probe', 'error');
      return;
    }
    if (!walkOid.trim()) setWalkOid(oid);
    setWalkTesting(true);
    setWalkResult(null);
    try {
      const response = await apiRequest<{ success: boolean; data: SnmpWalkResult }>(
        '/api/platform-registry/snmp-walk-test',
        {
          method: 'POST',
          body: JSON.stringify({
            device_id: walkDeviceId,
            version: walkVersion,
            oid,
            timeout: 5,
            max_rows: walkMaxRows,
          }),
        },
      );
      setWalkResult(response.data);
      showToast(
        response.data.status === 'ok'
          ? zh
            ? `WALK 探测成功，获取到 ${response.data.row_count} 行 OID 数据`
            : `WALK succeeded with ${response.data.row_count} rows`
          : response.data.message || (zh ? 'WALK 没有返回数据' : 'WALK returned no data'),
        response.data.status === 'ok' ? 'success' : 'error',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : zh ? 'SNMP WALK 探测失败' : 'SNMP WALK test failed', 'error');
    } finally {
      setWalkTesting(false);
    }
  };

  const filteredRows = useMemo(() => {
    if (!walkResult?.rows) return [];
    const kw = filterKeyword.trim().toLowerCase();
    if (!kw) return walkResult.rows;
    return walkResult.rows.filter(
      row => row.oid.toLowerCase().includes(kw) || String(row.value).toLowerCase().includes(kw),
    );
  }, [walkResult, filterKeyword]);

  const walkText = walkResult?.rows.map(row => `${row.oid} = ${row.value}`).join('\n') || '';

  const copyWalkOutput = async () => {
    if (!walkText) return;
    try {
      await navigator.clipboard.writeText(walkText);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2500);
      showToast(zh ? 'WALK 结果已复制到剪贴板' : 'WALK output copied', 'success');
    } catch {
      showToast(zh ? '复制失败，请手动选择复制' : 'Copy failed', 'error');
    }
  };

  const downloadWalkOutput = (format: 'text' | 'json') => {
    if (!walkResult) return;
    const content = format === 'json' ? JSON.stringify(walkResult, null, 2) : walkText;
    const blob = new Blob([content], {
      type: format === 'json' ? 'application/json;charset=utf-8' : 'text/plain;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `snmpwalk-${walkResult.host || 'result'}-${walkResult.oid || 'oid'}.${format === 'json' ? 'json' : 'txt'}`.replace(
      /[^a-zA-Z0-9_.-]/g,
      '_',
    );
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <section className="mb-4 rounded-xl border border-[#00bceb]/25 bg-[#00bceb]/[0.03] p-3.5 dark:bg-[#00bceb]/[0.05]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-black/75 dark:text-white/80">
            <Activity size={13} className="text-[#008aad] dark:text-[#00bceb]" />
            {zh ? 'SNMP WALK 实时探测与反向填充（只读安全）' : 'Live SNMP WALK & Backfill Inspector'}
          </div>
          <div className="mt-0.5 text-[9px] leading-4 text-black/45 dark:text-white/45">
            {zh
              ? '在线向设备发起 SNMP 只读探测，直接在探测返回的 OID 列表中点击一键填入指标，无需人工翻阅 MIB 树。'
              : 'Perform read-only SNMP probe on device and backfill OIDs directly into profile.'}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={executeSnmpWalk}
            disabled={walkTesting || saving}
            className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-3 py-1.5 text-[10px] font-semibold text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-45"
          >
            <Activity size={12} className={walkTesting ? 'animate-spin' : ''} />
            {walkTesting ? (zh ? '探测中...' : 'Testing...') : zh ? '执行 WALK 探测' : 'Run WALK'}
          </button>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {/* Candidate Device Quick Selector */}
        {candidateDevices.length > 0 && (
          <label className="block">
            <span className={tinyLabelClass}>{zh ? '从匹配资产快速选择' : 'Select matched device'}</span>
            <select value={walkDeviceId} onChange={handleSelectCandidate} className={selectClass}>
              <option value="">{zh ? '选择匹配型号的设备...' : 'Choose matched device...'}</option>
              {candidateDevices.map(dev => (
                <option key={dev.device_id} value={dev.device_id}>
                  {dev.hostname} {dev.ip_address ? `(${dev.ip_address})` : ''}
                </option>
              ))}
            </select>
          </label>
        )}

        {/* Manual IP Input */}
        <label className="block">
          <span className={tinyLabelClass}>{zh ? '设备 IP（输入后回车确认）' : 'Target IP (press Enter)'}</span>
          <input
            value={walkIp}
            onChange={event => clearWalkTargetConfirmation(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') {
                event.preventDefault();
                void confirmSnmpWalkTarget();
              }
            }}
            className={inputClass}
            placeholder="10.254.0.1"
          />
        </label>

        {/* SNMP Version */}
        <label className="block">
          <span className={tinyLabelClass}>{zh ? 'SNMP 版本' : 'SNMP version'}</span>
          <select
            value={walkVersion}
            onChange={event => setWalkVersion(event.target.value as SnmpWalkVersion)}
            className={selectClass}
          >
            <option value="2c">SNMPv2c</option>
            <option value="1">SNMPv1</option>
          </select>
        </label>

        {/* Start OID */}
        <label className="block">
          <span className={tinyLabelClass}>{zh ? '起始探测 OID' : 'Start OID'}</span>
          <input
            value={walkOid}
            onChange={event => setWalkOid(event.target.value)}
            className={inputClass}
            placeholder={fallbackOid || '1.3.6.1.2.1...'}
          />
        </label>
      </div>

      {/* Target status note */}
      <div
        className={
          (walkTargetStatus === 'matched'
            ? 'text-emerald-700 dark:text-emerald-400'
            : walkTargetStatus === 'multiple' || walkTargetStatus === 'none' || walkTargetStatus === 'error'
              ? 'text-amber-700 dark:text-amber-400'
              : 'text-black/45 dark:text-white/45') + ' mt-1.5 text-[9px] leading-4'
        }
      >
        {walkTargetStatus === 'idle' &&
          (zh
            ? '💡 可直接从左侧下拉框选择已有资产，或输入 IP 按回车关联 SNMP 凭据。'
            : 'Select an asset from dropdown or enter IP.')}
        {walkTargetStatus === 'loading' && (zh ? '正在匹配资产…' : 'Matching assets…')}
        {walkTargetStatus === 'matched' &&
          (zh ? `✓ 已匹配设备：${walkTargetLabel || '在线设备'}` : `✓ Matched: ${walkTargetLabel}`)}
        {walkTargetStatus === 'none' && (zh ? '未匹配到资产，请确认设备已录入资产管理。' : 'No managed asset matched.')}
        {walkTargetStatus === 'error' && (walkTargetError || (zh ? '匹配失败' : 'Matching failed'))}
      </div>

      {/* Result Section */}
      {walkResult && (
        <div className="mt-3 rounded-lg border border-black/8 bg-white/70 p-3 shadow-sm dark:border-white/10 dark:bg-white/[.04]">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[10px]">
            <div className="flex items-center gap-2">
              <span
                className={
                  walkResult.status === 'ok'
                    ? 'font-semibold text-emerald-700 dark:text-emerald-400'
                    : 'font-semibold text-red-700 dark:text-red-400'
                }
              >
                {walkResult.status === 'ok' ? '✓' : '✕'} {walkResult.message}
              </span>
              <span className="rounded bg-black/[.05] px-1.5 py-0.5 text-[9px] font-mono dark:bg-white/[.08]">
                {zh ? `共 ${walkResult.row_count} 行` : `${walkResult.row_count} rows`}
                {filteredRows.length !== walkResult.row_count &&
                  (zh ? ` · 筛选出 ${filteredRows.length} 行` : ` · ${filteredRows.length} filtered`)}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {/* Keyword filter input */}
              <div className="relative">
                <Search
                  size={11}
                  className="absolute left-2 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/30"
                />
                <input
                  value={filterKeyword}
                  onChange={e => setFilterKeyword(e.target.value)}
                  placeholder={zh ? '搜索 OID 或返回值...' : 'Filter OID or value...'}
                  className="h-6 w-36 rounded border border-black/10 bg-transparent pl-6 pr-1.5 text-[9px] outline-none focus:border-[#00bceb]/50 dark:border-white/10 sm:w-48"
                />
              </div>
              <button
                type="button"
                onClick={copyWalkOutput}
                disabled={!walkText}
                className="inline-flex items-center gap-0.5 rounded border border-black/10 bg-white/50 px-2 py-1 text-[9px] font-medium hover:bg-black/5 dark:border-white/10 dark:bg-white/[.05]"
              >
                {copySuccess ? <Check size={10} className="text-emerald-600" /> : <Copy size={10} />}
                {copySuccess ? (zh ? '已复制' : 'Copied') : zh ? '复制文本' : 'Copy'}
              </button>
              <button
                type="button"
                onClick={() => downloadWalkOutput('text')}
                disabled={!walkText}
                className="inline-flex items-center gap-0.5 rounded border border-black/10 bg-white/50 px-2 py-1 text-[9px] font-medium hover:bg-black/5 dark:border-white/10 dark:bg-white/[.05]"
              >
                <Download size={10} />
                {zh ? '下载 TXT' : 'TXT'}
              </button>
              <button
                type="button"
                onClick={() => downloadWalkOutput('json')}
                disabled={!walkText}
                className="inline-flex items-center gap-0.5 rounded border border-black/10 bg-white/50 px-2 py-1 text-[9px] font-medium hover:bg-black/5 dark:border-white/10 dark:bg-white/[.05]"
              >
                <Download size={10} />
                JSON
              </button>
            </div>
          </div>

          {/* Structured Rows Table for Backfill */}
          <div className="mt-2.5 max-h-56 overflow-y-auto rounded-lg border border-black/6 bg-black/[.02] dark:border-white/6 dark:bg-black/20">
            <table className="w-full text-left text-[10px]">
              <thead className="sticky top-0 bg-[var(--card-bg)] text-[9px] font-medium text-black/45 dark:text-white/45">
                <tr>
                  <th className="px-2.5 py-1.5 font-mono">OID</th>
                  <th className="px-2 py-1.5">{zh ? '当前返回值' : 'Value'}</th>
                  <th className="px-2.5 py-1.5 text-right">{zh ? '快捷反向填充到指标' : 'Quick Backfill'}</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="p-4 text-center text-xs text-black/40 dark:text-white/40">
                      {zh ? '未找到匹配的 OID 行' : 'No matching OID rows'}
                    </td>
                  </tr>
                ) : (
                  filteredRows.map((row, idx) => (
                    <tr
                      key={idx}
                      className="border-t border-black/5 hover:bg-[#00bceb]/[0.06] dark:border-white/5"
                    >
                      <td className="select-all px-2.5 py-1 font-mono text-[#008aad] dark:text-[#00bceb]">{row.oid}</td>
                      <td className="max-w-[240px] truncate px-2 py-1 font-mono text-black/70 dark:text-white/70">
                        {row.value}
                      </td>
                      <td className="px-2.5 py-1 text-right">
                        <div className="inline-flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => onBackfillOid('cpu', row.oid)}
                            className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                          >
                            {zh ? '设为 CPU' : 'Set CPU'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onBackfillOid('memory', row.oid)}
                            className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                          >
                            {zh ? '设为 内存' : 'Set Mem'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onBackfillOid('temperature', row.oid)}
                            className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                          >
                            {zh ? '设为 温度' : 'Set Temp'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onBackfillOid('fan', row.oid)}
                            className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                          >
                            {zh ? '设为 风扇' : 'Set Fan'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onBackfillOid('power_supply', row.oid)}
                            className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] font-medium text-black/70 hover:bg-[#00bceb]/20 hover:text-[#008aad] dark:bg-white/[.06] dark:text-white/80"
                          >
                            {zh ? '设为 电源' : 'Set Power'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
};
