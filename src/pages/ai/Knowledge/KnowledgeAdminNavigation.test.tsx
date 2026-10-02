import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import KnowledgeAdminNavigation from './KnowledgeAdminNavigation';

describe('KnowledgeAdminNavigation', () => {
  afterEach(() => cleanup());

  it('uses compact Chinese-first labels and keeps view guidance in tooltips', () => {
    render(<KnowledgeAdminNavigation activeView="documents" onChange={vi.fn()} />);

    expect(screen.getByText('文档与版本')).toBeTruthy();
    expect(screen.getByText('来源与更新')).toBeTruthy();
    expect(screen.getByText('UAT 签署')).toBeTruthy();
    expect(screen.getByText('基线自检')).toBeTruthy();
    expect(screen.getByText('检索诊断')).toBeTruthy();
    expect(screen.getByRole('button', { name: /来源与更新/ }).getAttribute('title')).toContain('校验厂商官网并监控来源更新');
    expect(screen.getByRole('button', { name: /基线自检/ }).getAttribute('title')).toContain('用固定夹具检查检索规则是否回退');
    expect(screen.getByRole('button', { name: /检索诊断/ }).getAttribute('title')).toContain('查看一次检索为何命中或未命中');
    expect(screen.getByRole('button', { name: /UAT 签署/ }).getAttribute('title')).toContain('逐案例记录浏览器验收结论并签署');
  });

  it('announces the selected function and requests a view change', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<KnowledgeAdminNavigation activeView="documents" onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: /基线自检/ }));
    expect(onChange).toHaveBeenCalledWith('evaluation');

    rerender(<KnowledgeAdminNavigation activeView="evaluation" onChange={onChange} />);
    expect(screen.getByText('当前：基线自检')).toBeTruthy();
    expect(screen.getByRole('button', { name: /基线自检/ }).getAttribute('title')).toContain('它不读取当前租户文档');
    expect(screen.getByRole('button', { name: /基线自检/ }).getAttribute('aria-pressed')).toBe('true');
  });
});
