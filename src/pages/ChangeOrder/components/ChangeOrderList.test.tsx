import React, { type ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ChangeOrderList } from './ChangeOrderList';
import type { ChangeOrder } from '../types';

type ChangeOrderListProps = ComponentProps<typeof ChangeOrderList>;

const createProps = (overrides: Partial<ChangeOrderListProps> = {}) => ({
  language: 'en',
  orders: [],
  total: 0,
  loading: false,
  loadError: null,
  page: 1,
  pageSize: 10,
  setPage: vi.fn(),
  setPageSize: vi.fn(),
  search: '',
  setSearch: vi.fn(),
  statusFilter: '',
  setStatusFilter: vi.fn(),
  priorityFilter: '',
  setPriorityFilter: vi.fn(),
  bookmarkFilter: false,
  setBookmarkFilter: vi.fn(),
  showAdvancedSearch: false,
  setShowAdvancedSearch: vi.fn(),
  requesterFilter: '',
  setRequesterFilter: vi.fn(),
  assigneeFilter: '',
  setAssigneeFilter: vi.fn(),
  orderTypeFilter: '',
  setOrderTypeFilter: vi.fn(),
  createdFrom: '',
  setCreatedFrom: vi.fn(),
  createdTo: '',
  setCreatedTo: vi.fn(),
  completedFrom: '',
  setCompletedFrom: vi.fn(),
  completedTo: '',
  setCompletedTo: vi.fn(),
  scheduledFrom: '',
  setScheduledFrom: vi.fn(),
  scheduledTo: '',
  setScheduledTo: vi.fn(),
  viewTab: 'all',
  myTodoSubTab: 'review',
  setMyTodoSubTab: vi.fn(),
  users: [],
  currentUser: { id: 'operator-1', username: 'operator', role: 'Operator' },
  bookmarkedIds: new Set<string>(),
  advancedFilterCount: 0,
  fetchOrders: vi.fn(),
  fetchSummary: vi.fn(),
  fetchBookmarks: vi.fn(),
  openDetail: vi.fn(),
  openEdit: vi.fn(),
  handleDelete: vi.fn(),
  summary: null,
  FEATURE_TODO_SUBTABS: false,
  DEFAULT_PAGE_SIZE: 10,
  ...overrides,
} satisfies ChangeOrderListProps);

describe('ChangeOrderList feedback and controls', () => {
  afterEach(() => cleanup());

  it('shows permission failure instead of an empty queue and retries the current query', () => {
    const props = createProps({ loadError: 'permission' });
    render(<ChangeOrderList {...props} />);

    expect(screen.getByRole('alert').textContent).toContain('not authorized to view change orders');
    expect(screen.queryByText('No change orders')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(props.fetchOrders).toHaveBeenCalledTimes(1);
  });

  it('provides accessible names for the queue search and bookmark toggle', () => {
    const props = createProps();
    render(<ChangeOrderList {...props} />);

    expect(screen.getByRole('searchbox', { name: 'Search order number or title' })).toBeTruthy();
    const bookmarkFilter = screen.getByRole('button', { name: 'Show bookmarked change orders' });
    expect(bookmarkFilter.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(bookmarkFilter);
    expect(props.setBookmarkFilter).toHaveBeenCalledWith(true);
    expect(props.setPage).toHaveBeenCalledWith(1);
  });

  it('keeps the table compact and shows the responsible reviewer with the order summary', () => {
    const order: ChangeOrder = {
      id: 'order-1',
      order_number: 'CO-1',
      title: 'Core switch change',
      description: '',
      order_type: 'config_change',
      priority: 'medium',
      status: 'initial_review',
      requester_id: 'requester-id',
      requester_username: 'requester',
      assigned_initial_reviewer_id: 'reviewer-id',
      assigned_initial_reviewer_username: 'reviewer',
      assigned_final_approver_id: '',
      assigned_final_approver_username: '',
      initial_reviewer_id: '',
      initial_reviewer_username: '',
      final_approver_id: '',
      final_approver_username: '',
      approver_id: '',
      approver_username: '',
      target_devices: [],
      commands: [],
      rollback_plan: '',
      risk_level: 'low',
      scheduled_start: '',
      scheduled_end: '',
      actual_start: '',
      actual_end: '',
      result_summary: '',
      result_detail: {},
      rejected_reason: '',
      created_at: '2026-10-24T08:00:00Z',
      updated_at: '2026-10-24T08:00:00Z',
    };
    const props = createProps({
      orders: [order],
      total: 1,
      summary: { total: 1, by_status: { initial_review: 1 }, by_priority: {}, by_type: {} },
    });
    render(<ChangeOrderList {...props} />);

    const table = screen.getByRole('table');
    expect(screen.getByText('Core switch change')).toBeTruthy();
    expect(screen.getByText('CO-1')).toBeTruthy();
    expect(screen.getByText('reviewer')).toBeTruthy();
    expect(screen.getByRole('columnheader', { name: 'Current handling' })).toBeTruthy();
    expect(screen.getAllByRole('columnheader')).toHaveLength(6);
    expect(screen.getByLabelText('Change order summary')).toBeTruthy();
    expect(table.textContent).toContain('By requester');
  });
});
