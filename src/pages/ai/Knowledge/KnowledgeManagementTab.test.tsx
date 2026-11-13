import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DirectoryTreePicker } from './KnowledgeManagementTab';
import type { KnowledgeDirectoryNode } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: () => ({ language: 'zh', currentUser: { role: 'Administrator' } }),
}));

const node: KnowledgeDirectoryNode = {
  id: 'dir-product',
  knowledge_base_id: 'kb-default',
  tenant_id: 'tenant-default',
  parent_id: null,
  name: '01_product',
  path: '01_product',
  depth: 0,
  is_system: true,
  sort_order: 10,
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z',
  children: [],
};

describe('DirectoryTreePicker', () => {
  it('allows read-only users to browse but hides directory write actions', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();

    render(
      <DirectoryTreePicker
        nodes={[node]}
        selectedPath=""
        loading={false}
        inline
        canManage={false}
        onSelect={onSelect}
        onCreate={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.queryByRole('button', { name: '新建目录' })).toBeNull();
    expect(screen.queryByRole('group', { name: '目录操作' })).toBeNull();
    await user.click(screen.getByRole('button', { name: /01_product/ }));
    expect(onSelect).toHaveBeenCalledWith(node);
  });
});
