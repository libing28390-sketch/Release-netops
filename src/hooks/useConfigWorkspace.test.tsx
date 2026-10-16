import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useConfigWorkspace } from './useConfigWorkspace';

const okResponse = (payload: unknown) => ({
  ok: true,
  status: 200,
  headers: new Headers(),
  json: vi.fn().mockResolvedValue(payload),
}) as unknown as Response;

const baseTemplate = {
  id: 'template-1',
  name: 'Template 1',
  type: 'Jinja2',
  category: 'custom',
  vendor: 'Custom',
  content: 'hostname {{ hostname }}',
};

describe('useConfigWorkspace refresh lifecycle', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => cleanup());

  it('preserves the selected template when refreshing workspace data', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith('/api/config-templates')) return okResponse({ items: [baseTemplate] });
      return okResponse([{ id: 'var-1', key: 'hostname', value: 'edge-01' }]);
    });

    const { result } = renderHook(() => useConfigWorkspace({
      devices: [],
      language: 'en',
      showToast: vi.fn(),
      currentUser: { username: 'operator' } as any,
      extractVars: (content) => [...content.matchAll(/\{\{\s*(\w+)/g)].map(match => match[1]),
    }));

    act(() => {
      result.current.setConfigTemplates([baseTemplate] as any);
      result.current.setSelectedTemplateId('template-1');
    });
    await act(async () => { await result.current.refreshConfigWorkspace(); });

    expect(result.current.selectedTemplateId).toBe('template-1');
    expect(result.current.selectedConfigTemplate?.id).toBe('template-1');
    expect(result.current.editorContent).toBe('hostname {{ hostname }}');
    expect(result.current.configVariableMap.hostname).toBe('edge-01');
  });

  it('refreshes lookups after saving a draft template and keeps its blank credential-free editor state', async () => {
    const savedRequests: Array<{ url: string; init: RequestInit }> = [];
    let persistedDraftId = '';
    vi.mocked(fetch).mockImplementation(async (input, init = {}) => {
      const url = String(input);
      if (url === '/api/config-templates') {
        savedRequests.push({ url, init });
        persistedDraftId = JSON.parse(String(init.body)).id;
        return okResponse({ id: persistedDraftId });
      }
      if (url.startsWith('/api/config-templates?page=')) return okResponse({ items: [{ ...baseTemplate, id: persistedDraftId, name: 'Untitled Template', content: 'interface {{ interface_name }}' }] });
      if (url === '/api/vars') return okResponse([]);
      return okResponse({});
    });
    const showToast = vi.fn();
    const { result } = renderHook(() => useConfigWorkspace({
      devices: [],
      language: 'en',
      showToast,
      currentUser: { username: 'operator' } as any,
      extractVars: () => [],
    }));

    act(() => result.current.handleNewTemplate());
    act(() => result.current.setEditorContent('interface {{ interface_name }}'));
    const draftId = result.current.selectedTemplateId;
    await act(async () => { await result.current.handleSaveTemplate(); });

    expect(savedRequests).toHaveLength(1);
    expect(JSON.parse(String(savedRequests[0].init.body)).content).toBe('interface {{ interface_name }}');
    expect(result.current.selectedTemplateId).toBe(draftId);
    expect(result.current.configTemplates[0]?.id).toBe(persistedDraftId);
    expect(result.current.editorContent).toBe('interface {{ interface_name }}');
    expect(showToast).toHaveBeenCalledWith('Template saved', 'success');
  });
});
