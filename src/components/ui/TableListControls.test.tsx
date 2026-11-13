import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ColumnSettingsButton } from './TableListControls';

const columns = [
  { key: 'hostname', label: 'Hostname', required: true },
  { key: 'management_ip', label: 'Management IP' },
  { key: 'actions', label: 'Actions', isAction: true },
];

describe('ColumnSettingsButton', () => {
  afterEach(() => cleanup());

  it('applies the draft while retaining required columns', () => {
    const onApply = vi.fn();
    render(
      <ColumnSettingsButton
        columns={columns}
        visibleKeys={['hostname']}
        defaultVisibleKeys={['hostname', 'management_ip']}
        onApply={onApply}
        language="en"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Customize columns' }));
    expect(screen.getByRole('dialog', { name: 'Customize columns' })).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: 'Hostname' }) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Management IP' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onApply).toHaveBeenCalledWith(['hostname', 'management_ip']);
    expect(screen.queryByRole('dialog', { name: 'Customize columns' })).toBeNull();
  });

  it('closes on Escape and restores focus to its trigger', async () => {
    render(
      <ColumnSettingsButton
        columns={columns}
        visibleKeys={['hostname']}
        defaultVisibleKeys={['hostname']}
        onApply={vi.fn()}
        language="en"
      />,
    );

    const trigger = screen.getByRole('button', { name: 'Customize columns' });
    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Customize columns' })).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});
