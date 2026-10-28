import { DataTable } from '../../../components/DataTable';
import React, { useCallback, useMemo } from 'react';
import {
  ClipboardList, RefreshCw, SlidersHorizontal,
  BookmarkCheck, Bookmark, Star, Eye, Pencil, Trash2,
  Clock, Zap, CheckCircle2, AlertTriangle, ChevronDown
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import Pagination from '../../../components/Pagination';
import type { ChangeOrder, Summary } from '../types';
import type { User as UserOption, SessionUser } from '../../../types';
import { STATUS_META, PRIORITY_META, ORDER_TYPE_META } from '../constants';
import { describeCurrentResponsibility, fmtTime, typeLabel, priorityLabel, statusLabel } from '../helpers';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';
import { ListSearchInput, ListToolbar } from '../../../components/ui/TableListControls';
import { TicketEmptyState } from '../../../components/tickets/TicketUI';
import { fetchAllPaginatedItems } from '../../../utils/pagination';
import type { TableExportData } from '../../../components/ui/TableExportMenu';
interface Props {
  language: string;
  orders: ChangeOrder[];
  total: number;
  loading: boolean;
  loadError: 'permission' | 'load' | null;
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
  loadError,
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
  const loadErrorMessage = loadError === 'permission'
    ? (zh ? '无权查看工单，或登录状态已失效。' : 'You are not authorized to view change orders, or your session has expired.')
    : (zh ? '工单列表加载失败。' : 'Could not load change orders.');
  const staleLoadErrorMessage = loadError === 'permission'
    ? (zh ? '无权刷新工单，或登录状态已失效；当前列表可能已过期。' : 'You are not authorized to refresh change orders, or your session has expired. The displayed results may be stale.')
    : (zh ? '工单列表刷新失败，当前显示的内容可能已过期。' : 'Could not refresh change orders. The displayed results may be stale.');
  const exportAllOrders = useCallback(async (): Promise<TableExportData> => {
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (statusFilter) params.set('status', statusFilter);
    if (priorityFilter) params.set('priority', priorityFilter);
    if (requesterFilter) params.set('requester', requesterFilter);
    if (assigneeFilter) params.set('assignee', assigneeFilter);
    if (bookmarkFilter && currentUser.id) params.set('bookmarked', String(currentUser.id));
    if (orderTypeFilter) params.set('order_type', orderTypeFilter);
    if (createdFrom) params.set('created_from', createdFrom);
    if (createdTo) params.set('created_to', createdTo);
    if (completedFrom) params.set('completed_from', completedFrom);
    if (completedTo) params.set('completed_to', completedTo);
    if (scheduledFrom) params.set('scheduled_from', scheduledFrom);
    if (scheduledTo) params.set('scheduled_to', scheduledTo);
    if (viewTab === 'my_todo' && currentUser.username) {
      params.set('my_todo', currentUser.username);
    } else if (viewTab === 'group_todo' && Array.isArray(currentUser.change_groups) && currentUser.change_groups.length > 0) {
      params.set('group_todo', currentUser.change_groups.join(','));
    } else if (viewTab === 'my_focus' && currentUser.id) {
      params.set('bookmarked', String(currentUser.id));
    } else if (viewTab === 'my_participated' && currentUser.username) {
      params.set('my_participated', currentUser.username);
    } else if (viewTab === 'my_drafts' && currentUser.username) {
      params.set('my_drafts', currentUser.username);
    }
    const allOrders = await fetchAllPaginatedItems<ChangeOrder>('/api/change-orders', params, 100);
    return {
      headers: [zh ? '工单号' : 'Order #', zh ? '标题' : 'Title', zh ? '类型' : 'Type', zh ? '优先级' : 'Priority', zh ? '状态' : 'Status', zh ? '申请人' : 'Requester', zh ? '创建时间' : 'Created'],
      rows: allOrders.map((order) => [
        order.order_number,
        order.title,
        typeLabel(order.order_type, language),
        priorityLabel(order.priority, language),
        statusLabel(order.status, language),
        order.requester_username || '—',
        fmtTime(order.created_at),
      ]),
    };
  }, [search, statusFilter, priorityFilter, requesterFilter, assigneeFilter, bookmarkFilter, orderTypeFilter, createdFrom, createdTo, completedFrom, completedTo, scheduledFrom, scheduledTo, viewTab, currentUser.id, currentUser.username, currentUser.change_groups, language, zh]);

  const summaryCards = useMemo(() => {
    if (!summary) return [];
    const s = summary.by_status;
    return [
      { key: 'total',     value: summary.total,                             label: zh ? '全部工单' : 'Total',       icon: ClipboardList, color: 'text-slate-700',   iconBg: 'bg-slate-100' },
      { key: 'reviewing', value: (s.initial_review || 0) + (s.final_review || 0) + (s.pending || 0) + (s.implementation_review || 0) + (s.implementation_result_review || 0), label: zh ? '审核中' : 'Reviewing', icon: Clock, color: 'text-amber-600', iconBg: 'bg-amber-50' },
      { key: 'implementing',   value: (s.implementing || 0) + (s.executing || 0),                 label: zh ? '实施中' : 'Implementing',   icon: Zap,          color: 'text-cyan-600',    iconBg: 'bg-cyan-50' },
      { key: 'completed',      value: (s.completed || 0),                                          label: zh ? '变更完成' : 'Completed',    icon: CheckCircle2, color: 'text-emerald-600', iconBg: 'bg-emerald-50' },
      { key: 'rollback',       value: (s.rollback_in_progress || 0) + (s.rolled_back || 0),       label: zh ? '回退' : 'Rollback',         icon: AlertTriangle,color: 'text-violet-600',  iconBg: 'bg-violet-50' },
    ];
  }, [summary, zh]);

  return (
    <>
      {/* ── Summary Cards (only on "all" view) ── */}
      {viewTab === 'all' && summaryCards.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-[var(--ui-border)] bg-[var(--ui-surface)] px-4 py-3" aria-label={zh ? '工单数量概览' : 'Change order summary'}>
          {summaryCards.map(card => (
            <div key={card.key} className="inline-flex items-center gap-2 text-xs text-[var(--ui-fg-muted)]">
              <span className={`flex h-6 w-6 items-center justify-center rounded-lg ${card.iconBg}`}>
                <card.icon size={13} className={card.color} />
              </span>
              <span>{card.label}</span>
              <strong className={`tabular-nums ${card.color}`}>{card.value}</strong>
            </div>
          ))}
        </div>
      )}

      {/* ── Filters bar ── */}
      <div className="bg-[var(--ui-surface)] rounded-xl border border-[var(--ui-border)] shadow-sm overflow-hidden">
        <ListToolbar className="p-3 sm:p-4">
          <ListSearchInput language={language} aria-label={zh ? '搜索工单号或标题' : 'Search order number or title'} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} onClear={() => { setSearch(''); setPage(1); }} placeholder={zh ? '搜索工单号或标题' : 'Search order number or title'} className="min-w-[220px] flex-1" />
          <select
            aria-label={zh ? '按状态筛选工单' : 'Filter change orders by status'}
            title={zh ? '按状态筛选' : 'Filter by status'}
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            className="bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
          >
            <option value="">{zh ? '全部状态' : 'All Status'}</option>
            {Object.entries(STATUS_META).map(([k, v]) => (
              <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
            ))}
          </select>
          <select
            aria-label={zh ? '按优先级筛选工单' : 'Filter change orders by priority'}
            title={zh ? '按优先级筛选' : 'Filter by priority'}
            value={priorityFilter}
            onChange={e => { setPriorityFilter(e.target.value); setPage(1); }}
            className="bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
          >
            <option value="">{zh ? '全部优先级' : 'All Priority'}</option>
            {Object.entries(PRIORITY_META).map(([k, v]) => (
              <option key={k} value={k}>{v.label[zh ? 'zh' : 'en']}</option>
            ))}
          </select>
          <button
            type="button"
            aria-expanded={showAdvancedSearch}
            onClick={() => setShowAdvancedSearch(v => !v)}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
              showAdvancedSearch || advancedFilterCount > 0
                ? 'bg-[var(--ui-accent-subtle)] text-[var(--ui-accent)] border-[var(--ui-accent)]'
                : 'bg-[var(--ui-surface)] text-[var(--ui-fg-muted)] border-[var(--ui-border)] hover:border-[var(--ui-accent)] hover:text-[var(--ui-accent)]'
            }`}
          >
            <SlidersHorizontal size={12} />
            {zh ? '高级筛选' : 'Advanced'}
            {advancedFilterCount > 0 && (
              <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[11px] font-bold bg-[var(--ui-accent)] text-white leading-none">{advancedFilterCount}</span>
            )}
            <ChevronDown size={11} className={`transition-transform ${showAdvancedSearch ? 'rotate-180' : ''}`} />
          </button>
          <ActionIconButton icon={bookmarkFilter ? BookmarkCheck : Bookmark} label={zh ? (bookmarkFilter ? '显示全部工单' : '只看收藏工单') : (bookmarkFilter ? 'Show all change orders' : 'Show bookmarked change orders')} aria-pressed={bookmarkFilter} variant={bookmarkFilter ? 'accent' : 'default'} onClick={() => { setBookmarkFilter(!bookmarkFilter); setPage(1); }} />
          <ActionIconButton icon={RefreshCw} label={zh ? '刷新工单列表' : 'Refresh change order list'} disabled={loading} iconClassName={loading ? 'animate-spin' : ''} onClick={() => { void fetchOrders(); fetchSummary(); fetchBookmarks(); }} />
          {(search || statusFilter || priorityFilter || advancedFilterCount > 0) && <ActionButton onClick={() => { setSearch(''); setStatusFilter(''); setPriorityFilter(''); setRequesterFilter(''); setAssigneeFilter(''); setBookmarkFilter(false); setOrderTypeFilter(''); setCreatedFrom(''); setCreatedTo(''); setCompletedFrom(''); setCompletedTo(''); setScheduledFrom(''); setScheduledTo(''); setPage(1); }}>{zh ? '重置' : 'Reset'}</ActionButton>}
        </ListToolbar>

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
              <div className="px-4 pb-4 pt-3 border-t border-[var(--ui-border)] space-y-3">
                {/* Row 1: Creator / Assignee / Order Type */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '创建人' : 'Creator'}</label>
                    <select
                      value={requesterFilter}
                      onChange={e => { setRequesterFilter(e.target.value); setPage(1); }}
                      title={zh ? '按创建人筛选' : 'Filter by creator'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    >
                      <option value="">{zh ? '全部创建人' : 'All Creators'}</option>
                      {users.map(u => (
                        <option key={u.id} value={u.username}>{u.username}{u.group_name ? ` · ${u.group_name}` : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '处理人' : 'Assignee'}</label>
                    <select
                      value={assigneeFilter}
                      onChange={e => { setAssigneeFilter(e.target.value); setPage(1); }}
                      title={zh ? '按处理人筛选' : 'Filter by assignee'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    >
                      <option value="">{zh ? '全部处理人' : 'All Assignees'}</option>
                      {users.filter(u => u.role !== 'Viewer').map(u => (
                        <option key={u.id} value={u.username}>{u.username}{u.group_name ? ` · ${u.group_name}` : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '工单类型' : 'Order Type'}</label>
                    <select
                      value={orderTypeFilter}
                      onChange={e => { setOrderTypeFilter(e.target.value); setPage(1); }}
                      title={zh ? '按类型筛选' : 'Filter by type'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
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
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '创建时间（从）' : 'Created From'}</label>
                    <input
                      type="datetime-local"
                      value={createdFrom}
                      onChange={e => { setCreatedFrom(e.target.value); setPage(1); }}
                      title={zh ? '创建时间（从）' : 'Created From'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '创建时间（至）' : 'Created To'}</label>
                    <input
                      type="datetime-local"
                      value={createdTo}
                      onChange={e => { setCreatedTo(e.target.value); setPage(1); }}
                      title={zh ? '创建时间（至）' : 'Created To'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '完成时间（从）' : 'Completed From'}</label>
                    <input
                      type="datetime-local"
                      value={completedFrom}
                      onChange={e => { setCompletedFrom(e.target.value); setPage(1); }}
                      title={zh ? '完成时间（从）' : 'Completed From'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '完成时间（至）' : 'Completed To'}</label>
                    <input
                      type="datetime-local"
                      value={completedTo}
                      onChange={e => { setCompletedTo(e.target.value); setPage(1); }}
                      title={zh ? '完成时间（至）' : 'Completed To'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    />
                  </div>
                </div>
                {/* Row 3: Scheduled range + Quick presets + Clear */}
                <div className="flex flex-wrap gap-3 items-end">
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '计划开始（从）' : 'Scheduled From'}</label>
                    <input
                      type="datetime-local"
                      value={scheduledFrom}
                      onChange={e => { setScheduledFrom(e.target.value); setPage(1); }}
                      title={zh ? '计划开始（从）' : 'Scheduled From'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    />
                  </div>
                  <div className="min-w-[170px]">
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '计划结束（至）' : 'Scheduled To'}</label>
                    <input
                      type="datetime-local"
                      value={scheduledTo}
                      onChange={e => { setScheduledTo(e.target.value); setPage(1); }}
                      title={zh ? '计划结束（至）' : 'Scheduled To'}
                      className="w-full bg-[var(--ui-surface)] border border-[var(--ui-border)] rounded-xl px-3 py-2 text-xs outline-none focus:border-[var(--ui-accent)]"
                    />
                  </div>
                  {/* Quick date presets */}
                  <div>
                    <label className="block text-[11px] font-semibold text-[var(--ui-fg-muted)] mb-1">{zh ? '快捷选择' : 'Quick Range'}</label>
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
                          className="px-2.5 py-1.5 rounded-lg text-[11px] font-medium border border-[var(--ui-border)] bg-[var(--ui-surface)] text-[var(--ui-fg-muted)] hover:text-[var(--ui-accent)] hover:border-[var(--ui-accent)] transition-all"
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
        <div className="bg-[var(--ui-surface)] rounded-xl border border-[var(--ui-border)] shadow-sm overflow-hidden">
          {/* ── My-Todo Sub-tabs (待我审核 / 待我实施 / 待我修改) ── */}
          {FEATURE_TODO_SUBTABS && viewTab === 'my_todo' && (
            <div className="flex items-center gap-1 px-4 pt-3 pb-0 border-b border-[var(--ui-border)]">
              {([
                { key: 'review',     zh: '待我审核', en: 'Pending Review' },
                { key: 'implement',  zh: '待我实施', en: 'Pending Implementation' },
                { key: 'modify',     zh: '待我修改', en: 'Pending Modification' },
              ] as const).map(tab => (
                <button
                  key={tab.key}
                  type="button"
                  aria-pressed={myTodoSubTab === tab.key}
                  onClick={() => { setMyTodoSubTab(tab.key); setPage(1); }}
                  className={`px-4 py-2 text-sm font-medium rounded-t-xl border-b-2 transition-all -mb-px ${
                    myTodoSubTab === tab.key
                      ? 'border-[var(--ui-accent)] text-[var(--ui-accent)] bg-[var(--ui-accent-subtle)]'
                      : 'border-transparent text-[var(--ui-fg-muted)] hover:text-[var(--ui-fg)] hover:border-black/20'
                  }`}
                >
                  {zh ? tab.zh : tab.en}
                </button>
              ))}
            </div>
          )}
          {loadError && orders.length > 0 && (
            <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-rose-200 bg-rose-50/80 px-5 py-3 text-sm text-rose-800">
              <span className="min-w-0 flex-1">{staleLoadErrorMessage}</span>
              <button type="button" onClick={() => void fetchOrders()} disabled={loading} className="shrink-0 rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50">
                {zh ? '重试' : 'Retry'}
              </button>
            </div>
          )}
          {loading && orders.length === 0 ? (
            <div role="status" aria-live="polite" className="flex items-center justify-center py-24 text-[var(--ui-fg-subtle)]">
              <RefreshCw size={18} className="animate-spin mr-2" /> {zh ? '加载中...' : 'Loading...'}
            </div>
          ) : loadError && orders.length === 0 ? (
            <div role="alert" className="flex flex-col items-center justify-center gap-3 py-24 text-center">
              <p className="text-sm text-rose-700">{loadErrorMessage}</p>
              <button type="button" onClick={() => void fetchOrders()} disabled={loading} className="rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-800 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50">
                {zh ? '重试' : 'Retry'}
              </button>
            </div>
          ) : orders.length === 0 ? (
            <TicketEmptyState title={zh ? '暂无变更工单' : 'No change orders'} description={zh ? '当前视图没有匹配的变更单，可调整筛选条件后查看。' : 'No change orders match this view. Adjust the filters to broaden the results.'} />
          ) : (
            <div className="overflow-x-auto">
              <DataTable unstyled exportConfig={{ filename: 'change-orders', language: zh ? 'zh' : 'en', disabled: loading || total === 0, exportData: exportAllOrders }} className="nx-data-table min-w-[880px] text-[13px]">
                <thead className="sticky top-0 z-10 bg-[var(--ui-surface-muted)] border-b border-[var(--ui-border)]">
                  <tr className="text-[var(--ui-fg-muted)] text-xs">
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '工单' : 'Order'}</th>
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '类型 · 优先级' : 'Type · Priority'}</th>
                    <th className="text-center px-4 py-3 font-semibold">{zh ? '状态' : 'Status'}</th>
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '当前处理' : 'Current handling'}</th>
                    <th className="text-left px-4 py-3 font-semibold">{zh ? '实施窗口' : 'Change window'}</th>
                    <TableActionHeader className="text-center px-4 py-3 font-semibold">{zh ? '操作' : 'Actions'}</TableActionHeader>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--ui-border)]">
                  {orders.map((order) => {
                    const sm = STATUS_META[order.status] || STATUS_META.draft;
                    const pm = PRIORITY_META[order.priority] || PRIORITY_META.medium;
                    const PriorityIcon = pm.icon;
                    const responsibility = describeCurrentResponsibility(order, language);
                    return (
                      <tr
                        key={order.id}
                        onClick={() => openDetail(order)}
                        className="cursor-pointer transition-colors hover:bg-[var(--ui-surface-muted)]"
                      >
                        <td className="max-w-[360px] px-4 py-3">
                          <div className="min-w-0">
                            <button type="button" className="block max-w-full truncate text-left font-medium text-[var(--ui-fg)] hover:text-[var(--ui-accent)]" title={order.title} onClick={(event) => { event.stopPropagation(); openDetail(order); }}>
                              {order.title || (zh ? '未命名工单' : 'Untitled order')}
                            </button>
                            <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[var(--ui-fg-muted)]">
                              <span className="font-mono font-semibold tracking-wide text-[var(--ui-fg-muted)]">
                            {bookmarkedIds.has(order.id) && <Star size={10} className="text-amber-400 fill-amber-400 flex-shrink-0" />}
                            {order.order_number}
                              </span>
                              <span>{zh ? `申请人：${order.requester_username || '—'}` : `By ${order.requester_username || '—'}`}</span>
                              <time dateTime={order.created_at}>{fmtTime(order.created_at)}</time>
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="mb-1.5 text-xs text-[var(--ui-fg-muted)]">{typeLabel(order.order_type, language)}</div>
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
                          <div className="max-w-[180px] truncate text-[13px] font-medium text-[var(--ui-fg)]" title={responsibility.owner}>{responsibility.owner}</div>
                          <div className="mt-1 text-xs text-[var(--ui-fg-muted)]">{responsibility.stage}</div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-xs text-[var(--ui-fg-muted)]">
                          {order.scheduled_start ? <><time dateTime={order.scheduled_start} className="block">{fmtTime(order.scheduled_start)}</time><time dateTime={order.scheduled_end} className="mt-1 block">{zh ? '至 ' : 'to '}{order.scheduled_end ? fmtTime(order.scheduled_end) : '—'}</time></> : '—'}
                        </td>
                        <TableActionCell className="px-4 py-3 text-center">
                          <ActionIconGroup label={zh ? '工单操作' : 'Change order actions'}>
                            <ActionIconButton
                              icon={Eye}
                              label={zh ? `查看工单 ${order.order_number}` : `View change order ${order.order_number}`}
                              onClick={(e) => { e.stopPropagation(); openDetail(order); }}
                            />
                            {['draft', 'rejected'].includes(order.status) && order.requester_username === currentUser.username && (
                              <ActionIconButton
                                icon={Pencil}
                                label={zh ? `编辑工单 ${order.order_number}` : `Edit change order ${order.order_number}`}
                                onClick={(e) => { e.stopPropagation(); openEdit(order); }}
                              />
                            )}
                            {['draft', 'cancelled'].includes(order.status) && order.requester_username === currentUser.username && (
                              <ActionIconButton
                                icon={Trash2}
                                label={zh ? `删除工单 ${order.order_number}` : `Delete change order ${order.order_number}`}
                                variant="danger"
                                onClick={(e) => { e.stopPropagation(); handleDelete(order.id); }}
                              />
                            )}
                          </ActionIconGroup>
                        </TableActionCell>
                      </tr>
                    );
                  })}
                </tbody>
              </DataTable>
            </div>
          )}
          <div className="border-t border-[var(--ui-border)]">
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
        </div>
      </div>
    </>
  );
};
