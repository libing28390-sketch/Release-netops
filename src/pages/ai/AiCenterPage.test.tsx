import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AiCenterPageLoadingState } from './AiCenterPage';

describe('AiCenterPage loading state', () => {
  it('announces localized lazy-page loading with a status role', () => {
    const { rerender } = render(<AiCenterPageLoadingState language="zh" />);
    const status = screen.getByRole('status');
    expect(status.textContent).toContain('正在加载 AI 中心');
    expect(status.getAttribute('aria-busy')).toBe('true');
    expect(status.className).toContain('var(--ui-surface)');

    rerender(<AiCenterPageLoadingState language="en" />);
    expect(screen.getByRole('status').textContent).toContain('Loading AI Center');
  });
});
