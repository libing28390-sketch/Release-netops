import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import UATSignoffPanel from './UATSignoffPanel';
import { getKnowledgeUATCaseHistory, getKnowledgeUATCampaign, signKnowledgeUATCase } from '../../../api/ai';

vi.mock('../../../contexts/AppDomainContext', () => ({
  useCoreApp: () => ({ language: 'zh', currentUser: { username: 'admin' } }),
}));

vi.mock('../../../api/ai', () => ({
  getKnowledgeUATCaseHistory: vi.fn(),
  getKnowledgeUATCampaign: vi.fn(),
  signKnowledgeUATCase: vi.fn(),
}));

const getCampaign = vi.mocked(getKnowledgeUATCampaign);
const getHistory = vi.mocked(getKnowledgeUATCaseHistory);
const signCase = vi.mocked(signKnowledgeUATCase);

const item = {
  case_id: 'UAT-HUA-01', suite: 'UAT-01', vendor: 'Huawei', scope_summary: 'Huawei CE6800；VRP；VLAN/VLANIF',
  observed_status: 'PASS', source_summary: '2 个 Huawei validated official VLAN 来源', risk_level: 'low',
  clarification_required: false, external_egress: false, cli_executed: false, observation_note: '',
  evidence_ref: 'docs/knowledge-engine/eval/eval-browser-uat-live-20260906.md', signoff_status: 'pending',
  reviewer_id: null, reviewer_name: null, signed_at: null, comment: '',
  signoff_evidence_ref: 'docs/knowledge-engine/eval/eval-browser-uat-live-20260906.md', history_count: 0,
} as const;

describe('UATSignoffPanel', () => {
  beforeEach(() => {
    getCampaign.mockResolvedValue({
      campaign_id: 'browser-uat-20260906', campaign_label: '浏览器 UAT-001（2026-09-06）',
      evidence_ref: item.evidence_ref, items: [item], total: 1,
      summary: { total: 1, signed: 0, pending: 1, approved: 0, partial: 0, rejected: 0, overall_status: 'PENDING_HUMAN_REVIEW', release_gate: 'HOLD' },
      campaign_summary: { total: 1, signed: 0, pending: 1, approved: 0, partial: 0, rejected: 0, overall_status: 'PENDING_HUMAN_REVIEW', release_gate: 'HOLD' },
      suites: [], vendors: ['Huawei'], can_sign: true, current_reviewer: { id: 'admin-1', name: 'admin' },
    });
    getHistory.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows observed facts separately and saves a server-owned sign-off', async () => {
    const user = userEvent.setup();
    signCase.mockResolvedValue({
      item: { ...item, signoff_status: 'approved', reviewer_id: 'admin-1', reviewer_name: 'admin', signed_at: '2026-09-06T00:00:00Z', history_count: 1 },
      summary: { total: 1, signed: 1, pending: 0, approved: 1, partial: 0, rejected: 0, overall_status: 'PASS', release_gate: 'PASS' },
      campaign_summary: { total: 1, signed: 1, pending: 0, approved: 1, partial: 0, rejected: 0, overall_status: 'PASS', release_gate: 'PASS' },
      audit_event_id: 'event-1',
    });

    render(<UATSignoffPanel />);

    expect(await screen.findByText('四厂商 UAT 签署')).toBeTruthy();
    expect(screen.getByText('机器观察事实（不可由签署表单修改）')).toBeTruthy();
    expect(screen.getAllByText('PASS').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: '保存签署' }));

    expect(signCase).toHaveBeenCalledWith(
      'browser-uat-20260906',
      'UAT-HUA-01',
      { decision: 'approved', comment: '', evidence_ref: item.evidence_ref },
    );
  });
});
