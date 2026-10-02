import { describe, expect, it } from 'vitest';
import type { AIModel, AIProvider } from '../../../api/ai';
import { buildAIModelExportData } from './modelExportData';

describe('buildAIModelExportData', () => {
  it('keeps each displayed field separate and includes the full filtered set without internal IDs', () => {
    const provider = { id: 'provider-db-id', name: 'DeepSeek' } as AIProvider;
    const models = Array.from({ length: 25 }, (_, index) => ({
      id: `model-db-id-${index}`,
      provider_id: provider.id,
      name: `Model ${index + 1}`,
      model_code: `model-${index + 1}`,
      model_type: 'chat',
      stream_supported: true,
      thinking_supported: false,
      tool_call_supported: true,
      json_supported: false,
      context_length: 128000,
      last_latency_ms: 42,
      cost_input_per_1k: 0.0002,
      is_default: index === 0,
      enabled: true,
      health_status: 'healthy',
    } as AIModel));
    const result = buildAIModelExportData(models, [provider], {
      headers: ['Name', 'Model code', 'Provider', 'Type', 'Streaming', 'Thinking', 'Tool calls', 'JSON', 'Context length', 'Health', 'Latency', 'Input cost', 'Default', 'Status'],
      yes: 'Yes',
      no: 'No',
      enabled: 'Enabled',
      disabled: 'Disabled',
      health: (status) => status || 'Unknown',
    });

    expect(result.rows).toHaveLength(25);
    expect(result.rows[0]).toEqual(['Model 1', 'model-1', 'DeepSeek', 'chat', 'Yes', 'No', 'Yes', 'No', 128000, 'healthy', '42 ms', '$0.0002', 'Yes', 'Enabled']);
    expect(JSON.stringify(result.rows)).not.toContain('model-db-id');
    expect(JSON.stringify(result.rows)).not.toContain('provider-db-id');
  });
});
