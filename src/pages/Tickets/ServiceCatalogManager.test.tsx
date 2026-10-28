import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import ServiceCatalogManager from './ServiceCatalogManager';

const response = (body: unknown) => ({ ok: true, status: 200, json: vi.fn().mockResolvedValue(body) }) as unknown as Response;

describe('ServiceCatalogManager', () => {
  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('closes with Escape when catalog editing is idle', async () => {
    localStorage.setItem('netops_token', 'test-token');
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(response({ success: true, data: [] }))));
    const onClose = vi.fn();
    render(<ServiceCatalogManager open groups={[]} onClose={onClose} onSaved={vi.fn()} language="en" />);

    expect(await screen.findByRole('dialog', { name: 'Service catalog' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
