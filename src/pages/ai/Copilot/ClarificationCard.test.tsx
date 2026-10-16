import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ClarificationCard } from './ClarificationCard';

const clarification = {
  required: true,
  state_id: 'clar_ui',
  revision: 2,
  request_kind: 'configuration_reference',
  risk: 'medium',
  missing_fields: ['feature', 'platform_or_model'],
  question: '你想配置哪项功能？同时请提供设备型号/OS。',
  options: [
    { field: 'feature', value: 'vlan', label: 'VLAN / Access / Trunk' },
    { field: 'cli_platform', value: 'huawei_yunshan_v600', label: 'Huawei YunShan V600' },
  ],
  allow_free_text: true,
  retrieval_allowed: false,
};

describe('ClarificationCard', () => {
  afterEach(() => cleanup());

  it('renders bounded choices and emits the selected option', async () => {
    const onSelect = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(<ClarificationCard clarification={clarification} onSelect={onSelect} onCancel={onCancel} />);

    expect(screen.getByText('先确认配置范围')).toBeTruthy();
    expect(screen.getByText('待补充：')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /VLAN \/ Access \/ Trunk/ }));
    expect(onSelect).toHaveBeenCalledWith(clarification.options[0]);

    await user.click(screen.getByRole('button', { name: /取消引导/ }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('shows recognized entities and prevents submitting an expired clarification', async () => {
    const onSelect = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <ClarificationCard
        clarification={{
          required: true,
          request_kind: 'intent_classification',
          risk: 'high',
          risk_level: 'R3',
          requires_confirmation: true,
          expires_at: '2020-01-01T00:00:00Z',
          question: '旧问题',
          missing_fields: ['confirmation'],
          recognized_fields: { device_id: 'edge-01', interface: 'Gi1/0/1' },
          options: [{ field: 'confirmation', value: 'yes', label: '确认执行' }],
        }}
        onSelect={onSelect}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByText('补充信息已过期')).toBeTruthy();
    expect(screen.getByText(/不会继续提交旧条件/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /确认执行/ }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole('button', { name: /重新开始/ }));
    expect(onSelect).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
