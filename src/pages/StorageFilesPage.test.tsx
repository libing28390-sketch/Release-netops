import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import StorageFilesPage from './StorageFilesPage';

const storageMocks = vi.hoisted(() => ({
  listProviders: vi.fn(),
  listObjects: vi.fn(),
  getObjectContent: vi.fn(),
}));

vi.mock('../api/storage', () => ({
  getStorageObjectContent: storageMocks.getObjectContent,
  listStorageObjects: storageMocks.listObjects,
  listStorageProviders: storageMocks.listProviders,
}));

describe('StorageFilesPage', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it('shows direct preview and CFG download actions for a selected snapshot', async () => {
    const object = {
      object_key: 'edge-01.cfg',
      s3_uri: 's3://nexora/edge-01.cfg',
      size: 18,
      last_modified: '2026-09-28T10:00:00Z',
    };
    storageMocks.listProviders.mockResolvedValue({
      items: [{
        id: 'profile-1', name: 'nexora', backend: 's3', endpoint_url: 'http://s3.local', bucket: 'nexora',
        region: 'us-east-1', force_path_style: true, verify_tls: false, is_default: true, source: 'database',
        has_access_key: true, has_secret_key: true,
      }],
      effective_default_id: 'profile-1',
    });
    storageMocks.listObjects.mockResolvedValue({
      provider_id: 'profile-1', provider_name: 'nexora', endpoint_url: 'http://s3.local', bucket: 'nexora',
      items: [object], folders: [], next_continuation_token: null, is_truncated: false,
    });
    storageMocks.getObjectContent.mockResolvedValue('hostname edge-01\n');

    const previousCreateObjectUrl = URL.createObjectURL;
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:config') });
    const downloadClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    try {
      const user = userEvent.setup();
      render(<StorageFilesPage language="zh" currentUser={{ role: 'Administrator' }} />);

      await user.click(await screen.findByText('edge-01.cfg'));
      const previewButton = await screen.findByRole('button', { name: '在线查看' });
      const downloadButton = screen.getByRole('button', { name: '下载 CFG' });
      expect(downloadButton).toBeTruthy();

      await user.click(previewButton);
      expect(await screen.findByText('hostname edge-01')).toBeTruthy();
      expect(storageMocks.getObjectContent).toHaveBeenCalledWith('profile-1', object.object_key, { signal: expect.any(AbortSignal) });

      await user.click(downloadButton);
      expect(storageMocks.getObjectContent).toHaveBeenLastCalledWith('profile-1', object.object_key, { download: true });
      expect(downloadClick).toHaveBeenCalledTimes(1);
    } finally {
      if (previousCreateObjectUrl) {
        Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: previousCreateObjectUrl });
      } else {
        Reflect.deleteProperty(URL, 'createObjectURL');
      }
    }
  });
});
