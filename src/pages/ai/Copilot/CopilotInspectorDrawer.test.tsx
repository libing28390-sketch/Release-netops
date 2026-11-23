import React, { useState } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { CopilotInspectorDrawer } from './CopilotInspectorDrawer';

const InspectorHarness = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button type="button" onClick={() => setIsOpen(true)}>打开 Inspector</button>
      <CopilotInspectorDrawer
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        activeMessage={{ intent: 'GENERAL_QA' }}
      />
    </>
  );
};

describe('CopilotInspectorDrawer keyboard interaction', () => {
  afterEach(() => cleanup());

  it('contains focus and returns it to the opener after Escape', async () => {
    const user = userEvent.setup();
    render(<InspectorHarness />);

    const opener = screen.getByRole('button', { name: '打开 Inspector' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog', { name: '开发者调试 Trace (Inspector)' });
    const closeButton = screen.getByRole('button', { name: '关闭调试 Trace' });
    expect(document.activeElement).toBe(closeButton);

    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it('shows zero hits for a knowledge miss and does not claim the model was skipped when it answered', () => {
    render(
      <CopilotInspectorDrawer
        isOpen
        onClose={() => undefined}
        activeMessage={{
          intent: 'knowledge',
          execution_mode: 'provider_generated',
          route_model: 'model-1',
          input_tokens: 12,
          output_tokens: 34,
          retrieval: { status: 'no_match', metadata_candidate_documents: 3, vector_top_n: 8 },
          sources: [],
        }}
      />,
    );
    expect(screen.getByText('本地 RAG 已执行 · 精确检索未命中')).toBeTruthy();
    const finalDocuments = document.querySelector('[data-copilot-final-documents="true"]');
    expect(finalDocuments?.textContent).toBe('0');
    expect(screen.getByText('model-1')).toBeTruthy();
    expect(screen.queryByText('未调用')).toBeNull();
  });

  it('does not show an invented relevance score for citation-only messages', () => {
    render(<CopilotInspectorDrawer isOpen onClose={() => undefined} activeMessage={{ sources: [{ document: 'SOP', section: '巡检' }] }} />);
    expect(screen.queryByText(/88%/)).toBeNull();
  });
});
