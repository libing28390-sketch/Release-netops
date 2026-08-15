import React, { useState } from 'react';
import { Bot, Sparkles, AlertTriangle, ShieldCheck, CheckCircle2, ArrowRight } from 'lucide-react';
import { analyzeCommand, analyzeConfig, analyzeDiff, analyzeAlarm } from '../../../api/ai';

interface AIAnalysisModalProps {
  type: 'command' | 'config' | 'diff' | 'alarm';
  title: string;
  data: any;
  onClose: () => void;
}

export const AIAnalysisModal: React.FC<AIAnalysisModalProps> = ({ type, title, data, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const runAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      if (type === 'command') {
        const res = await analyzeCommand({
          command: data.command,
          output: data.output,
          vendor: data.vendor,
          platform: data.platform,
        });
        setResult(res);
      } else if (type === 'config') {
        const res = await analyzeConfig({
          config_text: data.config_text,
          vendor: data.vendor,
          platform: data.platform,
        });
        setResult(res);
      } else if (type === 'diff') {
        const res = await analyzeDiff({
          diff_text: data.diff_text,
          vendor: data.vendor,
          platform: data.platform,
        });
        setResult(res);
      } else if (type === 'alarm') {
        const res = await analyzeAlarm({
          alarm_title: data.alarm_title,
          severity: data.severity,
          fingerprint: data.fingerprint,
          raw_content: data.raw_content,
        });
        setResult(res);
      }
    } catch (err: any) {
      setError(err.message || 'AI 分析异常');
    } finally {
      setLoading(false);
    }
  };

  React.useEffect(() => {
    runAnalysis();
  }, []);

  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl max-w-2xl w-full p-6 space-y-5 shadow-2xl max-h-[90vh] overflow-y-auto border border-indigo-100 dark:border-indigo-900/40">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-700/60 pb-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 rounded-xl">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-lg text-gray-900 dark:text-white flex items-center gap-2">
                {title}
              </h3>
              <p className="text-xs text-gray-400">Nexora AI 智能推理分析结论 (受控只读模式)</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-white text-lg font-bold"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        {loading ? (
          <div className="py-12 text-center space-y-3">
            <div className="w-8 h-8 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto" />
            <p className="text-sm font-medium text-indigo-600 dark:text-indigo-400 animate-pulse">
              AI 正在构建网络上下文并深入分析中...
            </p>
          </div>
        ) : error ? (
          <div className="p-4 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-300 text-sm">
            <div className="flex items-center gap-2 font-bold mb-1">
              <AlertTriangle className="w-4 h-4" /> 分析失败
            </div>
            <p className="text-xs opacity-90">{error}</p>
          </div>
        ) : result ? (
          <div className="space-y-5 text-sm">
            {/* Request ID Tag */}
            <div className="flex items-center justify-between text-xs text-gray-400 bg-gray-50 dark:bg-gray-900/60 px-3 py-1.5 rounded-lg font-mono">
              <span>Request ID: {result.request_id}</span>
              <span className="text-emerald-600 dark:text-emerald-400 flex items-center gap-1 font-sans">
                <ShieldCheck className="w-3.5 h-3.5" /> 敏感字段已安全脱敏
              </span>
            </div>

            {/* Summary */}
            <div className="bg-indigo-50/50 dark:bg-indigo-950/30 border border-indigo-100 dark:border-indigo-900/30 p-4 rounded-xl space-y-1">
              <h4 className="text-xs font-bold text-indigo-900 dark:text-indigo-300 uppercase tracking-wider">智能摘要总结</h4>
              <p className="text-gray-800 dark:text-gray-200 leading-relaxed">{result.summary || result.incident_summary || result.command_purpose}</p>
            </div>

            {/* Risk Level Badge if Diff */}
            {result.risk_level && (
              <div className="flex items-center gap-3">
                <span className="text-xs font-bold text-gray-500">变更风险评估:</span>
                <span
                  className={`px-3 py-1 text-xs font-bold rounded-full ${
                    result.risk_level === 'CRITICAL' || result.risk_level === 'HIGH'
                      ? 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300'
                      : result.risk_level === 'MEDIUM'
                      ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                      : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                  }`}
                >
                  {result.risk_level}
                </span>
              </div>
            )}

            {/* Evidence & Abnormalities */}
            {(result.abnormalities?.length > 0 || result.evidence?.length > 0) && (
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-gray-700 dark:text-gray-300">异常线索与发现:</h4>
                <ul className="space-y-1 text-xs text-red-600 dark:text-red-400 bg-red-50/40 dark:bg-red-950/20 p-3 rounded-lg border border-red-100 dark:border-red-900/20">
                  {(result.abnormalities || result.evidence).map((item: string, idx: number) => (
                    <li key={idx} className="flex items-start gap-1.5">
                      <span className="font-bold">•</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommendations */}
            {(result.recommendations?.length > 0 || result.recommended_actions?.length > 0) && (
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-gray-700 dark:text-gray-300">建议与后续处理操作:</h4>
                <ul className="space-y-1.5 text-xs text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/40 p-3 rounded-lg">
                  {(result.recommendations || result.recommended_actions).map((rec: string, idx: number) => (
                    <li key={idx} className="flex items-start gap-2">
                      <CheckCircle2 className="w-3.5 h-3.5 text-indigo-500 flex-shrink-0 mt-0.5" />
                      <span>{rec}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null}

        {/* Footer */}
        <div className="flex justify-end pt-4 border-t border-gray-100 dark:border-gray-700/60">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 text-gray-700 dark:text-gray-200 text-sm font-medium rounded-xl transition"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
};
