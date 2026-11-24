import { describe, expect, it } from 'vitest';
import type { AIModel, AIProvider } from '../../../api/ai';
import { buildCopilotModelOptions, pickCopilotModel } from './modelOptions';

const provider = (id: string, name: string, enabled = true) => ({ id, name, enabled }) as unknown as AIProvider;

const model = (overrides: Partial<AIModel>): AIModel => ({
  id: 'm',
  provider_id: 'p1',
  name: 'Model',
  model_code: 'model',
  model_type: 'chat',
  thinking_supported: false,
  tool_call_supported: true,
  json_supported: true,
  context_length: 131072,
  max_output_tokens: 16384,
  default_temperature: 0.7,
  default_max_tokens: 4096,
  enabled: true,
  is_default: false,
  priority: 10,
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
  health_status: 'healthy',
  ...overrides,
});

describe('Copilot model options', () => {
  const providers = [provider('p1', 'DeepSeek'), provider('p2', 'Local'), provider('p3', 'Off', false)];

  it('keeps distinct codes with the same name and prefers the healthy row for duplicate codes', () => {
    const options = buildCopilotModelOptions(providers, [
      model({ id: 'a', name: 'P1Model', model_code: 'p1', health_status: 'unhealthy' }),
      model({ id: 'b', name: 'P1Model', model_code: 'p1-copy', health_status: 'unhealthy' }),
      model({ id: 'a-healthy', name: 'P1Model', model_code: 'p1', health_status: 'healthy' }),
      model({ id: 'c', name: 'deepseek', model_code: 'deepseek-v4-flash', health_status: 'healthy' }),
    ]);
    expect(options.map((item) => item.id)).toEqual(['a-healthy', 'c', 'b']);
  });

  it('drops embedding models, disabled models and disabled providers', () => {
    const options = buildCopilotModelOptions(providers, [
      model({ id: 'chat', model_code: 'chat' }),
      model({ id: 'emb', model_code: 'emb', name: 'Embedding', model_type: 'embedding' }),
      model({ id: 'off', model_code: 'off', name: 'Off', enabled: false }),
      model({ id: 'p3m', provider_id: 'p3', model_code: 'x', name: 'X' }),
    ]);
    expect(options.map((item) => item.id)).toEqual(['chat']);
  });

  it('lists unhealthy models last and picks a usable default', () => {
    const options = buildCopilotModelOptions(providers, [
      model({ id: 'bad', model_code: 'bad', name: 'Bad', health_status: 'unhealthy', is_default: true }),
      model({ id: 'good', provider_id: 'p2', model_code: 'good', name: 'Good', health_status: 'unknown' }),
    ]);
    expect(options.map((item) => item.id)).toEqual(['good', 'bad']);
    expect(pickCopilotModel(options, '')).toBe('good');
    expect(pickCopilotModel(options, 'bad')).toBe('bad');
  });
});
