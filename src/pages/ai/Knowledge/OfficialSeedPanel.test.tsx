import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import OfficialSeedPanel from './OfficialSeedPanel';
import { importKnowledgeOfficialSeedBatch } from '../../../api/ai';

vi.mock('../../../api/ai', () => ({
  importKnowledgeOfficialSeedBatch: vi.fn(),
}));

const importSeedBatch = vi.mocked(importKnowledgeOfficialSeedBatch);

describe('OfficialSeedPanel', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('exposes the reviewed direct sources without selecting registry-only links', async () => {
    const user = userEvent.setup();
    render(<OfficialSeedPanel />);

    expect(screen.getByText('官方知识库种子来源')).toBeTruthy();
    expect(screen.getByText('9 个可直接采集')).toBeTruthy();
    const checkboxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
    expect(checkboxes).toHaveLength(13);
    expect(checkboxes.filter((input) => input.disabled)).toHaveLength(4);

    await user.click(screen.getByRole('button', { name: '全选当前可采集' }));
    expect(screen.getByText('已选 9 个')).toBeTruthy();
    expect((screen.getByRole('button', { name: '采集选中的官方资料' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('submits selected sources through the bounded batch endpoint and reports the result', async () => {
    const user = userEvent.setup();
    importSeedBatch.mockResolvedValue({
      batch_id: 'batch-1',
      item_count: 1,
      succeeded_count: 1,
      failed_count: 0,
      items: [],
    });
    render(<OfficialSeedPanel />);

    await user.click(screen.getByRole('button', { name: 'Huawei 2' }));
    await user.click(screen.getByRole('checkbox', { name: /S5700\/S6700 OSPF/ }));
    await user.click(screen.getByRole('button', { name: '采集选中的官方资料' }));

    expect(importSeedBatch).toHaveBeenCalledTimes(1);
    const payload = importSeedBatch.mock.calls[0][0];
    expect(payload).toHaveLength(1);
    expect(payload[0]).toMatchObject({
      vendor: 'Huawei',
      source_kind: 'configuration_guide',
      publish_to_knowledge_base: true,
      terms_review_status: 'approved',
    });
    expect(await screen.findByText(/成功 1 个，失败 0 个/)).toBeTruthy();
  });
});
