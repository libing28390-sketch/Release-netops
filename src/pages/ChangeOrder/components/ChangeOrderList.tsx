import React, { useMemo } from 'react';
import {
  ClipboardList, Search, X, Filter, RefreshCw, SlidersHorizontal,
  BookmarkCheck, Bookmark, Star, Eye, Pencil, Trash2,
  Clock, Zap, CheckCircle2, AlertTriangle, ChevronDown
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import Pagination from '../../../components/Pagination';
import type { ChangeOrder, Summary } from '../types';
import type { User as UserOption, SessionUser } from '../../../types';
import { STATUS_META, PRIORITY_META, ORDER_TYPE_META } from '../constants';
import { fmtTime, typeLabel, priorityLabel, statusLabel } from '../helpers';
import { ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';

interface Props {
  language: string;
  orders: ChangeOrder[];
  total: number;
  loading: boolean;
  page: number;
  pageSize: number;
  setPage: (p: number) => void;
  setPageSize: (sz: number) => void;
  search: string;
  setSearch: (s: string) => void;
  statusFilter: string;
  setStatusFilter: (s: string) => void;
  priorityFilter: string;
  setPriorityFilter: (p: string) => void;
  bookmarkFilter: boolean;
  setBookmarkFilter: (b: boolean) => void;
  showAdvancedSearch: boolean;
  setShowAdvancedSearch: React.Dispatch<React.SetStateAction<boolean>>;
  requesterFilter: string;
  setRequesterFilter: (r: string) => void;
  assigneeFilter: string;
  setAssigneeFilter: (a: string) => void;
  orderTypeFilter: string;
  setOrderTypeFilter: (ot: string) => void;
  createdFrom: string;
  setCreatedFrom: (d: string) => void;
  createdTo: string;
  setCreatedTo: (d: string) => void;
  completedFrom: string;
  setCompletedFrom: (d: string) => void;
  completedTo: string;
  setCompletedTo: (d: string) => void;
  scheduledFrom: string;
  setScheduledFrom: (d: string) => void;
  scheduledTo: string;
  setScheduledTo: (d: string) => void;
  viewTab: string;
  myTodoSubTab: string;
  setMyTodoSubTab: (tab: 'review' | 'implement' | 'modify') => void;
  users: UserOption[];
  currentUser: SessionUser;
  bookmarkedIds: Set<string>;
  advancedFilterCount: number;
  fetchOrders: () => void;
  fetchSummary: () => void;
  fetchBookmarks: () => void;
  openDetail: (order: ChangeOrder) => void;
  openEdit: (order: ChangeOrder) => void;
  handleDelete: (id: string) => void;
  summary: Summary | null;
  FEATURE_TODO_SUBTABS: boolean;
  DEFAULT_PAGE_SIZE: number;
}

export const ChangeOrderList: React.FC<Props> = ({
  language,
  orders,
  total,
  loading,
  page,
  pageSize,
  setPage,
  setPageSize,
  search,
  setSearch,
  statusFilter,
  setStatusFilter,
  priorityFilter,
  setPriorityFilter,
  bookmarkFilter,
  setBookmarkFilter,
  showAdvancedSearch,
  setShowAdvancedSearch,
  requesterFilter,
  setRequesterFilter,
  assigneeFilter,
  setAssigneeFilter,
  orderTypeFilter,
  setOrderTypeFilter,
  createdFrom,
  setCreatedFrom,
  createdTo,
  setCreatedTo,
  completedFrom,
  setCompletedFrom,
  completedTo,
  setCompletedTo,
  scheduledFrom,
  setScheduledFrom,
  scheduledTo,
  setScheduledTo,
  viewTab,
  myTodoSubTab,
  setMyTodoSubTab,
  users,
  currentUser,
  bookmarkedIds,
  advancedFilterCount,
  fetchOrders,
  fetchSummary,
  fetchBookmarks,
  openDetail,
  openEdit,
  handleDelete,
  summary,
  FEATURE_TODO_SUBTABS,
}) => {
  const zh = language === 'zh';

  const summaryCards = useMemo(() => {
    if (!summary) return [];
    const s = summary.by_status;
    return [
      { key: 'total',     value: summary.total,                             label: zh ? '全部工单' : 'Total',       icon: ClipboardList, color: 'text-slate-700',   iconBg: 'bg-slate-100' },
      { key: 'reviewing', value: (s.initial_review || 0) + (s.final_review || 0) + (s.pending || 0), label: zh ? '审核中' : 'Reviewing', icon: Clock, color: 'text-amber-600', iconBg: 'bg-amber-50' },
      { key: 'implementing',   value: (s.implementing || 0) + (s.executing || 0),                 label: zh ? '实施中' : 'Implementing',   icon: Zap,          color: 'text-cyan-600',    iconBg: 'bg-cyan-50' },
      { key: 'completed',      value: (s.completed || 0),                                          label: zh ? '变更完成' : 'Completed',    icon: CheckCircle2, color: 'text-emerald-600', iconBg: 'bg-emerald-50' },
      { key: 'rollback',       value: (s.rollback_in_progress || 0) + (s.rolled_back || 0),       label: zh ? '回溯' : 'Rollback',         icon: AlertTriangle,color: 'text-violet-600',  iconBg: 'bg-violet-50' },
    ];
  }, [summary, zh]);

  return (
    <>
      {/* ── Summary Cards (only on "all" view) ── */}
      {viewTab === 'all' && summaryCards.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {summaryCards.map((card, idx) => (
            <motion.div
              key={card.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.05 }}
              className="bg-white rounded-2xl border border-black/5 p-4 shadow-sm hover:shadow-md transition-shadow cursor-default"
            >
              <div className="flex items-center justify-between">
                <div className={`p-2 rounded-xl ${card.iconBg}`}>
                  <card.icon size={16} className={card.color} />
                </div>
                <span className={`text-2xl font-bold tabular-nums ${card.color}`}>{card.value}</span>
              </div>
              <p className="mt-2 text-xs text-black/45 font-medium">{card.label}</p>
            </motion.div>
          ))}
        </div>
      )}

      {/* ── Filters bar ── */}
      <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
        <div className="flex flex-wrap gap-3 items-center p-4">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-black/30" />
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              placeholder={zh ? '搜索工单号 / 标题...' : 'Search order # / title...'}
              className="w-full pl-9 pr-8 py-2 text-sm bg-black/[0.02] border border-black/8 rounded-xl outline-none focus:border-[#00bceb]/40 focus:ring-2 focus:ring-[#00bceb]/10 transition-all"
            />
            {search && (
              <button title={zh ? '清空搜索' : 'Clear search'} onClick={() => { setSearch(''); setPage(1); }} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60">
                <X size={13} />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1.5 text-black/40">
            <Filter size={13} />
          </div>
          <select
            title={zh ? '按状态筛选' : 'Filter by status'}
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            className="bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
          >
            <option value="">{zh ? '全部状态' : 'All Status'}</option>
            {Object.entries(STATUS_META).map(([k, v]) => (
              <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
            ))}
          </select>
          <select
            title={zh ? '按优先级筛选' : 'Filter by priority'}
            value={priorityFilter}
            onChange={e => { setPriorityFilter(e.target.value); setPage(1); }}
            className="bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
          >
            <option value="">{zh ? '全部优先级' : 'All Priority'}</option>
            {Object.entries(PRIORITY_META).map(([k, v]) => (
              <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
            ))}
          </select>
          <button
            onClick={() => setShowAdvancedSearch(v => !v)}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
              showAdvancedSearch || advancedFilterCount > 0
                ? 'bg-[#00bceb]/8 text-[#00bceb] border-[#00bceb]/20'
                : 'bg-white text-black/50 border-black/10 hover:border-[#00bceb]/30 hover:text-[#00bceb]'
            }`}
          >
            <SlidersHorizontal size={12} />
            {zh ? '高级筛选' : 'Advanced'}
            {advancedFilterCount > 0 && (
              <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-[#00bceb] text-white leading-none">{advancedFilterCount}</span>
            )}
            <ChevronDown size={11} className={`transition-transform ${showAdvancedSearch ? 'rotate-180' : ''}`} />
          </button>
          {/* Bookmark quick-filter */}
          <button
            onClick={() => { setBookmarkFilter(!bookmarkFilter); setPage(1); }}
            title={zh ? '只看收藏' : 'Show bookmarked'}
            className={`p-2 rounded-xl border transition-all ${
              bookmarkFilter
                ? 'bg-amber-50 text-amber-500 border-amber-200'
                : 'bg-white text-black/35 border-black/10 hover:text-amber-500 hover:border-amber-200'
            }`}
          >
            {bookmarkFilter ? <BookmarkCheck size={14} /> : <Bookmark size={14} />}
          </button>
          {/* Refresh */}
          <button
            onClick={() => { fetchOrders(); fetchSummary(); fetchBookmarks(); }}
            className="p-2 rounded-xl border border-black/10 bg-white text-black/40 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all"
            title={zh ? '刷新' : 'Refresh'}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        {/* ── Advanced search panel ── */}
        <AnimatePresence>
          {showAdvancedSearch && (
            <motion.div
              key="advanced-search-panel"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="px-4 pb-4 pt-3 border-t border-black/5 space-y-3">
                {/* Row 1: Creator / Assignee / Order Type */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '创建人' : 'Creator'}</label>
                    <select
                      value={requesterFilter}
                      onChange={e => { setRequesterFilter(e.target.value); setPage(1); }}
                      title={zh ? '按创建人筛选' : 'Filter by creator'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    >
                      <option value="">{zh ? '全部创建人' : 'All Creators'}</option>
                      {users.map(u => (
                        <option key={u.id} value={u.username}>{u.username}{u.group_name ? ` · ${u.group_name}` : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '处理人' : 'Assignee'}</label>
                    <select
                      value={assigneeFilter}
                      onChange={e => { setAssigneeFilter(e.target.value); setPage(1); }}
                      title={zh ? '按处理人筛选' : 'Filter by assignee'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    >
                      <option value="">{zh ? '全部处理人' : 'All Assignees'}</option>
                      {users.filter(u => u.role !== 'Viewer').map(u => (
                        <option key={u.id} value={u.username}>{u.username}{u.group_name ? ` · ${u.group_name}` : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '工单类型' : 'Order Type'}</label>
                    <select
                      value={orderTypeFilter}
                      onChange={e => { setOrderTypeFilter(e.target.value); setPage(1); }}
                      title={zh ? '按类型筛选' : 'Filter by type'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    >
                      <option value="">{zh ? '全部类型' : 'All Types'}</option>
                      {Object.entries(ORDER_TYPE_META).map(([k, v]) => (
                        <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
                      ))}
                    </select>
                  </div>
                </div>
                {/* Row 2: Date range filters */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '创建时间（从）' : 'Created From'}</label>
                    <input
                      type="datetime-local"
                      value={createdFrom}
                      onChange={e => { setCreatedFrom(e.target.value); setPage(1); }}
                      title={zh ? '创建时间（从）' : 'Created From'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '创建时间（至）' : 'Created To'}</label>
                    <input
                      type="datetime-local"
                      value={createdTo}
                      onChange={e => { setCreatedTo(e.target.value); setPage(1); }}
                      title={zh ? '创建时间（至）' : 'Created To'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '完成时间（从）' : 'Completed From'}</label>
                    <input
                      type="datetime-local"
                      value={completedFrom}
                      onChange={e => { setCompletedFrom(e.target.value); setPage(1); }}
                      title={zh ? '完成时间（从）' : 'Completed From'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '完成时间（至）' : 'Completed To'}</label>
                    <input
                      type="datetime-local"
                      value={completedTo}
                      onChange={e => { setCompletedTo(e.target.value); setPage(1); }}
                      title={zh ? '完成时间（至）' : 'Completed To'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                </div>
                {/* Row 3: Scheduled range + Quick presets + Clear */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '计划开始（从）' : 'Scheduled From'}</label>
                    <input
                      type="datetime-local"
                      value={scheduledFrom}
                      onChange={e => { setScheduledFrom(e.target.value); setPage(1); }}
                      title={zh ? '计划开始（从）' : 'Scheduled From'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '计划结束（至）' : 'Scheduled To'}</label>
                    <input
                      type="datetime-local"
                      value={scheduledTo}
                      onChange={e => { setScheduledTo(e.target.value); setPage(1); }}
                      title={zh ? '计划结束（至）' : 'Scheduled To'}
                      className="w-full bg-white border border-black/10 rounded-xl px-3 py-2 text-xs outline-none focus:border-[#00bceb]/40"
                    />
                  </div>
                  {/* Quick date presets */}
                  <div>
                    <label className="block text-[11px] font-semibold text-black/40 mb-1">{zh ? '快捷选择' : 'Quick Range'}</label>
                    <div className="flex gap-1.5">
                      {([
                        { label: zh ? '今天' : 'Today', days: 0 },
                        { label: zh ? '近7天' : '7d', days: 7 },
                        { label: zh ? '近30天' : '30d', days: 30 },
                        { label: zh ? '近90天' : '90d', days: 90 },
                      ] as const).map(preset => (
                        <button
                          key={preset.days}
                          onClick={() => {
                            const now = new Date();
                            const to = now.toISOString().slice(0, 16);
                            const from = preset.days === 0
                              ? new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString().slice(0, 16)
                              : new Date(now.getTime() - preset.days * 86400000).toISOString().slice(0, 16);
                            setCreatedFrom(from);
                            setCreatedTo(to);
                            setPage(1);
                          }}
                          className="px-2.5 py-1.5 rounded-lg text-[11px] font-medium border border-black/8 bg-white text-black/50 hover:text-[#00bceb] hover:border-[#00bceb]/30 transition-all"
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {/* Clear all advanced filters */}
                  {advancedFilterCount > 0 && (
                    <button
                      onClick={() => {
                        setRequesterFilter(''); setAssigneeFilter(''); setBookmarkFilter(false);
                        setOrderTypeFilter('');
                        setCreatedFrom(''); setCreatedTo('');
                        setCompletedFrom(''); setCompletedTo('');
                        setScheduledFrom(''); setScheduledTo('');
                        setPage(1);
                      }}
                      className="px-3 py-2 rounded-xl text-xs font-medium text-rose-500 bg-rose-50 border border-rose-200 hover:bg-rose-100 transition-all"
                    >
                      {zh ? '清空高级筛选' : 'Clear advanced'}
                    </button>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Table ── */}
      <div className="min-w-0">
        <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          {/* ── My-Todo Sub-tabs (待我审核 / 待我实施 / 待我修改) ── */}
          {FEATURE_TODO_SUBTABS && viewTab === 'my_todo' && (
            <div className="flex items-center gap-1 px-4 pt-3 pb-0 border-b border-black/5">
              {([
                { key: 'review',     zh: '待我审核', en: 'Pending Review' },
                { key: 'implement',  zh: '待我实施', en: 'Pending Implementation' },
                { key: 'modify',     zh: '待我修改', en: 'Pending Modification' },
              ] as const).map(tab => (
                <button
                  key={tab.key}
                  onClick={() => { setMyTodoSubTab(tab.key); setPage(1); }}
                  className={`px-4 py-2 text-sm font-medium rounded-t-xl border-b-2 transition-all -mb-px ${
                    myTodoSubTab === tab.key
                      ? 'border-[#00bceb] text-[#00bceb] bg-[#00bceb]/[0.04]'
                      : 'border-transparent text-black/45 hover:text-black/70 hover:border-black/20'
                  }`}
                >
                  {zh ? tab.zh : tab.en}
                </button>
              ))}
            </div>
          )}
          {loading && orders.length === 0 ? (
            <div className="flex items-center justify-center py-24 text-black/30">
              <RefreshCw size={18} className="animate-spin mr-2" /> {zh ? '加载中...' : 'Loading...'}
            </div>
          ) : orders.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-24 text-black/30">
              <ClipboardList size={40} className="mb-3 opacity-30" />
              <p className="text-sm">{zh ? '暂无变更工单' : 'No change orders'}</p>
            </div>
          ) : (
            <div className="overflow-x-auto max-h-[calc(100vh-380px)] overflow-y-auto custom-scrollbar">
              <table className="nx-data-table text-sm">
                <thead className="sticky top-0 z-10 bg-[#f8fafc] border-b border-black/5">
                  <tr className="text-black/50 text-xs">
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '工单号' : 'Order #'}</th>
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '标题' : 'Title'}</th>
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '类型' : 'Type'}</th>
                    <th className="text-center px-4 py-3 font-semibold">{zh ? '优先级' : 'Priority'}</th>
                    <th className="text-center px-4 py-3 font-semibold">{zh ? '状态' : 'Status'}</th>
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '申请人' : 'Requester'}</th>
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '创建时间' : 'Created'}</th>
                    <th className="text-center px-4 py-3 font-semibold">{zh ? '操作' : 'Actions'}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/[0.04]">
                  {orders.map((order) => {
                    const sm = STATUS_META[order.status] || STATUS_META.draft;
                    const pm = PRIORITY_META[order.priority] || PRIORITY_META.medium;
                    const PriorityIcon = pm.icon;
                    return (
                      <tr
                        key={order.id}
                        onClick={() => openDetail(order)}
                        className="cursor-pointer transition-colors hover:bg-black/[0.015]"
                      >
                        <td className="px-4 py-3">
                          <span className="font-mono text-xs font-bold tracking-wide text-[#0e7490] inline-flex items-center gap-1">
                            {bookmarkedIds.has(order.id) && <Star size={10} className="text-amber-400 fill-amber-400 flex-shrink-0" />}
                            {order.order_number}
                          </span>
                        </td>
                        <td className="px-4 py-3 max-w-[200px]">
                          <span className="font-medium text-black/80 truncate block">{order.title}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-xs text-black/50">{typeLabel(order.order_type, language)}</span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs font-medium ${pm.bg} ${pm.color}`}>
                            <PriorityIcon size={12} className="inline-block" />
                            {priorityLabel(order.priority, language)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ring-1 ${sm.bg} ${sm.ring}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${sm.dot}`} />
                            {statusLabel(order.status, language)}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-xs text-black/55">{order.requester_username || '—'}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-xs text-black/40 tabular-nums">{fmtTime(order.created_at)}</span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          <ActionIconGroup label={zh ? '工单操作' : 'Change order actions'}>
                            <ActionIconButton
                              icon={Eye}
                              label={zh ? '查看' : 'View'}
                              onClick={(e) => { e.stopPropagation(); openDetail(order); }}
                            />
                            {['draft', 'rejected'].includes(order.status) && order.requester_username === currentUser.username && (
                              <ActionIconButton
                                icon={Pencil}
                                label={zh ? '编辑' : 'Edit'}
                                onClick={(e) => { e.stopPropagation(); openEdit(order); }}
                              />
                            )}
                            {['draft', 'cancelled'].includes(order.status) && order.requester_username === currentUser.username && (
                              <ActionIconButton
                                icon={Trash2}
                                label={zh ? '删除' : 'Delete'}
                                variant="danger"
                                onClick={(e) => { e.stopPropagation(); handleDelete(order.id); }}
                              />
                            )}
                          </ActionIconGroup>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Fixed Footer for Pagination (only in list view) ── */}
      <div className="flex-shrink-0 bg-white border-t border-black/5 px-6 py-4">
        <Pagination
          currentPage={page}
          itemsPerPage={pageSize}
          totalItems={total}
          onPageChange={setPage}
          onItemsPerPageChange={(v) => { setPageSize(v); setPage(1); }}
          language={language}
          alwaysVisible
        />
      </div>
    </>
  );
};
