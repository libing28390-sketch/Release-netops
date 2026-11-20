// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import StackMembersModal from './StackMembersModal';

const jsonRes = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('StackMembersModal', () => {
  beforeEach(() => {
    localStorage.setItem('netops_token', 'test-token');
  });

  afterEach(() => {
    cleanup();
    localStorage.removeItem('netops_token');
    vi.unstubAllGlobals();
  });

  it('previews CSV stack members, blocks commit on conflict, and commits when clean', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === '/api/assets/stack-members/import-preview' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body || '{}'));
        const firstRow = body.rows?.[0];
        if (firstRow?.serial_number === 'DUP-SN') {
          return jsonRes({
            summary: { total: 1, create: 0, update: 0, existing: 0, conflict: 1 },
            items: [{
              row_number: 2,
              action: 'conflict',
              stack_asset_tag: 'AST-STACK-1',
              member_number: 1,
              physical_asset_tag: 'AST-M1',
              serial_number: 'DUP-SN',
              rack_name: 'R01',
              u_start: 10,
              u_height: 1,
              conflicts: [{ row_number: 2, field: 'serial_number', message: 'SN already registered' }],
            }],
            conflicts: [{ row_number: 2, field: 'serial_number', message: 'SN already registered' }],
            can_commit: false,
          });
        }
        return jsonRes({
          summary: { total: 1, create: 1, update: 0, existing: 0, conflict: 0 },
          items: [{
            row_number: 2,
            action: 'create',
            stack_asset_tag: 'AST-STACK-1',
            member_number: 1,
            physical_asset_tag: 'AST-M1',
            serial_number: 'SN-CLEAN-1',
            rack_name: 'R01',
            u_start: 10,
            u_height: 1,
            conflicts: [],
          }],
          conflicts: [],
          can_commit: true,
        });
      }
      if (url === '/api/assets/stack-members/import-commit' && init?.method === 'POST') {
        return jsonRes({ created: 1, updated: 0, unchanged: 0 });
      }
      return jsonRes({});
    });
    vi.stubGlobal('fetch', fetchMock);

    const onChanged = vi.fn();
    render(
      <StackMembersModal
        mode="import"
        language="zh"
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    const textarea = screen.getByRole('textbox', { name: '堆叠成员 CSV 内容' });
    fireEvent.change(textarea, {
      target: {
        value: 'stack_asset_tag,member_number,physical_asset_tag,serial_number,model,rack_name,u_start,u_height,notes\nAST-STACK-1,1,AST-M1,DUP-SN,S5735,R01,10,1,',
      },
    });
    fireEvent.click(screen.getByRole('button', { name: '预览校验' }));

    expect(await screen.findByText(/SN already registered/)).toBeTruthy();
    const commitBtn = screen.getByRole('button', { name: '确认导入成员' }) as HTMLButtonElement;
    expect(commitBtn.disabled).toBe(true);

    fireEvent.change(textarea, {
      target: {
        value: 'stack_asset_tag,member_number,physical_asset_tag,serial_number,model,rack_name,u_start,u_height,notes\nAST-STACK-1,1,AST-M1,SN-CLEAN-1,S5735,R01,10,1,',
      },
    });
    fireEvent.click(screen.getByRole('button', { name: '预览校验' }));

    await waitFor(() => {
      expect((screen.getByRole('button', { name: '确认导入成员' }) as HTMLButtonElement).disabled).toBe(false);
    });
    fireEvent.click(screen.getByRole('button', { name: '确认导入成员' }));

    expect(await screen.findByText(/导入成功：新增 1/)).toBeTruthy();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('loads stack members, triggers SNMP reconcile, and replaces a member', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith('/api/assets/ast-1/stack-members?')) {
        return jsonRes({
          items: [{
            id: 'sm-1',
            asset_id: 'ast-1',
            member_number: 1,
            physical_asset_tag: 'PHY-01',
            serial_number: 'SN-OLD',
            model: 'S5735',
            rack_id: 'rack-1',
            rack_name: 'R01',
            u_start: 12,
            u_height: 1,
            status: 'active',
            entity_index: 1,
            last_reconciled_at: null,
            reconciliation_status: 'unverified',
            replaced_by_id: null,
            retired_at: null,
            notes: '',
          }],
        });
      }
      if (url === '/api/assets/ast-1/stack-members/reconcile-snmp' && init?.method === 'POST') {
        return jsonRes({
          matched_members: [{ member_number: 1, serial_number: 'SN-OLD', entity_index: 2 }],
          missing_members: [],
          mismatched_members: [],
          unregistered_chassis: [],
        });
      }
      if (url === '/api/assets/stack-members/sm-1/replace' && init?.method === 'POST') {
        return jsonRes({ ok: true });
      }
      return jsonRes({});
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <StackMembersModal
        mode="members"
        asset={{ id: 'ast-1', asset_tag: 'AST-STACK-1', hostname: 'SW-CORE-1' }}
        language="zh"
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByText('PHY-01')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'SNMP 对账' }));
    expect(await screen.findByText(/SNMP 对账完成：匹配 1/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '更换机箱' }));
    fireEvent.change(screen.getByPlaceholderText('新机箱 SN *'), { target: { value: 'SN-NEW-999' } });
    fireEvent.change(screen.getByPlaceholderText('新物理资产编号'), { target: { value: 'PHY-01-NEW' } });
    fireEvent.click(screen.getByRole('button', { name: '确认换机' }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u, init]) => String(u) === '/api/assets/stack-members/sm-1/replace' && init?.method === 'POST')).toBe(true);
    });
  });
});
