import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DeleteConfirmModal } from './DeleteConfirmModal';

describe('DeleteConfirmModal', () => {
  it('shows a safe backend error while keeping the confirmation open', () => {
    render(
      <DeleteConfirmModal
        isOpen
        onClose={vi.fn()}
        deleteTarget={{ id: 'asset-1', hostname: 'nexora', asset_tag: '' } as any}
        handleDelete={vi.fn()}
        error="服务内部异常，请联系管理员查看后端日志"
        language="zh"
      />,
    );

    expect(screen.getByRole('alert').textContent).toContain('服务内部异常，请联系管理员查看后端日志');
    expect(screen.getByRole('button', { name: '删除' })).toBeTruthy();
  });
});
