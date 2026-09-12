import React, { useState, useEffect } from 'react';

interface TextFSMDebuggerProps {
  isOpen: boolean;
  onClose: () => void;
  platform: string;
  command: string;
  sampleOutput: string;
  onSaveSuccess: () => void;
}

export const TextFSMDebugger: React.FC<TextFSMDebuggerProps> = ({
  isOpen,
  onClose,
  platform,
  command,
  sampleOutput,
  onSaveSuccess,
}) => {
  const [templateContent, setTemplateContent] = useState('');
  const [sampleText, setSampleText] = useState(sampleOutput || '');
  const [records, setRecords] = useState<any[]>([]);
  const [fields, setFields] = useState<string[]>([]);
  const [selectedFields, setSelectedFields] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState({ type: '', text: '' });

  const token = localStorage.getItem('netops_token') || '';

  // Reset sample and generate initial template when open
  useEffect(() => {
    if (isOpen) {
      setSampleText(sampleOutput || '');
      setRecords([]);
      setFields([]);
      setSelectedFields([]);
      setStatusMsg({ type: '', text: '' });
      if (sampleOutput) {
        handleAutoGenerate(sampleOutput);
      } else {
        setTemplateContent('');
      }
    }
  }, [isOpen, sampleOutput]);

  const handleAutoGenerate = async (sampleData: string) => {
    setLoading(true);
    try {
      const res = await fetch('/api/textfsm/auto-generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ sample_output: sampleData }),
      });
      const data = await res.json();
      if (data.success && data.data?.content) {
        setTemplateContent(data.data.content);
        const generatedRecords = data.data.records || [];
        setRecords(generatedRecords);
        const generatedFields = data.data.columns || [];
        setFields(generatedFields);
        setSelectedFields(generatedFields);

        const matchRatePct = Math.round((data.data.match_rate || 0) * 100);
        const warningSuffix = data.data.warnings?.length > 0 ? ` (警告: ${data.data.warnings[0]})` : '';
        setStatusMsg({ 
          type: 'success', 
          text: `智能分析模板生成成功！匹配率: ${matchRatePct}% (成功匹配 ${data.data.matched_rows || 0}/${data.data.candidate_rows || 0} 行)${warningSuffix}` 
        });
      } else {
        setStatusMsg({ type: 'error', text: data.detail || data.message || '自动分析失败' });
      }
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.message || '网络连接失败' });
    } finally {
      setLoading(false);
    }
  };

  const handleTestParse = async () => {
    if (!templateContent.trim()) {
      setStatusMsg({ type: 'warning', text: '模板内容不能为空' });
      return;
    }
    if (!sampleText.trim()) {
      setStatusMsg({ type: 'warning', text: '样本输出内容不能为空' });
      return;
    }

    setTesting(true);
    setStatusMsg({ type: '', text: '' });
    try {
      const res = await fetch('/api/textfsm/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          content: templateContent,
          sample_output: sampleText,
        }),
      });
      const data = await res.json();
      if (data.success && data.data) {
        setRecords(data.data.records || []);
        setFields(data.data.fields || []);
        setSelectedFields(data.data.fields || []);
        setStatusMsg({ type: 'success', text: `解析测试成功，共匹配到 ${data.data.count} 条记录！` });
      } else {
        setRecords([]);
        setFields([]);
        setSelectedFields([]);
        setStatusMsg({ type: 'error', text: data.message || '模板匹配失败，请检查规则' });
      }
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.message || '解析测试异常' });
    } finally {
      setTesting(false);
    }
  };

  const handleSaveTemplate = async () => {
    if (!templateContent.trim()) {
      setStatusMsg({ type: 'warning', text: '模板内容不可为空' });
      return;
    }

    setSaving(true);
    try {
      const res = await fetch('/api/textfsm/templates', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          platform: platform,
          command: command,
          content: templateContent,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setStatusMsg({ type: 'success', text: '自定义解析模板保存并热加载成功！正在应用中...' });
        setTimeout(() => {
          onSaveSuccess();
          onClose();
        }, 1200);
      } else {
        setStatusMsg({ type: 'error', text: data.detail || data.message || '保存失败' });
      }
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err.message || '网络连接异常' });
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-end bg-black/60 backdrop-blur-sm transition-all duration-300">
      <div className="flex h-full w-[1000px] flex-col border-l border-white/10 bg-[#071324] text-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div>
            <h3 className="text-lg font-bold text-indigo-400">🧩 自定义命令 TextFSM 解析调试器</h3>
            <p className="text-xs text-white/50 mt-0.5">
              平台: <code className="bg-white/5 px-1.5 py-0.5 rounded text-white/80">{platform}</code> | 
              命令: <code className="bg-white/5 px-1.5 py-0.5 rounded text-white/80 ml-2">{command}</code>
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-white/60 hover:bg-white/5 hover:text-white"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left Panel: Editor & Output */}
          <div className="flex w-1/2 flex-col border-r border-white/10 p-5 overflow-y-auto">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-white/80">TextFSM 规则文件</span>
              <button
                onClick={() => handleAutoGenerate(sampleText)}
                disabled={loading || !sampleText}
                className="text-xs text-indigo-400 hover:text-indigo-300 disabled:opacity-50"
              >
                {loading ? '分析中...' : '💡 重新自动生成规则'}
              </button>
            </div>
            <textarea
              value={templateContent}
              onChange={(e) => setTemplateContent(e.target.value)}
              placeholder="# Enter TextFSM rules here"
              className="h-64 w-full rounded-xl border border-white/10 bg-black/40 p-4 font-mono text-xs text-indigo-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />

            <span className="text-sm font-semibold text-white/80 mt-5 mb-2">命令回显样本 (Raw Output)</span>
            <textarea
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              placeholder="Paste device response here"
              className="flex-1 min-h-[200px] w-full rounded-xl border border-white/10 bg-black/40 p-4 font-mono text-xs text-white/70 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* Right Panel: Parsed Results */}
          <div className="flex w-1/2 flex-col p-5 overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-semibold text-white/80">解析预览结果</span>
              <div className="space-x-2">
                <button
                  onClick={handleTestParse}
                  disabled={testing}
                  className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold hover:bg-indigo-500 disabled:opacity-50"
                >
                  {testing ? '测试中...' : '⚡ 运行测试解析'}
                </button>
              </div>
            </div>

            {/* Status alerts */}
            {statusMsg.text && (
              <div
                className={`mb-4 rounded-xl border p-3.5 text-xs ${
                  statusMsg.type === 'success'
                    ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400'
                    : 'border-rose-500/20 bg-rose-500/5 text-rose-400'
                }`}
              >
                {statusMsg.text}
              </div>
            )}

            {records.length > 0 ? (
              <div className="flex flex-col flex-1 overflow-hidden">
                {/* Column checkboxes */}
                <div className="mb-4 bg-white/5 p-3 rounded-xl border border-white/5">
                  <div className="text-[10px] text-white/40 font-mono mb-2 uppercase tracking-wider">选择输出列</div>
                  <div className="flex flex-wrap gap-2">
                    {fields.map((f) => (
                      <label key={f} className="flex items-center space-x-1.5 bg-black/30 px-2 py-1 rounded text-xs cursor-pointer hover:bg-black/50 select-none">
                        <input
                          type="checkbox"
                          checked={selectedFields.includes(f)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSelectedFields([...selectedFields, f]);
                            } else {
                              setSelectedFields(selectedFields.filter((item) => item !== f));
                            }
                          }}
                          className="rounded border-white/20 text-indigo-600 focus:ring-0 focus:ring-offset-0 bg-transparent"
                        />
                        <span className="font-mono text-white/80">{f}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Table preview */}
                <div className="flex-1 overflow-auto border border-white/10 rounded-xl bg-black/20">
                  <table className="nx-terminal-table min-w-full text-left text-xs text-white/80 border-collapse">
                    <thead>
                      <tr className="bg-white/5 border-b border-white/10">
                        {selectedFields.map((f) => (
                          <th key={f} className="px-3 py-2 font-semibold font-mono text-indigo-400 border-r border-white/10">{f}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((rec, idx) => (
                        <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                          {selectedFields.map((f) => (
                            <td key={f} className="px-3 py-1.5 font-mono border-r border-white/5">{String(rec[f] ?? '')}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center border border-dashed border-white/10 rounded-xl p-8 bg-black/10">
                <span className="text-3xl mb-2">📥</span>
                <span className="text-xs text-white/40">暂无测试解析数据，请先配置规则并点击“运行测试解析”</span>
              </div>
            )}
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-end space-x-3 border-t border-white/10 px-6 py-4 bg-black/20">
          <button
            onClick={onClose}
            className="rounded-xl border border-white/15 px-5 py-2 text-xs font-semibold hover:bg-white/5"
          >
            取消
          </button>
          <button
            onClick={handleSaveTemplate}
            disabled={saving || !templateContent}
            className="rounded-xl bg-indigo-600 px-6 py-2 text-xs font-bold hover:bg-indigo-500 disabled:opacity-50"
          >
            {saving ? '保存中...' : '💾 保存并应用该解析模板'}
          </button>
        </div>
      </div>
    </div>
  );
};
