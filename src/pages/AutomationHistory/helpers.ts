import * as XLSX from 'xlsx';

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
export function splitOutputByCommand(output: string, commands: string[]): Array<{ command: string; output: string }> {
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
  const cleanPromptRe = /^.*?[#>$]\s*/;
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
}

/** Export parsed records to a real .xlsx file */
export function downloadExcel(records: Record<string, any>[], fields: string[], filename: string): void {
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
}

/** Export parsed records as pretty-printed JSON */
export function downloadJSON(records: Record<string, any>[], filename: string): void {
  if (!records || records.length === 0) return;
  const text = JSON.stringify(records, null, 2);
  const blob = new Blob([text], { type: 'application/json;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename.endsWith('.json') ? filename : `${filename}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Copy text to clipboard with fallback */
export function copyToClipboard(text: string): void {
  navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  });
}

/** Download text content as a file */
export function downloadTextFile(text: string, filename: string): void {
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Helper mapping for execution status badge */
export function getStatusMap(status: string | undefined, isZh: boolean): { label: string; cls: string; dot: string } {
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
}
