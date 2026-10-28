import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ServiceRequestComposer from './ServiceRequestComposer';
import type { ServiceCatalogItem } from './types';

const catalog: ServiceCatalogItem = {
  id: 'catalog-network-change',
  key: 'network_change',
  name: 'Network change',
  description: 'Request an approved network change.',
  version: 3,
  current_version: 3,
  requires_approval: true,
  request_schema: { fields: [
    { key: 'device', label: 'Device name', type: 'text', required: true },
    { key: 'change_type', label: 'Change type', type: 'select', required: true, options: ['Add VLAN', 'Update route'] },
  ] },
};

describe('ServiceRequestComposer', () => {
  afterEach(() => cleanup());

  it('renders the active catalog version fields and submits their values', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ServiceRequestComposer open catalogs={[catalog]} loading={false} error="" onClose={vi.fn()} onSubmit={onSubmit} language="en" />);

    fireEvent.change(screen.getByLabelText('Request title'), { target: { value: 'Add a guest VLAN' } });
    fireEvent.change(screen.getByLabelText(/Device name/), { target: { value: 'dc-sw-01' } });
    fireEvent.change(screen.getByLabelText(/Change type/), { target: { value: 'Add VLAN' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit request' }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      catalog_item_id: 'catalog-network-change',
      version: 3,
      title: 'Add a guest VLAN',
      details: { device: 'dc-sw-01', change_type: 'Add VLAN' },
    }));
  });

  it('shows permission-independent catalog load errors and empty catalog state', () => {
    const { rerender } = render(<ServiceRequestComposer open catalogs={[]} loading={false} error="Catalog access denied" onClose={vi.fn()} onSubmit={vi.fn()} language="en" />);
    expect(screen.getByText('No services are available to request.')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('Catalog access denied');
    rerender(<ServiceRequestComposer open catalogs={[]} loading error="" onClose={vi.fn()} onSubmit={vi.fn()} language="en" />);
    expect(screen.getByRole('status').textContent).toContain('Loading service catalog');
  });

  it('closes with Escape when no submission is in progress', () => {
    const onClose = vi.fn();
    render(<ServiceRequestComposer open catalogs={[catalog]} loading={false} error="" onClose={onClose} onSubmit={vi.fn()} language="en" />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
