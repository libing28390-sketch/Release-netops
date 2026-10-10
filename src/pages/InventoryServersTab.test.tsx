import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import InventoryServersTab from './InventoryServersTab';

vi.mock('../components/DataTable', () => ({
  DataTable: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
}));
vi.mock('../components/PageHero', () => ({ default: ({ title }: { title: string }) => <h1>{title}</h1> }));

const response = (payload: unknown) => ({
  ok: true,
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

const allServerColumns = [
  '主机名', '管理 IP', '角色', '厂商', '型号', '数据中心', '机柜', 'U 位', '状态', 'Ping', 'SSH', '部门',
];

const renderServerPage = () => render(
  <InventoryServersTab language="zh" t={key => key} />,
);

describe('InventoryServersTab column defaults', () => {
  beforeEach(() => {
    window.localStorage.removeItem('netops:inventory-servers:columns:v1');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ items: [], total: 0 })));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('checks every available server column by default and restores all columns', async () => {
    renderServerPage();
    await screen.findByText('没有匹配的服务器');
    fireEvent.click(screen.getByRole('button', { name: '列设置' }));

    for (const column of allServerColumns) {
      expect((screen.getByRole('checkbox', { name: column }) as HTMLInputElement).checked).toBe(true);
    }

    fireEvent.click(screen.getByRole('checkbox', { name: 'Ping' }));
    expect((screen.getByRole('checkbox', { name: 'Ping' }) as HTMLInputElement).checked).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '恢复默认列' }));
    expect((screen.getByRole('checkbox', { name: 'Ping' }) as HTMLInputElement).checked).toBe(true);
  });

  it('migrates the previously auto-saved server defaults to all columns', async () => {
    window.localStorage.setItem('netops:inventory-servers:columns:v1', JSON.stringify({
      hostname: true,
      management_ip: true,
      device_role: false,
      vendor: false,
      model: false,
      datacenter: false,
      rack: false,
      rack_unit: false,
      status: true,
      ping: false,
      ssh: false,
      department: false,
    }));

    renderServerPage();
    await screen.findByText('没有匹配的服务器');
    fireEvent.click(screen.getByRole('button', { name: '列设置' }));

    for (const column of allServerColumns) {
      expect((screen.getByRole('checkbox', { name: column }) as HTMLInputElement).checked).toBe(true);
    }
  });
});
