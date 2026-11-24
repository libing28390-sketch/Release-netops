import type { AIModel, AIProvider } from '../../../api/ai';
import type { CopilotModelOption } from './CopilotComposer';

/** Model types a chat conversation can use. Embedding/rerank models are not. */
const CHAT_MODEL_TYPES = new Set(['chat', 'reasoning', '']);

const HEALTH_RANK: Record<string, number> = {
  healthy: 0,
  unknown: 1,
  '': 1,
  not_supported: 1,
  unhealthy: 2,
  disabled: 3,
};

const healthRank = (status?: string | null): number => HEALTH_RANK[String(status || '').toLowerCase()] ?? 1;

/** Unusable now: still listed (the user may pick it on purpose), but last. */
export const isDegradedModel = (status?: string | null): boolean => healthRank(status) >= 2;

const normalise = (value: string | undefined | null): string => String(value || '').trim().toLowerCase();

const better = (left: AIModel, right: AIModel): boolean => {
  const healthDelta = healthRank(left.health_status) - healthRank(right.health_status);
  if (healthDelta !== 0) return healthDelta < 0;
  if (Boolean(left.is_default) !== Boolean(right.is_default)) return Boolean(left.is_default);
  if ((left.priority || 0) !== (right.priority || 0)) return (left.priority || 0) > (right.priority || 0);
  return String(left.updated_at || '') > String(right.updated_at || '');
};

/**
 * Copilot model picker options.
 *
 * - only enabled chat/reasoning models of enabled providers;
 * - one entry per provider + model code; distinct codes may share a display
 *   name. For duplicate codes, prefer health, default status and priority;
 * - healthy and unchecked models first, unhealthy and disabled ones last.
 */
export function buildCopilotModelOptions(providers: AIProvider[], models: AIModel[]): CopilotModelOption[] {
  const providerNames = new Map(
    (providers || []).filter((provider) => provider.enabled).map((provider) => [provider.id, provider.name]),
  );
  const chosen = new Map<string, AIModel>();
  for (const model of models || []) {
    if (!model || !model.enabled || !providerNames.has(model.provider_id)) continue;
    if (!CHAT_MODEL_TYPES.has(normalise(model.model_type))) continue;
    const codeKey = `${model.provider_id}::code::${normalise(model.model_code)}`;
    const existing = chosen.get(codeKey);
    if (!existing || better(model, existing)) chosen.set(codeKey, model);
  }
  return [...chosen.values()]
    .sort((left, right) => {
      const healthDelta = Number(isDegradedModel(left.health_status)) - Number(isDegradedModel(right.health_status));
      if (healthDelta !== 0) return healthDelta;
      if (Boolean(left.is_default) !== Boolean(right.is_default)) return left.is_default ? -1 : 1;
      return (right.priority || 0) - (left.priority || 0);
    })
    .map((model) => ({
      id: model.id,
      name: model.display_name || model.name,
      model_code: model.model_code,
      provider_id: model.provider_id,
      provider_name: providerNames.get(model.provider_id) || 'AI 供应商',
      model_type: model.model_type,
      context_length: model.context_length,
      health_status: model.health_status,
      stream_supported: model.stream_supported,
    }));
}

/** Keep the current choice if still offered, else the first usable model. */
export function pickCopilotModel(options: CopilotModelOption[], current: string): string {
  if (options.some((option) => option.id === current)) return current;
  const usable = options.find((option) => !isDegradedModel(option.health_status));
  return (usable || options[0])?.id || current;
}
