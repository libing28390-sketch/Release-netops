import React, { useState, useEffect, useMemo } from 'react';
import { Search, X, Layers, Database, Check, Sparkles, Filter } from 'lucide-react';
import { apiRequest } from '../../api/http';
import { ALL_VENDOR_NAMES, NETWORK_VENDOR_GROUPS } from '../../pages/AssetManagement/constants';

export interface MibNodeItem {
  id: string;
  mib_id: string;
  mib_name: string;
  vendor: string;
  node_name: string;
  oid: string;
  syntax_type: string;
  access_type: string;
  status: string;
  description: string;
  recommended_mode?: string;
  recommended_counter_bits?: number;
}

interface OidPickerModalProps {
  open: boolean;
  onClose: () => void;
  onSelect: (node: MibNodeItem) => void;
  targetMetricName?: string;
  initialVendor?: string;
  language: string;
}

const OidPickerModal: React.FC<OidPickerModalProps> = ({
  open,
  onClose,
  onSelect,
  targetMetricName = '',
  initialVendor = '',
  language,
}) => {
  const zh = language === 'zh';
  const [query, setQuery] = useState('');
  const [vendorFilter, setVendorFilter] = useState(initialVendor || '');
  const [extraVendors, setExtraVendors] = useState<string[]>([]);
  const [nodes, setNodes] = useState<MibNodeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<MibNodeItem | null>(null);

  const fetchNodes = async (searchQuery: string, vendor: string) => {
    if (!searchQuery.trim() && !vendor.trim()) {
      searchQuery = 'cpu';
    }
    setLoading(true);
    try {
      const params = new URLSearchParams({
        query: searchQuery.trim() || 'system',
        limit: '50',
      });
      if (vendor.trim()) {
        params.set('vendor', vendor.trim());
      }
      const res = await apiRequest<{ success: boolean; data: MibNodeItem[] }>(
        `/api/platform-registry/mibs/nodes/search?${params.toString()}`
      );
      setNodes(Array.isArray(res.data) ? res.data : []);
    } catch {
      setNodes([]);
    } finally {
      setLoading(false);
    }
  };

  // Load extra MIB vendors from repository stats
  useEffect(() => {
    if (open) {
      void (async () => {
        try {
          const res = await apiRequest<{ success: boolean; data?: { vendor_counts?: Record<string, number> } }>(
            '/api/platform-registry/mibs/repository-stats'
          );
          if (res.data?.vendor_counts) {
            const known = new Set((ALL_VENDOR_NAMES as readonly string[]).map(v => v.toLowerCase()));
            const extras = Object.keys(res.data.vendor_counts)
              .filter(v => v.trim() && !known.has(v.trim().toLowerCase()) && v.trim().toLowerCase() !== 'standard')
              .sort((a, b) => a.localeCompare(b));
            setExtraVendors(extras);
          }
        } catch {
          // ignore
        }
      })();
    }
  }, [open]);

  // Reset search query and vendor filter when opening
  useEffect(() => {
    if (open) {
      let defaultQuery = '';
      if (targetMetricName === 'cpu') defaultQuery = 'cpu';
      else if (targetMetricName === 'memory') defaultQuery = 'mem';
      else if (targetMetricName === 'temperature') defaultQuery = 'temp';
      else if (targetMetricName === 'fan') defaultQuery = 'fan';
      else if (targetMetricName === 'power' || targetMetricName === 'power_supply') defaultQuery = 'power';
      else if (targetMetricName === 'storage') defaultQuery = 'storage';
      else if (targetMetricName === 'voltage') defaultQuery = 'volt';
      else if (targetMetricName === '__interface') defaultQuery = 'if';

      setQuery(defaultQuery);
      setVendorFilter(initialVendor || '');
      setSelectedNode(null);
      void fetchNodes(defaultQuery, initialVendor || '');
    }
  }, [open, targetMetricName, initialVendor]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    void fetchNodes(query, vendorFilter);
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-[960px] flex-col overflow-hidden rounded-2xl border border-black/10 bg-[var(--card-bg)] shadow-2xl dark:border-white/10"
        onMouseDown={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-black/8 px-5 py-4 dark:border-white/8">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#00bceb]/10 text-[#008aad] dark:text-[#00bceb]">
              <Database size={17} />
            </div>
            <div>
              <div className="text-sm font-semibold text-black/85 dark:text-white/90">
                {zh ? '从 MIB 知识库拾取 OID' : 'Pick OID from MIB Repository'}
              </div>
              <div className="mt-0.5 text-[11px] text-black/45 dark:text-white/45">
                {zh
                  ? `支持搜索 OID 符号名（如 cpu / memory / temp）、点分数字或 MIB 模块${targetMetricName ? ` · 正在配置【${targetMetricName}】` : ''}${initialVendor ? ` · 当前厂商【${initialVendor}】` : ''}`
                  : `Search symbol name, numeric OID prefix or MIB module${targetMetricName ? ` for [${targetMetricName}]` : ''}`}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-black/40 hover:bg-black/5 dark:text-white/45 dark:hover:bg-white/8"
          >
            <X size={17} />
          </button>
        </div>

        {/* Search Toolbar */}
        <form onSubmit={handleSearch} className="flex flex-wrap items-center gap-2 border-b border-black/6 bg-black/[.015] p-3 dark:border-white/6 dark:bg-white/[.015]">
          <div className="relative min-w-[200px] flex-1">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/25" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={zh ? '搜索符号名 / OID (如: cpu, temp, 1.3.6.1.4.1...)' : 'Search symbol or OID (e.g. cpu, temp, 1.3.6.1.4.1...)'}
              className="w-full rounded-lg border border-black/10 bg-transparent py-1.5 pl-8 pr-3 text-xs outline-none focus:border-[#00bceb]/60 dark:border-white/10"
              autoFocus
            />
          </div>

          <div className="flex items-center gap-1.5">
            <Filter size={13} className="text-black/40 dark:text-white/40" />
            <select
              value={vendorFilter}
              onChange={e => {
                const nextVendor = e.target.value;
                setVendorFilter(nextVendor);
                void fetchNodes(query, nextVendor);
              }}
              className="max-w-[200px] rounded-lg border border-black/10 bg-transparent px-2.5 py-1.5 text-xs outline-none focus:border-[#00bceb]/60 dark:border-white/10"
            >
              <option value="">{zh ? '全部厂商' : 'All Vendors'}</option>
              <option value="Standard">{zh ? '标准 MIB (RFC)' : 'Standard (RFC)'}</option>
              {NETWORK_VENDOR_GROUPS.map(group => (
                <optgroup key={group.key} label={zh ? group.labelZh : group.labelEn}>
                  {group.vendors.map(v => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </optgroup>
              ))}
              {extraVendors.length > 0 && (
                <optgroup label={zh ? 'MIB 库其他厂商' : 'Other MIB Vendors'}>
                  {extraVendors.map(v => (
                    <option key={v} value={v}>
                      {v}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-1 rounded-lg bg-[#00a9ce] px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-[#008fb1] disabled:opacity-50"
          >
            <Search size={12} />
            {zh ? '搜索' : 'Search'}
          </button>
        </form>

        {/* Content: List & Details */}
        <div className="grid min-h-[380px] flex-1 grid-cols-1 overflow-hidden lg:grid-cols-12">
          {/* Node List */}
          <div className="min-h-0 overflow-y-auto border-b border-black/6 p-2 dark:border-white/6 lg:col-span-7 lg:border-b-0 lg:border-r">
            {loading ? (
              <div className="py-16 text-center text-xs text-black/40 dark:text-white/40">
                {zh ? '正在检索 MIB 库…' : 'Searching MIB repository…'}
              </div>
            ) : nodes.length === 0 ? (
              <div className="py-16 text-center text-xs text-black/40 dark:text-white/40">
                {zh ? '未找到匹配的 OID 符号节点，请尝试其他关键字或在 MIB 库中导入相应 MIB 文件。' : 'No matching OID symbols found.'}
              </div>
            ) : (
              <div className="space-y-1">
                {nodes.map(node => {
                  const isSelected = selectedNode?.id === node.id;
                  return (
                    <div
                      key={node.id}
                      onClick={() => setSelectedNode(node)}
                      className={`cursor-pointer rounded-lg border p-2.5 transition-colors ${
                        isSelected
                          ? 'border-[#00bceb] bg-[#00bceb]/10 dark:bg-[#00bceb]/15'
                          : 'border-black/5 hover:border-black/15 hover:bg-black/[.02] dark:border-white/5 dark:hover:border-white/15 dark:hover:bg-white/[.03]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate font-mono text-xs font-semibold text-black/80 dark:text-white/90">
                          {node.node_name}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <span className="rounded bg-black/[.04] px-1.5 py-0.5 text-[9px] text-black/60 dark:bg-white/[.06] dark:text-white/60">
                            {node.vendor}
                          </span>
                          <span className="rounded bg-[#00bceb]/10 px-1.5 py-0.5 text-[9px] text-[#008aad] dark:text-[#00bceb]">
                            {node.mib_name}
                          </span>
                        </div>
                      </div>
                      <div className="mt-1 truncate font-mono text-[10px] text-black/50 dark:text-white/50">
                        {node.oid}
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[10px] text-black/40 dark:text-white/40">
                        <span>{node.syntax_type || 'Unknown Type'}</span>
                        {node.recommended_mode && (
                          <span className="inline-flex items-center gap-0.5 text-[9px] text-emerald-600 dark:text-emerald-400">
                            <Sparkles size={9} />
                            {node.recommended_mode}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Node Preview Panel */}
          <div className="flex flex-col overflow-y-auto bg-black/[.01] p-4 dark:bg-white/[.01] lg:col-span-5">
            {selectedNode ? (
              <div className="flex flex-1 flex-col justify-between">
                <div className="space-y-3">
                  <div>
                    <div className="text-[10px] font-medium uppercase tracking-wider text-black/40 dark:text-white/40">
                      {zh ? '符号节点名称' : 'Symbol Node'}
                    </div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-black/85 dark:text-white/90">
                      {selectedNode.node_name}
                    </div>
                  </div>

                  <div>
                    <div className="text-[10px] font-medium uppercase tracking-wider text-black/40 dark:text-white/40">
                      {zh ? '点分十进制 OID' : 'Dotted Decimal OID'}
                    </div>
                    <div className="mt-0.5 select-all rounded bg-black/[.03] p-1.5 font-mono text-xs font-medium text-[#008aad] dark:bg-white/[.05] dark:text-[#00bceb]">
                      {selectedNode.oid}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span className="text-[10px] text-black/45 dark:text-white/45">{zh ? '数据类型：' : 'Syntax: '}</span>
                      <div className="font-mono text-[11px] font-medium text-black/75 dark:text-white/80">
                        {selectedNode.syntax_type || '-'}
                      </div>
                    </div>
                    <div>
                      <span className="text-[10px] text-black/45 dark:text-white/45">{zh ? '所属 MIB：' : 'MIB: '}</span>
                      <div className="truncate font-mono text-[11px] font-medium text-black/75 dark:text-white/80">
                        {selectedNode.mib_name}
                      </div>
                    </div>
                  </div>

                  {selectedNode.recommended_mode && (
                    <div className="rounded-lg border border-[#00bceb]/25 bg-[#00bceb]/[0.05] p-2 text-[11px] text-[#008aad] dark:text-[#00bceb]">
                      <div className="font-medium">{zh ? '✨ 智能推导模式' : '✨ Recommended Mode'}</div>
                      <div className="mt-0.5 text-[10px] opacity-80">
                        {selectedNode.recommended_mode}
                        {selectedNode.recommended_counter_bits ? ` (${selectedNode.recommended_counter_bits}-bit)` : ''}
                      </div>
                    </div>
                  )}

                  {selectedNode.description && (
                    <div>
                      <div className="text-[10px] font-medium uppercase tracking-wider text-black/40 dark:text-white/40">
                        {zh ? '字段说明 (Description)' : 'Description'}
                      </div>
                      <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-black/8 bg-black/[.02] p-2 text-[10px] leading-relaxed text-black/65 dark:border-white/8 dark:bg-white/[.02] dark:text-white/65">
                        {selectedNode.description}
                      </div>
                    </div>
                  )}
                </div>

                <div className="mt-4 pt-3 border-t border-black/8 dark:border-white/8">
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(selectedNode);
                      onClose();
                    }}
                    className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#00a9ce] py-2 text-xs font-medium text-white shadow-sm hover:bg-[#008fb1]"
                  >
                    <Check size={14} />
                    {zh ? '选用此 OID 并填入表单' : 'Use this OID in form'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-1 flex-col items-center justify-center p-6 text-center text-xs text-black/40 dark:text-white/40">
                <Layers size={28} className="mb-2 opacity-40" />
                {zh ? '在左侧列表选中一个 OID 符号节点查看详细定义与推导建议' : 'Select an OID symbol from the list to preview details'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default OidPickerModal;
