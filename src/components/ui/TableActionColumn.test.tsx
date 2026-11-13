import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Pencil } from 'lucide-react';
import { ActionIconButton } from './ActionIconButton';
import { TableActionCell, TableActionHeader } from './TableActionColumn';

describe('table action column primitives', () => {
  it('provides a right-aligned action heading and labelled action group', () => {
    render(
      <table>
        <thead><tr><TableActionHeader>操作</TableActionHeader></tr></thead>
        <tbody>
          <tr>
            <TableActionCell label="Environment 的操作">
              <ActionIconButton icon={Pencil} label="编辑 Environment" />
            </TableActionCell>
          </tr>
        </tbody>
      </table>,
    );

    expect(screen.getByRole('columnheader', { name: '操作' }).classList.contains('nx-action-column-header')).toBe(true);
    expect(screen.getByRole('group', { name: 'Environment 的操作' }).classList.contains('nx-action-group')).toBe(true);
    expect(screen.getByRole('button', { name: '编辑 Environment' })).toBeTruthy();
  });

  it('accepts a single action passed as a one-item child array', () => {
    const { container } = render(
      <table>
        <tbody>
          <tr>
            <TableActionCell>{[<ActionIconButton key="edit" icon={Pencil} label="编辑 Environment" />]}</TableActionCell>
          </tr>
        </tbody>
      </table>,
    );

    expect(container.querySelector('button[aria-label="编辑 Environment"]')).not.toBeNull();
  });
});
