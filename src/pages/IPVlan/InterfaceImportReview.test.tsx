import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import InterfaceImportReview, { type InterfaceImportPreview, type InterfaceImportRequest } from './InterfaceImportReview';

const request: InterfaceImportRequest = { candidate_ids: ['source-a', 'source-b'], address_space_overrides: { 'source-a': 'global-1', 'source-b': 'global-1' } };
const preview: InterfaceImportPreview = {
  selected_candidate_count: 2, prefix_count: 1, new_prefix_count: 1, existing_prefix_count: 0,
  pending_candidate_count: 0, interface_count: 2, ip_count: 2, new_address_count: 2, existing_address_count: 0,
  can_generate: true, blockers: [], groups: [{
    group_id: 'global-1:192.0.2.0/30', candidate_ids: request.candidate_ids, prefix: '192.0.2.0/30',
    address_space_id: 'global-1', status: 'to_create', source_count: 2, interface_count: 2, ip_count: 2,
    interfaces: [{ device_name: 'Router-A', interface_name: 'Eth1', address: '192.0.2.1' }, { device_name: 'Router-B', interface_name: 'Eth2', address: '192.0.2.2' }],
  }],
};
const response = (payload: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => payload }) as Response;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount(payload: unknown = preview, status = 200) {
  const onConfirm = vi.fn();
  const fetcher = vi.fn(async () => response(payload, status));
  vi.stubGlobal('fetch', fetcher);
  render(<InterfaceImportReview request={request} spaceLabels={{ 'global-1': '全局（无 VRF）' }} zh submitting={false} generationError="" onBack={vi.fn()} onConfirm={onConfirm} />);
  return { onConfirm, fetcher };
}

it('shows one authoritative prefix with both endpoint IPs instead of treating two sources as two prefixes', async () => {
  const { onConfirm, fetcher } = mount();
  expect(await screen.findByText('192.0.2.0/30')).toBeTruthy();
  expect(screen.getAllByText('192.0.2.0/30')).toHaveLength(1);
  expect(screen.getByText('2 个接口 · 2 个 IP')).toBeTruthy();
  expect(screen.getByText(/Router-A/)).toBeTruthy();
  expect(screen.getByText(/Router-B/)).toBeTruthy();
  expect(onConfirm).not.toHaveBeenCalled();
  expect(fetcher).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole('button', { name: '确认导入' }));
  expect(onConfirm).toHaveBeenCalledWith(request);
  expect(fetcher).toHaveBeenCalledOnce();
});

it('recognizes a fully registered selection and prevents an unnecessary second import', async () => {
  const { onConfirm } = mount({ ...preview, new_prefix_count: 0, existing_prefix_count: 1, new_address_count: 0, existing_address_count: 2, groups: [{ ...preview.groups[0], status: 'existing' }] });
  expect(await screen.findByText('这些网段和接口 IP 已全部登记，无需重复导入。')).toBeTruthy();
  expect(screen.getByRole('button', { name: '已全部登记' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText('已存在 · 复用')).toBeTruthy();
  expect(onConfirm).not.toHaveBeenCalled();
});

it('keeps a resolved existing prefix importable when interface IPs still need registration', async () => {
  mount({ ...preview, new_prefix_count: 0, existing_prefix_count: 1, new_address_count: 1, existing_address_count: 1 });
  await screen.findByText('192.0.2.0/30');
  expect(screen.getByRole('button', { name: '确认导入' }).hasAttribute('disabled')).toBe(false);
});

it('preserves different address spaces when they have the same CIDR', async () => {
  mount({ ...preview, prefix_count: 2, new_prefix_count: 2, groups: [preview.groups[0], { ...preview.groups[0], group_id: 'vrf-b:192.0.2.0/30', address_space_id: 'vrf-b' }] });
  await waitFor(() => expect(screen.getAllByText('192.0.2.0/30')).toHaveLength(2));
});

it('disables import while the backend reports unresolved scope or conflicting ledger records', async () => {
  mount({ ...preview, can_generate: false, pending_candidate_count: 1, blockers: ['请确认网络归属'] });
  expect(await screen.findByText('请确认网络归属')).toBeTruthy();
  expect(screen.getByRole('button', { name: '确认导入' }).hasAttribute('disabled')).toBe(true);
});

it.each([
  [403, { detail: 'denied' }, '当前账号没有导入这些网段的权限。'],
  [404, { detail: 'hidden or stale source' }, '来源已变化或不可访问，请返回刷新后重新选择。'],
  [200, { groups: [], can_generate: true, blockers: [] }, '预览数据不完整，请刷新后重试。'],
] as const)('keeps the import disabled when preview returns %s', async (status, payload, message) => {
  mount(payload, status);
  expect(await screen.findByText(message)).toBeTruthy();
  expect(screen.getByRole('button', { name: '确认导入' }).hasAttribute('disabled')).toBe(true);
});

it('does not replace a new selection with a late response for the previous one', async () => {
  let resolveOld!: (response: Response) => void;
  const oldResponse = new Promise<Response>(resolve => { resolveOld = resolve; });
  vi.stubGlobal('fetch', vi.fn((url, init) => JSON.parse(String(init?.body)).candidate_ids[0] === 'source-a'
    ? oldResponse : Promise.resolve(response({ ...preview, groups: [{ ...preview.groups[0], prefix: '198.51.100.0/30' }] }))));
  const props = { spaceLabels: {}, zh: true, submitting: false, generationError: '', onBack: vi.fn(), onConfirm: vi.fn() };
  const view = render(<InterfaceImportReview {...props} request={request} />);
  view.rerender(<InterfaceImportReview {...props} request={{ candidate_ids: ['new-source'] }} />);
  expect(await screen.findByText('198.51.100.0/30')).toBeTruthy();
  resolveOld(response(preview));
  await waitFor(() => expect(screen.queryByText('192.0.2.0/30')).toBeNull());
  expect(screen.getByText('198.51.100.0/30')).toBeTruthy();
});
