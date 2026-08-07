import React, { useEffect, useState, useMemo } from 'react';
import { Activity, Zap, RefreshCw, Clock, CheckCircle2, AlertCircle } from 'lucide-react';
import { getAIUsageSummary, getAIAuditLogs, AIUsageSummary } from '../../../api/ai';
import Pagination from '../../../components/Pagination';

export const UsageDashboardTab: React.FC = () => {
  const [summary, setSummary] = useState<AIUsageSummary | null>(null);
  const [logs, setLogs] = useState<Array<Record<string, any>>>([]);
  const [loading, setLoading] = useState(true);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [sumData, logData] = await Promise.all([
        getAIUsageSummary(),
        getAIAuditLogs(100),
      ]);
      setSummary(sumData);
      setLogs(logData);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const paginatedLogs = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage;
    return logs.slice(start, start + itemsPerPage);
  }, [logs, currentPage, itemsPerPage]);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Activity className="w-6 h-6 text-indigo-500" />
            Token 使用统计与 AI 审计
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            实时统计 Token 消耗量、请求延迟、请求状态及全量审计日志。
          </p>
        </div>
        <button
          onClick={fetchData}
          className="px-3 py-2 text-sm bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 text-gray-700 dark:text-gray-300 rounded-lg flex items-center gap-1.5 transition"
        >
          <RefreshCw className="w-4 h-4" />
          刷新数据
        </button>
      </div>

      {/* Summary Stat Cards */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between text-gray-400 text-xs font-semibold uppercase">
              <span>总请求次数</span>
              <Zap className="w-4 h-4 text-amber-500" />
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-white mt-2">{summary.total_requests}</p>
          </div>

          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between text-gray-400 text-xs font-semibold uppercase">
              <span>Input Tokens</span>
              <Activity className="w-4 h-4 text-indigo-500" />
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-white mt-2">{summary.total_input_tokens.toLocaleString()}</p>
          </div>

          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between text-gray-400 text-xs font-semibold uppercase">
              <span>Output Tokens</span>
              <Activity className="w-4 h-4 text-emerald-500" />
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-white mt-2">{summary.total_output_tokens.toLocaleString()}</p>
          </div>

          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 shadow-sm">
            <div className="flex items-center justify-between text-gray-400 text-xs font-semibold uppercase">
              <span>平均延迟</span>
              <Clock className="w-4 h-4 text-blue-500" />
            </div>
            <p className="text-2xl font-bold text-gray-900 dark:text-white mt-2">{summary.avg_latency_ms} ms</p>
          </div>
        </div>
      )}

      {/* Audit Logs Table */}
      <div className="space-y-4">
        <h3 className="text-lg font-bold text-gray-900 dark:text-white">近期 AI 请求审计日志</h3>
        {loading ? (
          <div className="p-8 text-center text-gray-400">加载中...</div>
        ) : (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 text-gray-500 dark:text-gray-400 font-semibold">
                  <th className="py-3 px-4">Request ID</th>
                  <th className="py-3 px-4">用户</th>
                  <th className="py-3 px-4">场景</th>
                  <th className="py-3 px-4">Tokens (In/Out)</th>
                  <th className="py-3 px-4">耗时</th>
                  <th className="py-3 px-4">状态</th>
                  <th className="py-3 px-4">时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700 text-gray-700 dark:text-gray-300 font-mono">
                {paginatedLogs.map((l) => (
                  <tr key={l.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                    <td className="py-3 px-4 text-indigo-600 dark:text-indigo-400 font-semibold">{l.request_id}</td>
                    <td className="py-3 px-4">{l.user_id || 'anonymous'}</td>
                    <td className="py-3 px-4 font-sans font-medium">{l.scene}</td>
                    <td className="py-3 px-4">{l.input_tokens} / {l.output_tokens}</td>
                    <td className="py-3 px-4">{l.latency_ms} ms</td>
                    <td className="py-3 px-4 font-sans">
                      {l.status === 'success' ? (
                        <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                          <CheckCircle2 className="w-3.5 h-3.5" /> 成功
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400" title={l.error_message}>
                          <AlertCircle className="w-3.5 h-3.5" /> 失败 ({l.error_code})
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-gray-400">{new Date(l.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Shared Pagination Component Integration */}
            <Pagination
              currentPage={currentPage}
              totalItems={logs.length}
              onPageChange={setCurrentPage}
              itemsPerPage={itemsPerPage}
              onItemsPerPageChange={(size) => {
                setItemsPerPage(size);
                setCurrentPage(1);
              }}
              language="zh"
              alwaysVisible
            />
          </div>
        )}
      </div>
    </div>
  );
};
