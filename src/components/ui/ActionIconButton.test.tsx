import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Copy, Download, Trash2 } from 'lucide-react';
import { ActionIconButton, ActionIconGroup, ActionLink } from './ActionIconButton';

describe('ActionIconButton', () => {
  it('exposes a labelled, consistent small action control', () => {
    render(<ActionIconButton icon={Copy} label="复制配置" onClick={vi.fn()} />);

    const button = screen.getByRole('button', { name: '复制配置' });
    expect(button.getAttribute('title')).toBe('复制配置');
    expect(button.getAttribute('data-action-icon')).toBe('true');
    expect(button.classList.contains('nx-action-icon')).toBe(true);
    expect(button.classList.contains('nx-action-icon--sm')).toBe(true);
    expect(button.classList.contains('nx-action-icon--default')).toBe(true);
  });

  it('supports a destructive variant and grouped alignment', () => {
    render(
      <ActionIconGroup label="行操作">
        <ActionIconButton icon={Trash2} label="删除配置" variant="danger" size="md" />
      </ActionIconGroup>,
    );

    expect(screen.getByRole('group', { name: '行操作' }).classList.contains('nx-action-group')).toBe(true);
    const button = screen.getByRole('button', { name: '删除配置' });
    expect(button.classList.contains('nx-action-icon--md')).toBe(true);
    expect(button.classList.contains('nx-action-icon--danger')).toBe(true);
  });

  it('uses the same labelled treatment for download links', () => {
    render(
      <ActionLink href="/manual.md" download icon={Download} variant="accent">
        下载手册
      </ActionLink>,
    );

    const link = screen.getByRole('link', { name: '下载手册' });
    expect(link.getAttribute('download')).toBe('');
    expect(link.classList.contains('nx-action-button')).toBe(true);
    expect(link.classList.contains('nx-action-button--accent')).toBe(true);
  });
});
