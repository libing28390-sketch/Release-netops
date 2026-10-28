import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AuditTab from './AuditTab';

vi.mock('../components/DataTable', () => ({
  DataTable: ({ children }: React.PropsWithChildren) => <table>{children}</table>,
}));
vi.mock('../components/PageHero', () => ({ default: () => <header /> }));
vi.mock('../components/Pagination', () => ({ default: () => null }));

const renderAuditTab = (language = 'en', activeFilters = false) => {
  const setAuditCategoryFilter = vi.fn();
  const setAuditSeverityFilter = vi.fn();
  const setAuditStatusFilter = vi.fn();
  const setAuditTimeFilter = vi.fn();
  const setAuditPage = vi.fn();

  render(
    <AuditTab
      auditRows={[]}
      auditTotal={0}
      auditPage={activeFilters ? 4 : 1}
      setAuditPage={setAuditPage}
      auditPageSize={10}
      setAuditPageSize={vi.fn()}
      auditLoading={false}
      auditCategoryFilter={activeFilters ? 'auth' : 'all'}
      setAuditCategoryFilter={setAuditCategoryFilter}
      auditSeverityFilter={activeFilters ? 'critical' : 'all'}
      setAuditSeverityFilter={setAuditSeverityFilter}
      auditStatusFilter={activeFilters ? 'failed' : 'all'}
      setAuditStatusFilter={setAuditStatusFilter}
      auditTimeFilter={activeFilters ? '7d' : 'all'}
      setAuditTimeFilter={setAuditTimeFilter}
      openAuditEventDetail={vi.fn()}
      language={language}
      t={(key) => key}
    />,
  );

  return { setAuditCategoryFilter, setAuditSeverityFilter, setAuditStatusFilter, setAuditTimeFilter, setAuditPage };
};

describe('AuditTab filter controls', () => {
  afterEach(() => cleanup());

  it('gives each filter a localized accessible name and the shared focus treatment', () => {
    renderAuditTab();

    const filters = [
      screen.getByRole('combobox', { name: 'Category' }),
      screen.getByRole('combobox', { name: 'Severity' }),
      screen.getByRole('combobox', { name: 'Status' }),
      screen.getByRole('combobox', { name: 'Time range' }),
    ];

    for (const filter of filters) {
      expect(filter.className).toContain('focus-visible:ring-2');
      expect(filter.className).toContain('var(--ui-surface)');
    }

    cleanup();
    renderAuditTab('zh');
    expect(screen.getByRole('combobox', { name: '分类' })).toBeTruthy();
  });

  it('keeps each selection wired to its existing filter state setter', () => {
    const setters = renderAuditTab();

    fireEvent.change(screen.getByRole('combobox', { name: 'Category' }), { target: { value: 'auth' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Severity' }), { target: { value: 'critical' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), { target: { value: 'failed' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Time range' }), { target: { value: '7d' } });

    expect(setters.setAuditCategoryFilter).toHaveBeenCalledWith('auth');
    expect(setters.setAuditSeverityFilter).toHaveBeenCalledWith('critical');
    expect(setters.setAuditStatusFilter).toHaveBeenCalledWith('failed');
    expect(setters.setAuditTimeFilter).toHaveBeenCalledWith('7d');
  });

  it('resets all filters and pagination from a single action', () => {
    const setters = renderAuditTab('en', true);

    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));

    expect(setters.setAuditCategoryFilter).toHaveBeenCalledWith('all');
    expect(setters.setAuditSeverityFilter).toHaveBeenCalledWith('all');
    expect(setters.setAuditStatusFilter).toHaveBeenCalledWith('all');
    expect(setters.setAuditTimeFilter).toHaveBeenCalledWith('all');
    expect(setters.setAuditPage).toHaveBeenCalledWith(1);
  });
});
