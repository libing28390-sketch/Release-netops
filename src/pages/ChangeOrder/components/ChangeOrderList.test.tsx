import React, { type ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ChangeOrderList } from './ChangeOrderList';

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

    expect(screen.getByRole('textbox', { name: 'Search order number or title' })).toBeTruthy();
    const bookmarkFilter = screen.getByRole('button', { name: 'Show bookmarked change orders' });
    expect(bookmarkFilter.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(bookmarkFilter);
    expect(props.setBookmarkFilter).toHaveBeenCalledWith(true);
    expect(props.setPage).toHaveBeenCalledWith(1);
  });
});
