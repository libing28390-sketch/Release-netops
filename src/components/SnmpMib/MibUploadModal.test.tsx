import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from '../../api/http';
import MibUploadModal from './MibUploadModal';

vi.mock('../../api/http', () => ({
  apiRequest: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequest);

const mibNode = {
  id: 'node-1',
  node_name: 'zxAnEnvMonCapabilities',
  oid: '1.3.6.1.4.1.3902.1082.10.10.1.1',
  parent_oid: '1.3.6.1.4.1.3902.1082.10.10.1',
  syntax_type: 'BITS',
  access_type: 'read-only',
  status: 'current',
  description: 'ZTE environment monitor capabilities',
};

const repositoryStats = {
  module_count: 1,
  parsed_module_count: 1,
  zero_node_module_count: 0,
  failed_module_count: 0,
  unresolved_oid_node_count: 0,
  vendor_counts: { ZTE: 1 },
  latest_import: null,
};

const mockSearchableRepository = () => {
  mockedApiRequest.mockImplementation(async (url) => {
    const requestUrl = String(url);
    if (requestUrl.startsWith('/api/platform-registry/mibs/sync-librenms/status')) {
      return { success: true, data: { running: false, repository: repositoryStats } } as never;
    }
    if (requestUrl.startsWith('/api/platform-registry/mibs/nodes/search?')) {
      return { success: true, data: [{ ...mibNode, mib_id: 'mib-1', mib_name: 'ZTE-AN-ENVMON-MIB', vendor: 'ZTE' }] } as never;
    }
    if (requestUrl === '/api/platform-registry/mibs/mib-1') {
      return {
        success: true,
        data: {
          id: 'mib-1',
          name: 'ZTE-AN-ENVMON-MIB',
          vendor: 'ZTE',
          description: 'Official LibreNMS MIB for ZTE',
          nodes: [mibNode],
          resolved_node_count: 1,
          unresolved_node_count: 0,
        },
      } as never;
    }
    if (requestUrl.startsWith('/api/platform-registry/mibs?')) {
      return {
        success: true,
        data: [{
          id: 'mib-1',
          name: 'ZTE-AN-ENVMON-MIB',
          vendor: 'ZTE',
          filename: 'ZTE-AN-ENVMON-MIB',
          file_size: 1024,
          node_count: 1,
          source_type: 'librenms',
          created_at: '',
          updated_at: '',
        }],
        total: 1,
        page: 1,
        stats: repositoryStats,
      } as never;
    }
    return { success: true, data: [] } as never;
  });
};

describe('MibUploadModal node search and template mapping', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('filters the repository by vendor and parsed status', async () => {
    const user = userEvent.setup();
    mockSearchableRepository();

    render(
      <MibUploadModal
        open
        language="zh"
        onClose={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getAllByText('ZTE-AN-ENVMON-MIB').length).toBeGreaterThan(0));
    expect(screen.getByRole('button', { name: '上传 MIB / ZIP' })).toBeTruthy();
    const vendorCombobox = screen.getByRole('combobox', { name: '厂商分类' });
    await user.click(vendorCombobox);
    const vendorSearch = screen.getByLabelText('搜索厂商');
    await user.type(vendorSearch, 'zte');
    expect(screen.getByRole('option', { name: /^ZTE$/ })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /^Huawei$/ })).toBeNull();
    await user.click(screen.getByRole('option', { name: /^ZTE$/ }));
    await waitFor(() => expect(
      mockedApiRequest.mock.calls.some(([url]) => String(url).includes('vendor=ZTE')),
    ).toBe(true));
    await user.click(screen.getByRole('button', { name: /含节点模块/ }));
    await waitFor(() => expect(
      mockedApiRequest.mock.calls.some(([url]) => String(url).includes('status=parsed')),
    ).toBe(true));
  });

  it('searches nodes in the selected MIB and exposes direct template mapping', async () => {
    const user = userEvent.setup();
    const onMapNodeToTemplate = vi.fn();
    mockSearchableRepository();

    render(
      <MibUploadModal
        open
        language="zh"
        onClose={vi.fn()}
        showToast={vi.fn()}
        onMapNodeToTemplate={onMapNodeToTemplate}
      />,
    );

    await waitFor(() => expect(screen.getAllByText('ZTE-AN-ENVMON-MIB').length).toBeGreaterThan(0));
    await user.click(screen.getAllByText('ZTE-AN-ENVMON-MIB')[0]);
    await waitFor(() => expect(screen.getByText('zxAnEnvMonCapabilities')).toBeTruthy());

    const searchInput = screen.getByPlaceholderText('搜索节点名称 / OID…');
    await user.type(searchInput, 'zxAnEnvMon');
    await user.click(screen.getByRole('button', { name: '搜索' }));

    await waitFor(() => expect(
      mockedApiRequest.mock.calls.some(([url]) => {
        const requestUrl = String(url);
        return requestUrl.startsWith('/api/platform-registry/mibs/nodes/search?')
          && requestUrl.includes('mib_id=mib-1')
          && requestUrl.includes('scope=node');
      }),
    ).toBe(true));

    await user.click(screen.getByRole('button', { name: '映射到新建模板' }));
    expect(onMapNodeToTemplate).toHaveBeenCalledWith(expect.objectContaining({
      node_name: 'zxAnEnvMonCapabilities',
      oid: mibNode.oid,
      mib_name: 'ZTE-AN-ENVMON-MIB',
    }), 'cpu');
  });

  it('uploads a ZIP archive as multipart form data and refreshes the repository', async () => {
    const user = userEvent.setup();
    const showToast = vi.fn();
    mockedApiRequest.mockImplementation(async (url, init) => {
      const requestUrl = String(url);
      if (requestUrl.startsWith('/api/platform-registry/mibs/sync-librenms/status')) {
        return { success: true, data: { running: false, repository: null } } as never;
      }
      if (requestUrl.startsWith('/api/platform-registry/mibs/upload')) {
        expect(init?.method).toBe('POST');
        expect(init?.body).toBeInstanceOf(FormData);
        return {
          success: true,
          imported: 2,
          failed: 1,
          data: [],
          errors: [{ filename: 'broken.mib', error: 'parse failed' }],
        } as never;
      }
      if (requestUrl.startsWith('/api/platform-registry/mibs?')) {
        return { success: true, data: [], total: 0, page: 1, stats: null } as never;
      }
      return { success: true, data: [] } as never;
    });

    render(
      <MibUploadModal
        open
        language="zh"
        onClose={vi.fn()}
        showToast={showToast}
      />,
    );

    const input = screen.getByLabelText('选择 MIB 或 ZIP 文件');
    await user.upload(input, new File(['zip bytes'], 'vendor-mibs.zip', { type: 'application/zip' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('MIB 导入完成：成功 2 个，失败 1 个', 'info'));
    expect(mockedApiRequest.mock.calls.some(([url]) => String(url).startsWith('/api/platform-registry/mibs/upload'))).toBe(true);
  });

  it('keeps the current MIB list visible while a vendor filter reloads', async () => {
    const user = userEvent.setup();
    let listRequestCount = 0;
    let resolveVendorRequest: ((value: unknown) => void) | null = null;
    const stats = {
      module_count: 1,
      parsed_module_count: 1,
      zero_node_module_count: 0,
      failed_module_count: 0,
      unresolved_oid_node_count: 0,
      vendor_counts: { ZTE: 1, Huawei: 1 },
      latest_import: null,
    };
    const zteMib = {
      id: 'mib-zte',
      name: 'ZTE-AN-ENVMON-MIB',
      vendor: 'ZTE',
      filename: 'ZTE-AN-ENVMON-MIB',
      file_size: 1024,
      node_count: 1,
      source_type: 'librenms',
      created_at: '',
      updated_at: '',
    };

    mockedApiRequest.mockImplementation(async (url) => {
      const requestUrl = String(url);
      if (requestUrl.startsWith('/api/platform-registry/mibs/sync-librenms/status')) {
        return { success: true, data: { running: false, repository: stats } } as never;
      }
      if (requestUrl.startsWith('/api/platform-registry/mibs?')) {
        listRequestCount += 1;
        if (listRequestCount === 1) {
          return { success: true, data: [zteMib], total: 1, page: 1, stats } as never;
        }
        return new Promise(resolve => {
          resolveVendorRequest = resolve;
        }) as never;
      }
      return { success: true, data: [] } as never;
    });

    render(
      <MibUploadModal
        open
        language="zh"
        onClose={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getAllByText('ZTE-AN-ENVMON-MIB').length).toBeGreaterThan(0));
    await user.click(screen.getByRole('combobox', { name: '厂商分类' }));
    await user.click(screen.getByRole('option', { name: /^Huawei$/ }));

    await waitFor(() => expect(screen.getByText('正在更新列表…')).toBeTruthy());
    expect(screen.getAllByText('ZTE-AN-ENVMON-MIB').length).toBeGreaterThan(0);

    resolveVendorRequest?.({
      success: true,
      data: [{ ...zteMib, id: 'mib-huawei', name: 'HUAWEI-DEVICE-MIB', vendor: 'Huawei' }],
      total: 1,
      page: 1,
      stats,
    });
    await waitFor(() => expect(screen.getByText('HUAWEI-DEVICE-MIB')).toBeTruthy());
  });

  it('keeps the current detail visible while another MIB module loads', async () => {
    const user = userEvent.setup();
    let resolveSecondDetail: ((value: unknown) => void) | null = null;
    const stats = {
      module_count: 2,
      parsed_module_count: 2,
      zero_node_module_count: 0,
      failed_module_count: 0,
      unresolved_oid_node_count: 0,
      vendor_counts: { ZTE: 1, Huawei: 1 },
      latest_import: null,
    };
    const zteMib = {
      id: 'mib-zte',
      name: 'ZTE-AN-ENVMON-MIB',
      vendor: 'ZTE',
      filename: 'ZTE-AN-ENVMON-MIB',
      file_size: 1024,
      node_count: 1,
      source_type: 'librenms',
      created_at: '',
      updated_at: '',
    };
    const huaweiMib = {
      ...zteMib,
      id: 'mib-huawei',
      name: 'HUAWEI-DEVICE-MIB',
      vendor: 'Huawei',
    };
    const huaweiNode = { ...mibNode, id: 'node-2', node_name: 'hwDeviceCpuUsage' };

    mockedApiRequest.mockImplementation(async (url) => {
      const requestUrl = String(url);
      if (requestUrl.startsWith('/api/platform-registry/mibs/sync-librenms/status')) {
        return { success: true, data: { running: false, repository: stats } } as never;
      }
      if (requestUrl.startsWith('/api/platform-registry/mibs?')) {
        return { success: true, data: [zteMib, huaweiMib], total: 2, page: 1, stats } as never;
      }
      if (requestUrl === '/api/platform-registry/mibs/mib-zte') {
        return {
          success: true,
          data: {
            ...zteMib,
            description: 'Official LibreNMS MIB for ZTE',
            nodes: [mibNode],
            resolved_node_count: 1,
            unresolved_node_count: 0,
          },
        } as never;
      }
      if (requestUrl === '/api/platform-registry/mibs/mib-huawei') {
        return new Promise(resolve => {
          resolveSecondDetail = resolve;
        }) as never;
      }
      return { success: true, data: [] } as never;
    });

    render(
      <MibUploadModal
        open
        language="zh"
        onClose={vi.fn()}
        showToast={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getAllByText('ZTE-AN-ENVMON-MIB').length).toBeGreaterThan(0));
    await user.click(screen.getAllByText('ZTE-AN-ENVMON-MIB')[0]);
    await waitFor(() => expect(screen.getByText('zxAnEnvMonCapabilities')).toBeTruthy());

    await user.click(screen.getAllByText('HUAWEI-DEVICE-MIB')[0]);
    await waitFor(() => expect(screen.getByText('正在加载节点符号树…')).toBeTruthy());
    expect(screen.getByText('zxAnEnvMonCapabilities')).toBeTruthy();

    resolveSecondDetail?.({
      success: true,
      data: {
        ...huaweiMib,
        description: 'Official LibreNMS MIB for Huawei',
        nodes: [huaweiNode],
        resolved_node_count: 1,
        unresolved_node_count: 0,
      },
    });
    await waitFor(() => expect(screen.getByText('hwDeviceCpuUsage')).toBeTruthy());
  });
});
