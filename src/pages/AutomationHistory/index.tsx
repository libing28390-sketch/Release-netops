import React, { useState, useEffect, useCallback } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  History,
  RotateCcw,
  Search,
  Server,
  Trash2,
  User,
  X,
  XCircle,
  Copy,
  Check,
  Table2,
  FileText,
  Loader2,
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
  FileJson,
} from 'lucide-react';
import * as XLSX from 'xlsx';
import type { Device } from '../../types';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import OutputActions from '../../components/OutputActions';
import type { AutomationHistoryTabProps, PlaybookExecution } from './types';
import {
  splitOutputByCommand,
  downloadExcel,
  downloadJSON,
  copyToClipboard,
  downloadTextFile,
  getStatusMap,
} from './helpers';

const AutomationHistoryTab: React.FC<AutomationHistoryTabProps> = ({
  t,
  language,
  devices,
  playbookExecutions,
  playbookHistoryTotal,
  playbookHistoryPage,
  playbookHistoryStatusFilter,
  playbookHistoryScenarioSearch,
  activeExecutionId,
  executionStatus,
  wsMessages,
  selectedExecutionLoading,
  selectedExecutionDetail,
  selectedExecDevices,
  selectedExecDevicesTotal,
  selectedExecDevicesPage,
  selectedExecDevicesStatusFilter,
  selectedExecDevicesLoading,
  selectedDeviceDetail,
  selectedDeviceDetailLoading,
  onRefreshHistory,
  onScenarioSearchChange,
  onHistoryPageChange,
  onHistoryStatusFilterChange,
  onSelectExecution,
  onDeleteExecution,
  onExecDevicesStatusFilterChange,
  onExecDevicesPageChange,
  onSelectExecDevice,
  onCloseDeviceDetail,
  onRerun,
}) => {
  const isZh = language === 'zh';
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const isLive = !!(activeExecutionId && executionStatus === 'running');

  // ── TextFSM parse state (per command block key) ──
  // key format: `${phase}::${command}` for per-command granularity
  const [parseViewMode, setParseViewMode] = useState<Record<string, 'raw' | 'parsed'>>({});
  const [parseResults, setParseResults] = useState<Record<string, { loading: boolean; data: any; error: string }>>({});
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [collapsedBlocks, setCollapsedBlocks] = useState<Record<string, boolean>>({});

  const toggleBlockCollapse = useCallback((key: string) => {
    setCollapsedBlocks(prev => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // Reset parse state when device changes
  useEffect(() => {
    setParseViewMode({});
    setParseResults({});
    setCopiedKey(null);
    setCollapsedBlocks({});
  }, [selectedDeviceDetail]);

  useEffect(() => {
    if (isLive) {
      setIsDetailModalOpen(true);
    }
  }, [isLive]);

  const authHeaders = (() => {
    const token = localStorage.getItem('netops_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  })();

  // Parse a single command's output via TextFSM
  const handleParseCommand = useCallback(async (
    blockKey: string,
    platform: string,
    command: string,
    rawOutput: string,
    executionId: string,
    deviceId: string,
  ) => {
    setParseResults(prev => ({ ...prev, [blockKey]: { loading: true, data: null, error: '' } }));
    setParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' }));

    try {
      const res = await fetch(`/api/playbooks/${executionId}/devices/${deviceId}/parse`, {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform, command, output: rawOutput }),
      });
      const json = await res.json();
      if (json.success && json.data?.count > 0) {
        setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: json.data, error: '' } }));
      } else if (json.has_template === false) {
        setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: isZh ? `未找到 ${platform} / ${command} 的解析模板` : `No template for ${platform} / ${command}` } }));
        setParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }));
      } else {
        setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: json.message || (isZh ? '解析无结果' : 'No parse results') } }));
      }
    } catch {
      setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: isZh ? '解析请求失败' : 'Parse request failed' } }));
      setParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }));
    }
  }, [authHeaders, isZh]);

  const copyText = useCallback((text: string, key: string) => {
    copyToClipboard(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  }, []);

  const downloadText = useCallback((text: string, filename: string) => {
    downloadTextFile(text, filename);
  }, []);

  /**
   * Split a combined output string into per-command blocks.
   *
   * New format (produced by _exec_commands): each command's output is preceded by
   * a "# <command>" marker line, separated by blank lines.
   *
   * Old format (no markers): the whole output is one blob. In this case we create
   * one block per command in the commands array, all sharing the same raw output
   * so each command can still be individually parsed via TextFSM.
   */
  const splitOutputByCommand = useCallback((output: string, commands: string[]): Array<{ command: string; output: string }> => {
    if (!output && (!commands || commands.length === 0)) return [];
    const safeOutput = output || '';
    const safeCommands = commands || [];

    // 1. Try standard marker split: lines starting with "# <cmd>"
    const markerRe = /^#[ \t]+(?:[^:\n]+:[ \t]+)?(.+)$/m;
    if (markerRe.test(safeOutput)) {
      const blocks: Array<{ command: string; output: string }> = [];
      const lines = safeOutput.split('\n');
      let currentCmd = '';
      let currentLines: string[] = [];

      for (const line of lines) {
        const m = line.match(/^#[ \t]+(?:[^:\n]+:[ \t]+)?(.+)$/);
        if (m) {
          if (currentCmd || currentLines.some(l => l.trim())) {
            blocks.push({ command: currentCmd, output: currentLines.join('\n').trim() });
          }
          currentCmd = m[1].trim();
          currentLines = [];
        } else {
          currentLines.push(line);
        }
      }
      if (currentCmd || currentLines.some(l => l.trim())) {
        blocks.push({ command: currentCmd, output: currentLines.join('\n').trim() });
      }
      const valid = blocks.filter(b => b.command || b.output);
      if (valid.length > 0) return valid;
    }

    // 2. If we only have 0 or 1 command, return full blob directly
    if (safeCommands.length === 0) {
      return safeOutput.trim() ? [{ command: '', output: safeOutput.trim() }] : [];
    }
    if (safeCommands.length === 1) {
      return [{ command: safeCommands[0], output: safeOutput.trim() }];
    }

    // 3. Multi-command split strategy (Resonance & Signature matching inspired by Excel export)
    const lines = safeOutput.split('\n');
    
    // 3a. Search for command prompts in lines (e.g. "SW1# show version" or "show version")
    const cleanPromptRe = /^.*?[\#\>\$]\s*/;
    const foundHeaders: Array<{ lineIdx: number; cmd: string }> = [];
    
    for (let i = 0; i < lines.length; i++) {
      const sLine = lines[i].replace(cleanPromptRe, '').trim().toLowerCase();
      for (const cmd of safeCommands) {
        const cLower = cmd.trim().toLowerCase();
        if (sLine === cLower || sLine.startsWith(cLower + ' ')) {
          foundHeaders.push({ lineIdx: i, cmd });
          break;
        }
      }
    }

    // If we found command headers matching our expected commands
    if (foundHeaders.length > 0) {
      const extractedMap: Record<string, string> = {};
      for (let i = 0; i < foundHeaders.length; i++) {
        const startIdx = foundHeaders[i].lineIdx;
        const cmdName = foundHeaders[i].cmd;
        const endIdx = i + 1 < foundHeaders.length ? foundHeaders[i + 1].lineIdx : lines.length;
        const contentLines = lines.slice(startIdx + 1, endIdx);
        extractedMap[cmdName] = contentLines.join('\n').trim();
      }

      return safeCommands.map(cmd => ({
        command: cmd,
        output: (extractedMap[cmd] !== undefined && extractedMap[cmd].trim() !== '') 
          ? extractedMap[cmd] 
          : 'ℹ️ 无返回内容或未采集。'
      }));
    }

    // 3b. If no prompt headers found, use Signature & Sequential Boundary Analysis
    const sigMap: Record<string, string[]> = {
      'show version': ['cisco ios software', 'linux software', 'cisco internetwork operating system', 'software (i86bi', 'rom: bootstrap'],
      'show processes cpu': ['cpu utilization for five seconds', 'pid runtime', 'cpu utilization'],
      'show processes memory': ['processor pool total', 'pid tty allocated', 'holding getbufs', 'memory pool'],
      'show environment temperature': ['temperature', 'temperature status', 'inlet temperature', 'fan status', 'temp'],
      'show environment power': ['power supply', 'power status', 'watts', 'power consumption', 'psu'],
      'show environment': ['environmental status', 'temperature', 'power', 'fan'],
      'show interfaces status': ['port name status', 'duplex speed', 'port status', 'port vlan duplex speed'],
      'show interfaces': ['line protocol is', 'hardware is', '5 minute input rate', 'full-duplex'],
      'show ip bgp summary': ['bgp router identifier', 'neighbor v as', 'bgp table version'],
      'show ip bgp': ['bgp routing table', 'bgp router identifier'],
      'show ip ospf neighbor': ['neighbor id pri state', 'ospf process'],
      'show ip ospf': ['routing process "ospf', 'ospf router with id'],
      'show ip route summary': ['ip routing table', 'route source', 'subnets'],
      'show ip route': ['codes: l - local', 'gateway of last resort', 'routing table'],
      'show running-config': ['building configuration', 'current configuration', 'version 15.'],
      'show ip int': ['interface ip-address ok?'],
      'show inventory': ['name:', 'descr:', 'chassis'],
      'show clock': ['utc', 'cst', 'pst', 'est'],
    };

    const getSigs = (c: string): string[] => {
      const cLower = c.trim().toLowerCase();
      for (const [key, sigs] of Object.entries(sigMap)) {
        if (cLower.includes(key)) return sigs;
      }
      return [];
    };

    const resultBlocks: Array<{ command: string; output: string }> = [];
    let currIdx = 0;
    const totalLines = lines.length;
    let cmdI = 0;
    const totalCmds = safeCommands.length;
    const errRe = /^\s*(?:%|invalid|unknown|syntax error|bad command|unrecognized)/i;

    while (cmdI < totalCmds) {
      const cmd = safeCommands[cmdI];
      if (currIdx >= totalLines) {
        resultBlocks.push({ command: cmd, output: 'ℹ️ 无返回内容或未采集。' });
        cmdI++;
        continue;
      }

      const currentIsError = errRe.test(lines[currIdx]);

      if (!currentIsError) {
        let endIdx = totalLines;
        for (let offset = 0; offset < totalLines - currIdx; offset++) {
          const absIdx = currIdx + offset;
          const l = lines[absIdx];
          const lLower = l.trim().toLowerCase();

          if (offset > 1 && errRe.test(l)) {
            endIdx = absIdx;
            break;
          }

          let matchedNext = false;
          for (let nextCIdx = cmdI + 1; nextCIdx < totalCmds; nextCIdx++) {
            const nextCmd = safeCommands[nextCIdx];
            if (lLower.includes(nextCmd.toLowerCase()) && lLower.length < nextCmd.length + 15) {
              endIdx = absIdx;
              matchedNext = true;
              break;
            }
            const sigs = getSigs(nextCmd);
            if (sigs.length > 0 && sigs.some(sig => lLower.includes(sig))) {
              endIdx = absIdx;
              matchedNext = true;
              break;
            }
          }
          if (matchedNext) break;
        }

        const cmdContent = lines.slice(currIdx, endIdx).join('\n').trim();
        resultBlocks.push({ command: cmd, output: cmdContent || 'ℹ️ 执行成功，但无回显' });
        currIdx = endIdx;
        cmdI++;
      } else {
        // Error block resonance alignment
        let nextSuccessCmdIdx = -1;
        let foundSuccessLineIdx = totalLines;

        for (let nextCIdx = cmdI + 1; nextCIdx < totalCmds; nextCIdx++) {
          const nextCmd = safeCommands[nextCIdx];
          const sigs = getSigs(nextCmd);

          for (let offset = 0; offset < totalLines - currIdx; offset++) {
            const absIdx = currIdx + offset;
            const l = lines[absIdx];
            const lLower = l.trim().toLowerCase();
            if (!errRe.test(l)) {
              if (lLower.includes(nextCmd.toLowerCase()) && lLower.length < nextCmd.length + 15) {
                nextSuccessCmdIdx = nextCIdx;
                foundSuccessLineIdx = absIdx;
                break;
              }
              if (sigs.length > 0 && sigs.some(sig => lLower.includes(sig))) {
                nextSuccessCmdIdx = nextCIdx;
                foundSuccessLineIdx = absIdx;
                break;
              }
            }
          }
          if (nextSuccessCmdIdx !== -1) break;
        }

        const chunkLines = lines.slice(currIdx, foundSuccessLineIdx);
        const countToAssign = (nextSuccessCmdIdx !== -1 ? nextSuccessCmdIdx : totalCmds) - cmdI;

        if (countToAssign === 1) {
          resultBlocks.push({ command: cmd, output: chunkLines.join('\n').trim() });
        } else {
          const errChunks: string[] = [];
          let currErrChunk: string[] = [];
          for (const cl of chunkLines) {
            const clStr = cl.trim();
            const isCaretOnly = clStr.length > 0 && clStr.split('').every(ch => ch === '^' || ch === ' ');
            const isErrStart = errRe.test(cl) || isCaretOnly;
            const hasRealText = currErrChunk.some(x => /[a-zA-Z0-9%]/.test(x));

            if (isErrStart && hasRealText) {
              errChunks.push(currErrChunk.join('\n').trim());
              currErrChunk = [cl];
            } else {
              currErrChunk.push(cl);
            }
          }
          if (currErrChunk.length > 0) {
            errChunks.push(currErrChunk.join('\n').trim());
          }
          const validErrChunks = errChunks.filter(ch => ch.trim() !== '');

          const cmdsToAssign = safeCommands.slice(cmdI, cmdI + countToAssign);
          const assignedOut: Record<string, string> = {};
          const remainingErrs = [...validErrChunks];
          const remainingCmds = [...cmdsToAssign];

          for (const errTxt of [...remainingErrs]) {
            const errLower = errTxt.toLowerCase();
            let matchedCmd: string | undefined = undefined;
            if (errLower.includes('bgp')) {
              matchedCmd = remainingCmds.find(c => c.toLowerCase().includes('bgp'));
            } else if (errLower.includes('ospf')) {
              matchedCmd = remainingCmds.find(c => c.toLowerCase().includes('ospf'));
            } else if (errLower.includes('interface') || errLower.includes('drop') || errLower.includes('line protocol')) {
              matchedCmd = remainingCmds.find(c => c.toLowerCase().includes('interface') || c.toLowerCase().includes('int'));
            }

            if (matchedCmd) {
              assignedOut[matchedCmd] = errTxt;
              remainingErrs.splice(remainingErrs.indexOf(errTxt), 1);
              remainingCmds.splice(remainingCmds.indexOf(matchedCmd), 1);
            }
          }

          for (const errTxt of remainingErrs) {
            if (remainingCmds.length > 0) {
              const cmdTarget = remainingCmds.shift()!;
              assignedOut[cmdTarget] = errTxt;
            }
          }

          for (const cName of cmdsToAssign) {
            resultBlocks.push({ command: cName, output: assignedOut[cName] || 'ℹ️ 执行成功，但无回显' });
          }
        }

        currIdx = foundSuccessLineIdx;
        cmdI = nextSuccessCmdIdx !== -1 ? nextSuccessCmdIdx : totalCmds;
      }
    }

    return resultBlocks;
  }, []);

  /** Export parsed records to a real .xlsx file */
  const downloadExcel = useCallback((records: Record<string, any>[], fields: string[], filename: string) => {
    if (!records || records.length === 0) return;
    const data = records.map(r => {
      const row: Record<string, any> = {};
      for (const f of fields) row[f] = r[f] ?? '';
      return row;
    });
    const ws = XLSX.utils.json_to_sheet(data, { header: fields });
    // Auto column width
    ws['!cols'] = fields.map(f => {
      const maxLen = Math.max(f.length, ...data.map(r => String(r[f] ?? '').length));
      return { wch: Math.min(Math.max(maxLen + 2, 10), 60) };
    });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Parsed');
    XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`);
  }, []);

  /** Export parsed records as pretty-printed JSON */
  const downloadJSON = useCallback((records: Record<string, any>[], filename: string) => {
    if (!records || records.length === 0) return;
    const text = JSON.stringify(records, null, 2);
    const blob = new Blob([text], { type: 'application/json;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename.endsWith('.json') ? filename : `${filename}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  /**
   * Download an Excel summary of the whole execution:
   *   - Sheet 1: 概览 (execution + devices summary)
   *   - Sheet 2..N: per-device per-command raw output
   * Requires a loaded execution detail and devices list.
   */
  const handleDownloadExecutionExcel = useCallback(async () => {
    const execution = selectedExecutionDetail;
    if (!execution) return;

    const execId = execution.id;
    const wb = XLSX.utils.book_new();

    // ── Sheet 1: 概览 ──
    const overviewRows: Record<string, any>[] = [
      { 字段: isZh ? '作业名称' : 'Job Name', 值: execution.scenario_name || execution.task_name || '-' },
      { 字段: 'Execution ID', 值: execId },
      { 字段: isZh ? '执行人' : 'Operator', 值: execution.author || 'admin' },
      { 字段: isZh ? '触发时间' : 'Triggered At', 值: new Date(execution.created_at).toLocaleString() },
      { 字段: isZh ? '状态' : 'Status', 值: execution.status || '-' },
      { 字段: isZh ? '总设备数' : 'Total Devices', 值: execution.total_devices ?? 0 },
      { 字段: isZh ? '成功' : 'Success', 值: execution.success_count ?? 0 },
      { 字段: isZh ? '失败' : 'Failed', 值: execution.failed_count ?? 0 },
      { 字段: isZh ? '部分' : 'Partial', 值: execution.partial_count ?? 0 },
    ];
    const wsOverview = XLSX.utils.json_to_sheet(overviewRows);
    wsOverview['!cols'] = [{ wch: 22 }, { wch: 60 }];
    XLSX.utils.book_append_sheet(wb, wsOverview, isZh ? '概览' : 'Overview');

    // ── Sheet 2: 设备汇总 ──
    const deviceSummary = selectedExecDevices.map(d => ({
      [isZh ? '主机名' : 'Hostname']: d.hostname,
      [isZh ? 'IP 地址' : 'IP Address']: d.ip_address || '',
      [isZh ? '状态' : 'Status']: d.status || '',
      [isZh ? '耗时(ms)' : 'Duration(ms)']: d.duration_ms ?? 0,
      [isZh ? '错误信息' : 'Error']: d.error_message || '',
    }));
    if (deviceSummary.length > 0) {
      const wsDev = XLSX.utils.json_to_sheet(deviceSummary);
      const cols = Object.keys(deviceSummary[0]);
      wsDev['!cols'] = cols.map(k => {
        const maxLen = Math.max(k.length, ...deviceSummary.map(r => String((r as any)[k] ?? '').length));
        return { wch: Math.min(Math.max(maxLen + 2, 10), 60) };
      });
      XLSX.utils.book_append_sheet(wb, wsDev, isZh ? '设备汇总' : 'Devices');
    }

    // ── Sheet 3..N: per-device per-command output ──
    // Fetch full detail for each device (if we have the list)
    const token = localStorage.getItem('netops_token');
    const hdr: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    for (const dev of selectedExecDevices) {
      try {
        const res = await fetch(`/api/playbooks/${execId}/devices/${dev.device_id}`, { headers: hdr });
        if (!res.ok) continue;
        const detail = await res.json();
        let phases: Record<string, any> = {};
        try { phases = JSON.parse(detail.phases_json || '{}'); } catch { phases = {}; }

        const rows: Record<string, any>[] = [];
        for (const [phaseName, pdata] of Object.entries(phases)) {
          const pd: any = pdata || {};
          const cmds: string[] = pd.commands || [];
          const outputStr: string = typeof pd.output === 'string' ? pd.output : JSON.stringify(pd.output || '');
          // Try to split per-command via our helper
          const blocks = splitOutputByCommand(outputStr, cmds);
          for (const blk of blocks) {
            rows.push({
              [isZh ? '阶段' : 'Phase']: phaseName,
              [isZh ? '命令' : 'Command']: blk.command || '-',
              [isZh ? '输出' : 'Output']: blk.output || '',
            });
          }
          if (blocks.length === 0 && outputStr) {
            rows.push({
              [isZh ? '阶段' : 'Phase']: phaseName,
              [isZh ? '命令' : 'Command']: cmds.join(' | ') || '-',
              [isZh ? '输出' : 'Output']: outputStr,
            });
          }
        }
        if (rows.length === 0) continue;

        const ws = XLSX.utils.json_to_sheet(rows);
        ws['!cols'] = [
          { wch: 12 },
          { wch: 40 },
          { wch: 80 },
        ];
        // Sheet name max 31 chars, no special chars
        const rawName = (dev.hostname || dev.ip_address || dev.device_id || 'device').replace(/[\\/?*[\]:]/g, '_');
        const sheetName = rawName.slice(0, 31);
        // Avoid duplicate sheet names
        let unique = sheetName;
        let i = 2;
        while (wb.SheetNames.includes(unique)) {
          unique = `${sheetName.slice(0, 28)}_${i++}`;
        }
        XLSX.utils.book_append_sheet(wb, ws, unique);
      } catch {
        // Skip devices that fail to load
      }
    }

    const filename = `execution_${(execution.scenario_name || 'summary').replace(/[^a-zA-Z0-9\u4e00-\u9fa5]+/g, '_').slice(0, 50)}_${execId.slice(0, 8)}.xlsx`;
    XLSX.writeFile(wb, filename);
  }, [selectedExecutionDetail, selectedExecDevices, splitOutputByCommand, isZh]);

  // Helper mapping for execution status badge
  const getStatusMap = (status?: string) => {
    const statusMap: Record<string, { label: string; cls: string; dot: string }> = {
      success: { label: isZh ? '执行成功' : 'Success', cls: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500' },
      running: { label: isZh ? '执行中' : 'Running', cls: 'bg-cyan-50 text-cyan-700', dot: 'bg-cyan-500 animate-pulse' },
      pending: { label: isZh ? '排队中' : 'Pending', cls: 'bg-blue-50 text-blue-700', dot: 'bg-blue-500' },
      dry_run_complete: { label: isZh ? '模拟完成' : 'Dry-Run', cls: 'bg-amber-50 text-amber-700', dot: 'bg-amber-500' },
    };
    return statusMap[status || ''] || { 
      label: isZh ? '执行失败' : 'Failed', 
      cls: 'bg-red-50 text-red-700 border-red-100', 
      dot: 'bg-red-500' 
    };
  };

  const handleDownloadSummary = () => {
    if (!selectedExecutionDetail) return;
    const dataStr = JSON.stringify(selectedExecutionDetail, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `execution_summary_${selectedExecutionDetail.id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Toggle state for the header download menu
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const [downloadingExcel, setDownloadingExcel] = useState(false);
  const handleDownloadSummaryExcel = async () => {
    setDownloadingExcel(true);
    try {
      await handleDownloadExecutionExcel();
    } finally {
      setDownloadingExcel(false);
      setDownloadMenuOpen(false);
    }
  };

  const handleDownloadLogStream = () => {
    if (!wsMessages || wsMessages.length === 0) return;
    const logStr = wsMessages
      .map((msg, idx) => {
        let line = `[${idx + 1}] `;
        if (msg.type === 'start') line += `▶ Playbook started — ${msg.total_devices} devices`;
        else if (msg.type === 'device_start') line += `┌─ ${msg.hostname}`;
        else if (msg.type === 'phase_start') line += `│  ⏳ ${msg.phase?.toUpperCase()} commands`;
        else if (msg.type === 'phase_done') line += `│  ✓ ${msg.phase?.toUpperCase()} complete`;
        else if (msg.type === 'device_done') line += `└─ ${msg.hostname} — ${msg.status}`;
        else if (msg.type === 'device_error') line += `✗ ERROR — ${msg.device_id}: ${msg.error}`;
        else if (msg.type === 'complete') line += `\n✦ COMPLETE — Status: ${msg.status}`;
        return line;
      })
      .join('\n');

    const blob = new Blob([logStr], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `live_log_stream_${activeExecutionId}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <PageHero
        icon={History}
        title={t('executionHistory')}
        subtitle={t('executionHistoryDesc')}
        actions={
          <button
            onClick={() => void onRefreshHistory()}
            title={isZh ? '刷新执行历史' : 'Refresh execution history'}
            className="p-2 rounded-xl border border-black/10 hover:bg-black/5 transition-all"
          >
            <RotateCcw size={14} />
          </button>
        }
      />

      <div className="flex-1 flex flex-col px-6 py-5 overflow-hidden">
      <div className="flex-1 bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden flex flex-col min-h-[500px]">
        {/* Toolbar */}
        <div className="px-6 py-4 border-b border-black/5 bg-black/[0.01] flex items-center justify-between flex-wrap gap-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center">
              <History size={16} className="text-indigo-600" />
            </div>
            <h3 className="text-sm font-bold text-[#164e63]">
              {playbookHistoryTotal > 0 ? `${playbookHistoryTotal} ${isZh ? '条记录' : 'Records'}` : `${playbookExecutions.length} ${isZh ? '条记录' : 'Records'}`}
            </h3>
          </div>
          
          <div className="flex items-center gap-3 flex-wrap">
            {/* Search Input */}
            <div className="relative w-64">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/25" />
              <input
                type="text"
                value={playbookHistoryScenarioSearch}
                onChange={(event) => {
                  onScenarioSearchChange(event.target.value);
                  onHistoryPageChange(1);
                  void onRefreshHistory(1, playbookHistoryStatusFilter, event.target.value);
                }}
                placeholder={isZh ? '搜索任务名称...' : 'Search scenario...'}
                className="w-full text-xs pl-9 pr-8 py-2 rounded-xl bg-black/[0.03] border border-transparent focus:outline-none focus:border-black/10 focus:bg-white transition-all shadow-inner"
              />
              {playbookHistoryScenarioSearch && (
                <button
                  onClick={() => {
                    onScenarioSearchChange('');
                    onHistoryPageChange(1);
                    void onRefreshHistory(1, playbookHistoryStatusFilter, '');
                  }}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-black/25 hover:text-black/50"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            {/* Filter Buttons */}
            <div className="flex items-center gap-1.5 p-1 rounded-xl bg-black/[0.03] border border-black/5">
              {[
                { key: 'all', label: isZh ? '全部' : 'All', cls: 'bg-white shadow-sm text-black' },
                { key: 'success', label: isZh ? '成功' : '✓', cls: 'bg-emerald-500 text-white shadow-sm shadow-emerald-500/20' },
                { key: 'failed', label: isZh ? '失败' : '✗', cls: 'bg-red-500 text-white shadow-sm shadow-red-500/20' },
                { key: 'partial_failure', label: isZh ? '部分' : 'Partial', cls: 'bg-amber-500 text-white shadow-sm shadow-amber-500/20' },
                { key: 'dry_run_complete', label: 'DRY', cls: 'bg-cyan-500 text-white shadow-sm shadow-cyan-500/20' },
              ].map((filterItem) => {
                const isActive = playbookHistoryStatusFilter === filterItem.key;
                return (
                  <button
                    key={filterItem.key}
                    onClick={() => {
                      onHistoryStatusFilterChange(filterItem.key);
                      onHistoryPageChange(1);
                      void onRefreshHistory(1, filterItem.key, playbookHistoryScenarioSearch);
                    }}
                    className={`text-[10px] font-bold px-3 py-1.5 rounded-lg transition-all ${
                      isActive ? filterItem.cls : 'text-black/40 hover:text-black/60 hover:bg-white/50'
                    }`}
                  >
                    {filterItem.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Table Content */}
        <div className="flex-1 overflow-auto">
          {playbookExecutions.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-black/20 py-24">
              <History size={48} strokeWidth={1} className="opacity-10" />
              <p className="mt-3 text-sm font-medium">{t('noExecutions')}</p>
            </div>
          ) : (
            <table className="w-full text-left border-collapse min-w-[900px]">
              <thead className="sticky top-0 bg-slate-50 border-b border-black/5 z-10">
                <tr className="bg-black/[0.01]">
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '任务名称' : 'Scenario Name'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '触发时间' : 'Triggered At'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '状态' : 'Status'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '设备概况' : 'Devices Info'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider">{isZh ? '执行人' : 'Operator'}</th>
                  <th className="px-6 py-4 text-[11px] font-bold text-black/35 uppercase tracking-wider text-right">{isZh ? '操作' : 'Actions'}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.03]">
                {playbookExecutions.map((execution) => {
                  const isRowLive = execution.id === activeExecutionId && executionStatus === 'running';
                  const deviceCount = execution.total_devices || (() => {
                    try { return JSON.parse(execution.device_ids || '[]').length; } catch { return 0; }
                  })();
                  const st = getStatusMap(execution.status);

                  return (
                    <tr key={execution.id} className="group hover:bg-indigo-50/20 transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex flex-col">
                          <span className="text-sm font-bold text-[#164e63] group-hover:text-cyan-700 transition-colors">
                            {execution.scenario_name || execution.task_name || (isZh ? '快捷命令' : 'Direct Command')}
                          </span>
                          {execution._type === 'job' && (
                            <span className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyan-50 text-cyan-600 self-start mt-1">DIRECT</span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-xs font-mono text-black/60 whitespace-nowrap">
                        {new Date(execution.created_at).toLocaleString()}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold ${st.cls}`}>
                          <div className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                          {st.label}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2 text-xs font-bold text-black/60">
                          <span className="flex items-center gap-1"><Server size={12} />{deviceCount}</span>
                          {(execution.success_count || 0) > 0 && <span className="text-emerald-500">✓{execution.success_count}</span>}
                          {(execution.failed_count || 0) > 0 && <span className="text-red-500">✗{execution.failed_count}</span>}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-xs text-black/60 font-medium">
                        {execution.author || 'admin'}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => onRerun(execution)}
                            className="flex items-center gap-1 px-2 py-1.5 text-xs text-amber-600 hover:bg-amber-50 font-bold rounded-lg transition-all"
                            title={isZh ? '重复执行' : 'Rerun'}
                          >
                            <RotateCcw size={14} />
                            <span className="hidden sm:inline">{isZh ? '重试' : 'Retry'}</span>
                          </button>
                          <button
                            onClick={() => {
                              void onSelectExecution(execution);
                              setIsDetailModalOpen(true);
                            }}
                            className="flex items-center gap-1 px-2 py-1.5 text-xs text-[#0e7490] hover:bg-cyan-50 font-bold rounded-lg transition-all"
                          >
                            {isZh ? '详情' : 'Details'}
                          </button>
                          {!isRowLive && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                void onDeleteExecution(execution);
                              }}
                              className="p-2 rounded-lg text-black/25 hover:text-red-500 hover:bg-red-50 transition-all"
                              title={isZh ? '删除' : 'Delete'}
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination footer */}
        {playbookHistoryTotal > 20 && (
          <div className="px-6 py-4 border-t border-black/5 bg-black/[0.01] flex-shrink-0">
            <Pagination
              currentPage={playbookHistoryPage}
              totalItems={playbookHistoryTotal}
              itemsPerPage={20}
              onPageChange={onHistoryPageChange}
              language={language}
            />
          </div>
        )}
      </div>

      {/* Detail Modal */}
      <AnimatePresence>
        {isDetailModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsDetailModalOpen(false)}
              className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="relative bg-white rounded-[2rem] shadow-2xl w-full max-w-6xl h-[90vh] overflow-hidden flex flex-col z-10 border border-black/10"
            >
              {/* Modal Header */}
              <div className="px-6 py-4 border-b border-black/5 flex items-center justify-between bg-black/[0.015] flex-shrink-0">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 border border-indigo-100">
                    <History size={18} />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-[#164e63]">
                      {isLive ? (isZh ? '正在执行详情' : 'Live Execution Log') : (isZh ? '执行历史详情' : 'Execution Log Details')}
                    </h3>
                    <p className="text-[10px] text-black/30 font-mono mt-0.5">ID: {activeExecutionId || selectedExecutionDetail?.id}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!isLive && selectedExecutionDetail && (
                    <div className="relative">
                      <button
                        onClick={() => setDownloadMenuOpen(v => !v)}
                        title={isZh ? '下载汇总报告' : 'Download Summary'}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-xl text-[#0891b2] border border-cyan-100 bg-cyan-50/30 hover:bg-cyan-50 hover:text-[#0e7490] transition-all text-[11px] font-semibold"
                      >
                        {downloadingExcel ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                        {isZh ? '下载汇总' : 'Download'}
                        <ChevronDown size={12} />
                      </button>
                      <AnimatePresence>
                        {downloadMenuOpen && (
                          <motion.div
                            initial={{ opacity: 0, y: -4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -4 }}
                            className="absolute right-0 top-full mt-1 w-48 bg-white rounded-xl border border-black/[0.08] shadow-xl overflow-hidden z-20"
                          >
                            <button
                              onClick={() => { setDownloadMenuOpen(false); handleDownloadSummary(); }}
                              className="w-full flex items-center gap-2 px-3 py-2 text-[11px] font-medium text-black/70 hover:bg-indigo-50 hover:text-indigo-700 transition-colors"
                            >
                              <FileJson size={13} className="text-indigo-500" />
                              <div className="text-left flex-1">
                                <div className="font-semibold">{isZh ? 'JSON 汇总' : 'JSON Summary'}</div>
                                <div className="text-[9px] text-black/40">{isZh ? '执行元数据' : 'Metadata only'}</div>
                              </div>
                            </button>
                            <div className="border-t border-black/[0.04]" />
                            <button
                              onClick={() => void handleDownloadSummaryExcel()}
                              disabled={downloadingExcel}
                              className="w-full flex items-center gap-2 px-3 py-2 text-[11px] font-medium text-black/70 hover:bg-emerald-50 hover:text-emerald-700 transition-colors disabled:opacity-50"
                            >
                              {downloadingExcel ? <Loader2 size={13} className="animate-spin text-emerald-500" /> : <FileSpreadsheet size={13} className="text-emerald-500" />}
                              <div className="text-left flex-1">
                                <div className="font-semibold">{isZh ? 'Excel 汇总' : 'Excel Report'}</div>
                                <div className="text-[9px] text-black/40">{isZh ? '含各设备完整输出' : 'With per-device output'}</div>
                              </div>
                            </button>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )}
                  {isLive && wsMessages.length > 0 && (
                    <button
                      onClick={handleDownloadLogStream}
                      title={isZh ? '导出实时日志' : 'Export Live Stream'}
                      className="p-2 rounded-xl text-[#0891b2] border border-cyan-100 bg-cyan-50/30 hover:bg-cyan-50 hover:text-[#0e7490] transition-all"
                    >
                      <Download size={16} />
                    </button>
                  )}
                  <button
                    onClick={() => setIsDetailModalOpen(false)}
                    className="p-2 rounded-xl text-black/20 hover:bg-black/5 hover:text-black/40 transition-all"
                  >
                    <X size={20} />
                  </button>
                </div>
              </div>

              {/* Modal Content */}
              <div className="flex-1 overflow-hidden relative">
                {isLive ? (
                  /* Live Streaming Panel */
                  <div className="flex flex-col h-full bg-[#1E1E1E] font-mono text-xs p-6 overflow-auto space-y-1">
                    {wsMessages.map((message, index) => {
                      const color =
                        message.type === 'start' ? 'text-blue-400' :
                          message.type === 'device_start' ? 'text-cyan-400' :
                            message.type === 'phase_start' ? 'text-purple-400' :
                              message.type === 'phase_done' ? 'text-emerald-400' :
                                message.type === 'device_done' ? 'text-green-300' :
                                  message.type === 'rollback_start' || message.type === 'rollback_done' ? 'text-red-400' :
                                    message.type === 'device_error' ? 'text-red-500' :
                                      message.type === 'complete' ? 'text-yellow-300' :
                                        'text-[#d4d4d4]';
                      return (
                        <div key={index} className={`${color} leading-5`}>
                          <span className="text-white/20 mr-2">{String(index + 1).padStart(3, ' ')}</span>
                          {message.type === 'start' && `▶ Playbook started — ${message.total_devices} device(s) ${message.dry_run ? '[DRY-RUN]' : ''}`}
                          {message.type === 'device_start' && `┌─ ${message.hostname} (${message.index! + 1}/${message.total})`}
                          {message.type === 'phase_start' && `│  ⏳ ${message.phase?.replace(/_/g, ' ').toUpperCase()} — ${message.commands?.length || 0} command(s) ${message.dry_run ? '[DRY-RUN]' : ''}`}
                          {message.type === 'phase_done' && `│  ✓ ${message.phase?.replace(/_/g, ' ').toUpperCase()} ${message.dry_run ? '[DRY-RUN]' : '— done'}`}
                          {message.type === 'phase_done' && message.output?.output && (
                            <div className="ml-8 text-[#d4d4d4]/60 whitespace-pre-wrap">{message.output.output.slice(0, 500)}</div>
                          )}
                          {message.type === 'device_done' && `└─ ${message.hostname} — ${message.status}`}
                          {message.type === 'rollback_start' && `│  ⚠ ROLLBACK TRIGGERED — ${message.hostname}`}
                          {message.type === 'rollback_done' && `│  ↩ Rollback complete — ${message.hostname}`}
                          {message.type === 'device_error' && `✗ ERROR — ${message.device_id}: ${message.error}`}
                          {message.type === 'complete' && `\n✦ COMPLETE — Status: ${message.status} | Success: ${message.summary?.success}/${message.summary?.total} | Failed: ${message.summary?.failed}`}
                        </div>
                      );
                    })}
                    <div className="h-4" />
                  </div>
                ) : (
                  /* Loaded Results Panel */
                  (() => {
                    if (selectedExecutionLoading) {
                      return (
                        <div className="h-full flex items-center justify-center text-black/30">
                          <RotateCcw size={20} className="animate-spin" />
                        </div>
                      );
                    }

                    const execution = selectedExecutionDetail || playbookExecutions.find((item) => item.id === activeExecutionId);
                    if (!execution) {
                      return <div className="p-8 text-center text-black/20 text-sm">{t('noData')}</div>;
                    }

                    const executionStatusMap: Record<string, { label: string; cls: string }> = {
                      success: { label: isZh ? '成功' : 'Success', cls: 'bg-emerald-500 text-white' },
                      failed: { label: isZh ? '失败' : 'Failed', cls: 'bg-red-500 text-white' },
                      partial_failure: { label: isZh ? '部分失败' : 'Partial Failure', cls: 'bg-amber-500 text-white' },
                      dry_run_complete: { label: 'DRY-RUN', cls: 'bg-cyan-500 text-white' },
                    };
                    const executionSt = executionStatusMap[execution.status || ''] || { label: execution.status || 'Failed', cls: 'bg-red-500 text-white' };

                    return (
                      <div className="flex flex-col md:flex-row h-full">
                        {/* Device List (Left) */}
                        <div className="w-full md:w-5/12 border-r border-black/5 flex flex-col h-full bg-slate-50/50">
                          {/* Left Header */}
                          <div className="p-4 border-b border-black/5 bg-white">
                            <div className="flex items-center justify-between mb-3">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-bold text-black/50">{isZh ? '设备执行情况' : 'Device Execution'}</span>
                                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${executionSt.cls}`}>{executionSt.label}</span>
                              </div>
                              <span className="text-[10px] font-mono text-black/40">{new Date(execution.created_at).toLocaleString()}</span>
                            </div>
                            
                            {/* Device List Filters */}
                            <div className="flex items-center gap-2 flex-wrap">
                              {/* Search */}
                              <div className="flex items-center gap-1.5 p-1 rounded-lg bg-black/[0.03] border border-black/5">
                                {[
                                  { key: 'all', label: isZh ? '全部' : 'All' },
                                  { key: 'success', label: isZh ? '成功' : 'Pass' },
                                  { key: 'failed', label: isZh ? '失败' : 'Fail' },
                                ].map((filterItem) => {
                                  const isActive = selectedExecDevicesStatusFilter === filterItem.key;
                                  return (
                                    <button
                                      key={filterItem.key}
                                      onClick={() => void onExecDevicesStatusFilterChange(filterItem.key)}
                                      className={`text-[9px] font-bold px-2.5 py-1 rounded-md transition-all ${
                                        isActive ? 'bg-white shadow-sm text-[#164e63]' : 'text-black/40 hover:text-black/60'
                                      }`}
                                    >
                                      {filterItem.label}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          </div>

                          {/* Device Items */}
                          <div className="flex-1 overflow-auto p-2 space-y-1">
                            {selectedExecDevicesLoading ? (
                              <div className="h-32 flex items-center justify-center text-black/20"><RotateCcw size={16} className="animate-spin" /></div>
                            ) : selectedExecDevices.length === 0 ? (
                              <p className="text-center text-[10px] text-black/20 py-8">{t('noData')}</p>
                            ) : (
                              selectedExecDevices.map((dev) => {
                                const stMap: Record<string, { cls: string; label: string }> = {
                                  success: { cls: 'bg-emerald-500', label: isZh ? '完成' : 'Pass' },
                                  failed: { cls: 'bg-red-500', label: isZh ? '失败' : 'Fail' },
                                  running: { cls: 'bg-cyan-500 animate-pulse', label: isZh ? '执行中' : 'Live' },
                                };
                                const dst = stMap[dev.status || ''] || { cls: 'bg-red-500', label: isZh ? '错误' : 'Fail' };

                                return (
                                  <div
                                    key={dev.device_id}
                                    onClick={() => void onSelectExecDevice(dev.device_id)}
                                    className="flex items-center justify-between p-3 rounded-xl bg-white border border-black/5 hover:border-black/10 hover:shadow-sm cursor-pointer transition-all"
                                  >
                                    <div className="min-w-0">
                                      <p className="text-xs font-bold text-[#164e63] truncate">{dev.hostname}</p>
                                      <p className="text-[10px] text-black/30 font-mono mt-0.5">{dev.ip_address || '0.0.0.0'}</p>
                                    </div>
                                    <div className="flex items-center gap-2 shrink-0">
                                      {dev.duration_ms !== undefined && (
                                        <span className="text-[10px] text-black/40 font-mono">{dev.duration_ms >= 1000 ? `${(dev.duration_ms / 1000).toFixed(1)}s` : `${dev.duration_ms}ms`}</span>
                                      )}
                                      <span className={`text-[9px] font-bold text-white px-2 py-0.5 rounded-md ${dst.cls}`}>{dst.label}</span>
                                    </div>
                                  </div>
                                );
                              })
                            )}
                          </div>

                          {/* Left Pagination */}
                          {selectedExecDevicesTotal > 20 && (
                            <div className="p-3 border-t border-black/5 bg-white flex-shrink-0">
                              <Pagination
                                currentPage={selectedExecDevicesPage}
                                totalItems={selectedExecDevicesTotal}
                                itemsPerPage={20}
                                onPageChange={onExecDevicesPageChange}
                                language={language}
                              />
                            </div>
                          )}
                        </div>

                        {/* Device Detail Output (Right) */}
                        <div className="w-full md:w-7/12 flex flex-col h-full bg-white relative">
                          {selectedDeviceDetailLoading ? (
                            <div className="h-full flex items-center justify-center text-black/30"><RotateCcw size={20} className="animate-spin" /></div>
                          ) : selectedDeviceDetail ? (
                            <div className="flex flex-col h-full">
                              <div className="p-4 border-b border-black/5 bg-black/[0.01] flex-shrink-0">
                                <div className="flex items-center justify-between mb-3">
                                  <div>
                                    <p className="text-xs font-bold text-[#164e63]">{selectedDeviceDetail.hostname}</p>
                                    <p className="text-[10px] font-mono text-black/40 mt-0.5">{selectedDeviceDetail.ip_address}</p>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    {selectedDeviceDetail.duration_ms !== undefined && (
                                      <span className="text-[10px] font-bold px-2 py-1 bg-black/[0.03] text-black/40 rounded-lg">
                                        {selectedDeviceDetail.duration_ms >= 1000 ? `${(selectedDeviceDetail.duration_ms / 1000).toFixed(2)} s` : `${selectedDeviceDetail.duration_ms} ms`}
                                      </span>
                                    )}
                                    {(() => {
                                      let logText = '';
                                      try {
                                        const phases = JSON.parse(selectedDeviceDetail.phases_json || '{}');
                                        Object.entries(phases).forEach(([name, p]: [string, any]) => {
                                          logText += `[PHASE: ${String(name).toUpperCase()}]\n`;
                                          if (p?.commands && Array.isArray(p.commands) && p.commands.length > 0) {
                                            logText += p.commands.map((c: string) => `> ${c}`).join('\n') + '\n';
                                          }
                                          if (p?.output) {
                                            logText += (typeof p.output === 'string' ? p.output : JSON.stringify(p.output, null, 2)) + '\n';
                                          }
                                          logText += '\n';
                                        });
                                      } catch {
                                        logText = selectedDeviceDetail.phases_json || '';
                                      }
                                      return (
                                        <OutputActions
                                          text={logText}
                                          filename={`log_${selectedDeviceDetail.hostname || selectedDeviceDetail.ip_address || 'device'}`}
                                          theme="light"
                                          zh={isZh}
                                        />
                                      );
                                    })()}
                                  </div>
                                </div>

                                {/* Key Device Information */}
                                {(() => {
                                  const dev = devices.find(d => d.hostname === selectedDeviceDetail.hostname || d.ip_address === selectedDeviceDetail.ip_address);
                                  if (!dev) return null;
                                  return (
                                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-1">
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '平台' : 'Platform'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.platform || '-'}</p>
                                      </div>
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '角色' : 'Role'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.role || '-'}</p>
                                      </div>
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '站点' : 'Site'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.site || '-'}</p>
                                      </div>
                                      <div className="px-2 py-1.5 rounded-lg bg-black/[0.02] border border-black/5">
                                        <p className="text-[9px] font-bold text-black/20 uppercase tracking-tighter">{isZh ? '型号' : 'Model'}</p>
                                        <p className="text-[10px] font-bold text-black/60 truncate">{dev.model || '-'}</p>
                                      </div>
                                    </div>
                                  );
                                })()}
                              </div>
                              
                              {/* Output Stream Content */}
                              <div className="flex-1 overflow-auto p-4 space-y-3">
                                {selectedDeviceDetail.error_message && (
                                  <div className="rounded-xl border border-red-100 bg-red-50/60 p-4 flex items-start gap-3">
                                    <div className="w-8 h-8 rounded-lg bg-red-100 flex items-center justify-center shrink-0">
                                      <AlertCircle size={14} className="text-red-600" />
                                    </div>
                                    <div className="min-w-0">
                                      <p className="text-[10px] font-bold text-red-700 mb-1">{isZh ? '错误信息' : 'Error Message'}</p>
                                      <pre className="text-[11px] font-mono text-red-600 whitespace-pre-wrap break-all">{selectedDeviceDetail.error_message}</pre>
                                    </div>
                                  </div>
                                )}
                                {Object.entries((() => {
                                  try {
                                    return JSON.parse(selectedDeviceDetail.phases_json || '{}') as Record<string, { success?: boolean; commands?: string[]; output?: unknown }>;
                                  } catch { return {}; }
                                })()).map(([phase, data]) => {
                                  const rawOutput = data?.output
                                    ? (typeof data.output === 'string' ? data.output : JSON.stringify(data.output, null, 2))
                                    : '';
                                  const commands = data?.commands || [];
                                  const dev = devices.find(d => d.hostname === selectedDeviceDetail.hostname || d.ip_address === selectedDeviceDetail.ip_address);
                                  const platform = dev?.platform || 'cisco_ios';
                                  const execId = selectedExecutionDetail?.id || activeExecutionId || '';
                                  const devId = dev?.id || selectedDeviceDetail.ip_address || '';
                                  const hostname = selectedDeviceDetail.hostname || 'device';

                                  // Split combined output into per-command blocks
                                  const cmdBlocks = splitOutputByCommand(rawOutput, commands);

                                  return (
                                    <div key={phase} className="rounded-xl border border-black/5 overflow-hidden">
                                      {/* Phase header */}
                                      <div className="flex items-center justify-between px-4 py-2.5 bg-black/[0.02] border-b border-black/5">
                                        <div className="flex items-center gap-2">
                                          <p className="text-[10px] font-bold uppercase tracking-wider text-black/40"># PHASE: {phase.replace(/_/g, ' ')}</p>
                                          {data?.success !== undefined && (
                                            <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${data.success ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}`}>
                                              {data.success ? '✓ Pass' : '✗ Fail'}
                                            </span>
                                          )}
                                        </div>
                                        <div className="flex items-center gap-2">
                                          {cmdBlocks.length > 0 && (
                                            <div className="flex items-center gap-1.5 mr-2">
                                              <button
                                                onClick={() => {
                                                  const next = { ...collapsedBlocks };
                                                  cmdBlocks.forEach((b, bi) => next[`${phase}::${b.command || bi}`] = false);
                                                  setCollapsedBlocks(next);
                                                }}
                                                className="text-[10px] font-bold text-[#0891b2] hover:text-[#0e7490] transition-colors cursor-pointer"
                                              >
                                                {isZh ? '全部展开' : 'Expand All'}
                                              </button>
                                              <div className="w-px h-2.5 bg-black/10" />
                                              <button
                                                onClick={() => {
                                                  const next = { ...collapsedBlocks };
                                                  cmdBlocks.forEach((b, bi) => next[`${phase}::${b.command || bi}`] = true);
                                                  setCollapsedBlocks(next);
                                                }}
                                                className="text-[10px] font-bold text-black/35 hover:text-black/60 transition-colors cursor-pointer"
                                              >
                                                {isZh ? '全部折叠' : 'Collapse All'}
                                              </button>
                                            </div>
                                          )}
                                          {/* Phase-level download of full raw output */}
                                          {rawOutput && (
                                            <div className="flex items-center gap-1.5 border-l border-black/5 pl-2">
                                              <button
                                                onClick={() => copyText(rawOutput, `${phase}-all`)}
                                                className={`flex items-center gap-1 px-2 py-1 rounded-md border text-[10px] font-medium transition-all shadow-sm ${copiedKey === `${phase}-all` ? 'bg-emerald-50 border-emerald-200 text-emerald-600' : 'bg-white border-black/10 text-black/40 hover:text-black/70 hover:border-black/20'}`}
                                                title={isZh ? '复制全部输出' : 'Copy all output'}
                                              >
                                                {copiedKey === `${phase}-all` ? <Check size={10} /> : <Copy size={10} />}
                                                <span>{isZh ? '复制全部' : 'Copy all'}</span>
                                              </button>
                                              <button
                                                onClick={() => downloadText(rawOutput, `${hostname}_${phase}_raw.txt`)}
                                                className="flex items-center gap-1 px-2 py-1 rounded-md border bg-white border-black/10 text-[10px] font-medium text-black/40 hover:text-black/70 hover:border-black/20 transition-all shadow-sm"
                                                title={isZh ? '下载全部输出' : 'Download all output'}
                                              >
                                                <Download size={10} />
                                                <span>{isZh ? '下载' : 'Download'}</span>
                                              </button>
                                            </div>
                                          )}
                                        </div>
                                      </div>

                                      {/* Per-command blocks */}
                                      <div className="divide-y divide-black/[0.04]">
                                        {cmdBlocks.length > 0 ? cmdBlocks.map((block, bi) => {
                                          const blockKey = `${phase}::${block.command || bi}`;
                                          const viewMode = parseViewMode[blockKey] || 'raw';
                                          const parseState = parseResults[blockKey];
                                          const isCopied = copiedKey === `${blockKey}-copy`;
                                          const hasOutput = !!block.output;
                                          const displayCmd = block.command || commands[bi] || '';
                                          const isCollapsed = collapsedBlocks[blockKey] ?? false;

                                          return (
                                            <div key={blockKey} className="bg-white">
                                              {/* Command bar — GitHub-style, always shown when we have a command */}
                                              {displayCmd && (
                                                <div 
                                                  onClick={() => toggleBlockCollapse(blockKey)}
                                                  className="flex items-center justify-between px-4 py-2 bg-[#f6f8fa] border-b border-black/[0.06] cursor-pointer hover:bg-black/[0.03] transition-colors select-none"
                                                >
                                                  <div className="flex items-center gap-2 min-w-0">
                                                    <ChevronRight size={14} className={`text-black/30 shrink-0 transition-transform duration-200 ${isCollapsed ? '' : 'rotate-90'}`} />
                                                    <span className="text-[10px] text-black/30 font-mono select-none">$</span>
                                                    <code className="text-[11px] font-mono text-[#0550ae] font-semibold truncate">{displayCmd}</code>
                                                  </div>
                                                  {hasOutput && (
                                                    <div className="flex items-center gap-1 shrink-0 ml-3" onClick={e => e.stopPropagation()}>
                                                      {isCollapsed && (
                                                        <span className="text-[10px] text-black/30 font-mono italic truncate max-w-[200px] sm:max-w-[300px] mr-2 hidden md:inline">
                                                          {block.output.substring(0, 60).replace(/\n/g, ' ')}...
                                                        </span>
                                                      )}
                                                      {/* Raw / Parsed toggle */}
                                                      <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-black/[0.05] border border-black/[0.06]">
                                                        <button
                                                          onClick={() => setParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }))}
                                                          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-all ${viewMode === 'raw' ? 'bg-white shadow-sm text-[#24292f]' : 'text-black/30 hover:text-black/60'}`}
                                                        >
                                                          <FileText size={9} />
                                                          Raw
                                                        </button>
                                                        <button
                                                          onClick={() => {
                                                            if (!parseState || (!parseState.data && !parseState.loading)) {
                                                              void handleParseCommand(blockKey, platform, displayCmd, block.output, execId, devId);
                                                            } else {
                                                              setParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' }));
                                                            }
                                                          }}
                                                          className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold transition-all ${viewMode === 'parsed' ? 'bg-white shadow-sm text-cyan-700' : 'text-black/30 hover:text-black/60'}`}
                                                        >
                                                          {parseState?.loading ? <Loader2 size={9} className="animate-spin" /> : <Table2 size={9} />}
                                                          Parsed
                                                        </button>
                                                      </div>
                                                      {/* Copy */}
                                                      <button
                                                        onClick={() => {
                                                          const txt = viewMode === 'parsed' && parseState?.data
                                                            ? JSON.stringify(parseState.data.records, null, 2)
                                                            : block.output;
                                                          copyText(txt, `${blockKey}-copy`);
                                                        }}
                                                        className={`p-1 rounded border transition-all ${isCopied ? 'bg-emerald-50 border-emerald-200 text-emerald-600' : 'bg-white border-black/10 text-black/35 hover:text-[#0550ae] hover:border-[#0550ae]/30'}`}
                                                        title={isZh ? '复制' : 'Copy'}
                                                      >
                                                        {isCopied ? <Check size={11} /> : <Copy size={11} />}
                                                      </button>
                                                      {/* Download raw .txt */}
                                                      <button
                                                        onClick={() => {
                                                          const safeCmd = displayCmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                          downloadText(block.output, `${hostname}_${safeCmd}_raw.txt`);
                                                        }}
                                                        className="flex items-center gap-1 p-1 rounded border bg-white border-black/10 text-black/35 hover:text-cyan-600 hover:border-cyan-300 transition-all"
                                                        title={isZh ? '下载原始文本' : 'Download raw .txt'}
                                                      >
                                                        <Download size={11} />
                                                        <span className="text-[9px] font-mono">txt</span>
                                                      </button>
                                                      {/* Download parsed .xlsx — only when parsed data available */}
                                                      {parseState?.data && (
                                                        <button
                                                          onClick={() => {
                                                            const safeCmd = displayCmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                            downloadExcel(parseState.data.records, parseState.data.fields, `${hostname}_${safeCmd}_parsed`);
                                                          }}
                                                          className="flex items-center gap-1 p-1 rounded border bg-emerald-50 border-emerald-200 text-emerald-700 hover:bg-emerald-100 transition-all"
                                                          title={isZh ? '下载解析结果 (Excel)' : 'Download parsed as Excel'}
                                                        >
                                                          <FileSpreadsheet size={11} />
                                                          <span className="text-[9px] font-mono">xlsx</span>
                                                        </button>
                                                      )}
                                                      {/* Download parsed .json — only when parsed data available */}
                                                      {parseState?.data && (
                                                        <button
                                                          onClick={() => {
                                                            const safeCmd = displayCmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                            downloadJSON(parseState.data.records, `${hostname}_${safeCmd}_parsed`);
                                                          }}
                                                          className="flex items-center gap-1 p-1 rounded border bg-indigo-50 border-indigo-200 text-indigo-700 hover:bg-indigo-100 transition-all"
                                                          title={isZh ? '下载解析结果 (JSON)' : 'Download parsed as JSON'}
                                                        >
                                                          <FileJson size={11} />
                                                          <span className="text-[9px] font-mono">json</span>
                                                        </button>
                                                      )}
                                                    </div>
                                                  )}
                                                </div>
                                              )}

                                              {/* Output content */}
                                              {!isCollapsed && hasOutput && (
                                                <div className="px-0">
                                                  {viewMode === 'parsed' ? (
                                                    parseState?.loading ? (
                                                      <div className="flex items-center justify-center py-6 text-black/30 gap-2">
                                                        <Loader2 size={14} className="animate-spin" />
                                                        <span className="text-xs">{isZh ? '正在解析...' : 'Parsing...'}</span>
                                                      </div>
                                                    ) : parseState?.error ? (
                                                      <div className="mx-4 my-3 rounded-lg bg-amber-50 border border-amber-100 p-3 flex items-start gap-2">
                                                        <AlertCircle size={12} className="text-amber-500 shrink-0 mt-0.5" />
                                                        <div>
                                                          <p className="text-[11px] text-amber-700 font-medium">{parseState.error}</p>
                                                          <p className="text-[10px] text-amber-500 mt-0.5">{isZh ? '已切换回原始视图' : 'Showing raw output'}</p>
                                                        </div>
                                                      </div>
                                                    ) : parseState?.data ? (
                                                      <div className="p-3 space-y-2">
                                                        <div className="flex items-center justify-between px-1">
                                                          <div className="flex items-center gap-2 text-[10px] text-emerald-600 font-semibold">
                                                            <CheckCircle2 size={11} />
                                                            {isZh ? `${parseState.data.count} 条记录` : `${parseState.data.count} record(s)`}
                                                            <span className="text-black/25 font-normal">{parseState.data.fields.join(' · ')}</span>
                                                          </div>
                                                          {/* Excel download button inside table header */}
                                                          <div className="flex items-center gap-1.5">
                                                            <button
                                                              onClick={() => {
                                                                const safeCmd = displayCmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                                downloadExcel(parseState.data.records, parseState.data.fields, `${hostname}_${safeCmd}_parsed`);
                                                              }}
                                                              className="flex items-center gap-1 px-2 py-0.5 rounded border bg-emerald-50 border-emerald-200 text-emerald-700 text-[10px] font-semibold hover:bg-emerald-100 transition-all"
                                                              title={isZh ? '导出 Excel (.xlsx)' : 'Export as Excel (.xlsx)'}
                                                            >
                                                              <FileSpreadsheet size={10} />
                                                              {isZh ? '导出 Excel' : 'Export Excel'}
                                                            </button>
                                                            <button
                                                              onClick={() => {
                                                                const safeCmd = displayCmd.replace(/[^a-z0-9_]/gi, '_').slice(0, 40);
                                                                downloadJSON(parseState.data.records, `${hostname}_${safeCmd}_parsed`);
                                                              }}
                                                              className="flex items-center gap-1 px-2 py-0.5 rounded border bg-indigo-50 border-indigo-200 text-indigo-700 text-[10px] font-semibold hover:bg-indigo-100 transition-all"
                                                              title={isZh ? '导出 JSON (.json)' : 'Export as JSON (.json)'}
                                                            >
                                                              <FileJson size={10} />
                                                              {isZh ? '导出 JSON' : 'Export JSON'}
                                                            </button>
                                                          </div>
                                                        </div>
                                                        <div className="overflow-auto rounded-lg border border-black/[0.06]">
                                                          <table className="w-full text-[11px] font-mono">
                                                            <thead className="bg-[#f6f8fa] border-b border-black/[0.06]">
                                                              <tr>
                                                                {parseState.data.fields.map((f: string) => (
                                                                  <th key={f} className="px-3 py-1.5 text-left text-[10px] font-bold text-black/40 uppercase tracking-wider whitespace-nowrap">{f}</th>
                                                                ))}
                                                              </tr>
                                                            </thead>
                                                            <tbody className="divide-y divide-black/[0.04]">
                                                              {parseState.data.records.map((rec: Record<string, string>, ri: number) => (
                                                                <tr key={ri} className="hover:bg-[#f6f8fa]/60 transition-colors">
                                                                  {parseState.data.fields.map((f: string) => (
                                                                    <td key={f} className="px-3 py-1.5 text-black/65 whitespace-nowrap max-w-[180px] truncate" title={rec[f]}>{rec[f] || '—'}</td>
                                                                  ))}
                                                                </tr>
                                                              ))}
                                                            </tbody>
                                                          </table>
                                                        </div>
                                                      </div>
                                                    ) : null
                                                  ) : (
                                                    /* Raw view — dark terminal style */
                                                    <pre className="text-[11px] font-mono text-[#e6edf3] bg-[#161b22] px-5 py-4 max-h-[480px] overflow-auto whitespace-pre-wrap leading-5 border-0">
                                                      {block.output}
                                                    </pre>
                                                  )}
                                                </div>
                                              )}
                                            </div>
                                          );
                                        }) : (
                                          /* No output at all */
                                          !rawOutput && (
                                            <div className="px-4 py-3">
                                              <p className="text-[10px] text-black/20 italic">{isZh ? '无输出' : 'No output'}</p>
                                            </div>
                                          )
                                        )}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          ) : (
                            <div className="h-full flex flex-col items-center justify-center text-black/20 p-8">
                              <div className="w-16 h-16 rounded-2xl bg-black/[0.03] flex items-center justify-center mb-4">
                                <History size={28} strokeWidth={1} className="text-black/15" />
                              </div>
                              <p className="text-sm font-medium text-black/25">{t('selectExecutionHint')}</p>
                              <p className="text-[11px] text-black/15 mt-1">{isZh ? '点击左侧列表查看详情' : 'Click an item from the list to view details'}</p>
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })()
                )}
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      </div>
    </div>
  );
};

export default AutomationHistoryTab;