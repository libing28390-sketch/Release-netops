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

  it('keeps code block DOM (and the user selection) when the parent re-renders', () => {
    const content = '```huawei\ndisplay ospf peer\ndisplay ospf brief\n```';
    const Parent: React.FC<{ tick: number }> = ({ tick }) => (
      <div data-tick={tick}>
        <MarkdownRenderer content={content} />
      </div>
    );
    const { container, rerender } = render(<Parent tick={0} />);
    const before = container.querySelector('pre code');
    expect(before).toBeTruthy();

    const range = document.createRange();
    range.selectNodeContents(before as Node);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);

    // A selection change or a timer re-renders the Copilot page.
    rerender(<Parent tick={1} />);

    expect(container.querySelector('pre code')).toBe(before);
    expect(window.getSelection()?.toString()).toContain('display ospf peer');
  });

  it('renders a fenced block without a language as a code block, not inline code', () => {
    render(<MarkdownRenderer content={'```\n<HUAWEI> display version\nVRP (R) software\n```'} />);
    expect(screen.getByText('CLI / Text')).toBeTruthy();
    expect(screen.getByRole('button', { name: '复制代码' })).toBeTruthy();
  });

  it('Ctrl+A inside a code block selects only that block', async () => {
    render(<MarkdownRenderer content={'前文说明\n\n```huawei\ndisplay interface brief\n```\n\n后文说明'} />);
    const block = screen.getByLabelText(/代码块/);
    block.focus();
    const user = userEvent.setup();
    await user.keyboard('{Control>}a{/Control}');
    const selected = window.getSelection()?.toString() || '';
    expect(selected).toContain('display interface brief');
    expect(selected).not.toContain('前文说明');
    expect(selected).not.toContain('后文说明');
  });

  it('does not add a top margin when the answer starts with a code block', () => {
    const { container } = render(<MarkdownRenderer content={'```bash\nshow version\n```'} />);
    const block = container.querySelector('[data-code-block="true"]');
    expect(block?.className).toContain('first:mt-0');
    expect(block?.className).toContain('my-3');
  });
});
