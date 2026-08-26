import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

const clipboardMocks = vi.hoisted(() => ({
  copyTextWithFallback: vi.fn(),
}));

vi.mock('../utils/clipboard', () => clipboardMocks);

import { MarkdownRenderer } from './MarkdownRenderer';

describe('MarkdownRenderer links and code actions', () => {
  afterEach(() => {
    cleanup();
    clipboardMocks.copyTextWithFallback.mockReset();
    vi.restoreAllMocks();
  });

  it('normalizes escaped HTTP URLs into clickable links', () => {
    render(<MarkdownRenderer content={'官方文档：https\\://example.com/guide'} />);

    const link = screen.getByRole('link', { name: 'https://example.com/guide' });
    expect(link.getAttribute('href')).toBe('https://example.com/guide');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it('copies a code block and gives visible feedback', async () => {
    clipboardMocks.copyTextWithFallback.mockResolvedValue(true);

    render(<MarkdownRenderer content={'```huawei\nsystem-view\ndisplay ospf peer\n```'} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '复制代码' }));

    await waitFor(() => expect(clipboardMocks.copyTextWithFallback).toHaveBeenCalledWith('system-view\ndisplay ospf peer'));
    expect(screen.getByText('已复制')).toBeTruthy();
  });
});
