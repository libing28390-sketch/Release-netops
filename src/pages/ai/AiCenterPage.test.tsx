import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AiCenterPage,
  AiCenterPageLoadingState,
  canOpenAiCenterTab,
  firstAccessibleAiCenterTab,
  hasAiPermission,
  resolveAiCenterTab,
} from './AiCenterPage';

vi.mock('../../contexts/AppDomainContext', () => ({
  useCoreApp: vi.fn(),
}));

// Lazy sub-pages are replaced by stubs; these tests are about which page the
// AI Center shell chooses, not about the pages themselves.
vi.mock('./Providers/ProviderManagementTab', () => ({ ProviderManagementTab: () => <div>providers-stub</div> }));
vi.mock('./Copilot/AssistantTab', () => ({ AssistantTab: () => <div>copilot-stub</div> }));
vi.mock('./Security/SecurityPolicyTab', () => ({ SecurityPolicyTab: () => <div>security-stub</div> }));

const navTo = vi.fn();

const mockCoreApp = async (role: string | undefined, activeTab = 'ai-providers') => {
  const { useCoreApp } = await import('../../contexts/AppDomainContext');
  vi.mocked(useCoreApp).mockReturnValue({
    language: 'zh',
    activeTab,
    navTo,
    currentUser: { username: 'u', role },
  } as never);
};

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

describe('AI Center access rules (L6-e)', () => {
  it('mirrors the backend role table', () => {
    expect(hasAiPermission({ role: 'Administrator' }, 'ai.provider.manage')).toBe(true);
    expect(hasAiPermission({ role: 'Operator' }, 'ai.provider.manage')).toBe(false);
    expect(hasAiPermission({ role: 'Operator' }, 'ai.assistant')).toBe(true);
    expect(hasAiPermission({ role: 'Viewer' }, 'ai.assistant')).toBe(false);
    expect(hasAiPermission({ role: 'Viewer' }, 'ai.view')).toBe(true);
    expect(hasAiPermission({ role: 'Unknown' }, 'ai.view')).toBe(false);
    // Extra per-user permissions are honoured, as on the server.
    expect(hasAiPermission({ role: 'Operator', permissions: ['ai.provider.manage'] }, 'ai.provider.manage')).toBe(true);
  });

  it('does not hide pages when the session has no role (the server still enforces)', () => {
    expect(canOpenAiCenterTab({ role: undefined }, 'providers')).toBe(true);
  });

  it('lands an Operator on Copilot instead of the Provider page', () => {
    expect(firstAccessibleAiCenterTab({ role: 'Operator' })).toBe('copilot');
    expect(firstAccessibleAiCenterTab({ role: 'Administrator' })).toBe('providers');
    expect(resolveAiCenterTab({ role: 'Operator' }, 'providers', true)).toEqual({ kind: 'page', tab: 'copilot' });
    expect(resolveAiCenterTab({ role: 'Operator' }, undefined, false)).toEqual({ kind: 'page', tab: 'copilot' });
    expect(resolveAiCenterTab({ role: 'Operator' }, 'no-such-page', false)).toEqual({ kind: 'page', tab: 'copilot' });
  });

  it('reports an explicit request for a forbidden page instead of rendering it', () => {
    expect(resolveAiCenterTab({ role: 'Operator' }, 'providers', false)).toEqual({
      kind: 'forbidden', tab: 'providers', permission: 'ai.provider.manage', fallback: 'copilot',
    });
    expect(resolveAiCenterTab({ role: 'Operator' }, 'security', false)).toEqual({ kind: 'page', tab: 'security' });
  });

  it('a Viewer only gets pages that need ai.view', () => {
    expect(firstAccessibleAiCenterTab({ role: 'Viewer' })).toBe('health');
    expect(canOpenAiCenterTab({ role: 'Viewer' }, 'copilot')).toBe(false);
  });

  it('returns "none" when no page is accessible', () => {
    expect(resolveAiCenterTab({ role: 'Guest' }, undefined, true)).toEqual({ kind: 'none' });
  });
});

describe('AiCenterPage rendering', () => {
  beforeEach(() => navTo.mockClear());
  afterEach(() => cleanup());

  it('shows the Provider page to an Administrator', async () => {
    await mockCoreApp('Administrator');
    render(<AiCenterPage activeSubTab="providers" />);
    expect(await screen.findByText('providers-stub')).toBeTruthy();
  });

  it('opens Copilot for an Operator who opens the AI Center itself', async () => {
    await mockCoreApp('Operator', 'ai-center');
    render(<AiCenterPage activeSubTab="providers" />);
    expect(await screen.findByText('copilot-stub')).toBeTruthy();
    expect(screen.queryByText('providers-stub')).toBeNull();
  });

  it('shows a permission empty state, not a 403, for an explicit forbidden page', async () => {
    await mockCoreApp('Operator', 'ai-providers');
    const user = userEvent.setup();
    render(<AiCenterPage activeSubTab="providers" />);
    expect(screen.getByText('没有访问这个页面的权限')).toBeTruthy();
    expect(screen.getByText(/ai\.provider\.manage/)).toBeTruthy();
    expect(screen.queryByText('providers-stub')).toBeNull();
    await user.click(screen.getByRole('button', { name: '前往Copilot 对话' }));
    expect(navTo).toHaveBeenCalledWith('/ai/copilot');
  });
});
