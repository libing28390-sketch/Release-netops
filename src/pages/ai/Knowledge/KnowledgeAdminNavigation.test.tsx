import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import KnowledgeAdminNavigation from './KnowledgeAdminNavigation';

describe('KnowledgeAdminNavigation', () => {
  afterEach(() => cleanup());

  it('uses compact Chinese-first labels for daily management views and keeps guidance in tooltips', () => {
    render(<KnowledgeAdminNavigation activeView="documents" onChange={vi.fn()} />);

    expect(screen.getByText('文档与版本')).toBeTruthy();
    expect(screen.getByText('来源与更新')).toBeTruthy();
    expect(screen.queryByText('UAT 签署')).toBeNull();
    expect(screen.queryByText('基线自检')).toBeNull();
    expect(screen.queryByText('检索诊断')).toBeNull();
    expect(screen.getByRole('button', { name: /来源与更新/ }).getAttribute('title')).toContain('校验厂商官网并监控来源更新');
  });

  it('announces the selected function and requests a view change', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<KnowledgeAdminNavigation activeView="documents" onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: /来源与更新/ }));
    expect(onChange).toHaveBeenCalledWith('sources');

    rerender(<KnowledgeAdminNavigation activeView="sources" onChange={onChange} />);
    expect(screen.getByText('当前：来源与更新')).toBeTruthy();
    expect(screen.getByRole('button', { name: /来源与更新/ }).getAttribute('aria-pressed')).toBe('true');
  });
});
