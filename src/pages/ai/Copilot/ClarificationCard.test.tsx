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
});
