import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import KnowledgeAdminNavigation from './KnowledgeAdminNavigation';

describe('KnowledgeAdminNavigation', () => {
  afterEach(() => cleanup());

  it('uses Chinese-first labels and explains all knowledge administration views', () => {
    render(<KnowledgeAdminNavigation activeView="documents" onChange={vi.fn()} />);

    expect(screen.getByText('文档与版本')).toBeTruthy();
    expect(screen.getByText('来源与更新')).toBeTruthy();
    expect(screen.getByText('基线自检')).toBeTruthy();
    expect(screen.getByText('检索诊断')).toBeTruthy();
    expect(screen.getByText('校验厂商官网并监控来源更新')).toBeTruthy();
    expect(screen.getByText('用固定夹具检查检索规则是否回退')).toBeTruthy();
    expect(screen.getByText('查看一次检索为何命中或未命中')).toBeTruthy();
  });

  it('announces the selected function and requests a view change', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<KnowledgeAdminNavigation activeView="documents" onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: /基线自检/ }));
    expect(onChange).toHaveBeenCalledWith('evaluation');

    rerender(<KnowledgeAdminNavigation activeView="evaluation" onChange={onChange} />);
    expect(screen.getByText('当前：基线自检')).toBeTruthy();
    expect(screen.getByText(/它不读取当前租户文档/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /基线自检/ }).getAttribute('aria-pressed')).toBe('true');
  });
});
