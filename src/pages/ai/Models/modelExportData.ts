import type { AIModel, AIProvider } from '../../../api/ai';
import type { TableExportData } from '../../../components/ui/TableExportMenu';

export interface AIModelExportLabels {
  headers: string[];
  yes: string;
  no: string;
  enabled: string;
  disabled: string;
  health: (status?: string) => string;
}

export function buildAIModelExportData(
  models: AIModel[],
  providers: AIProvider[],
  labels: AIModelExportLabels,
): TableExportData {
  return {
    headers: labels.headers,
    rows: models.map((model) => {
      const provider = providers.find((item) => item.id === model.provider_id);
      return [
        model.name,
        model.model_code,
        provider?.name || '',
        model.model_type,
        model.stream_supported ? labels.yes : labels.no,
        model.thinking_supported ? labels.yes : labels.no,
        model.tool_call_supported ? labels.yes : labels.no,
        model.json_supported ? labels.yes : labels.no,
        model.context_length,
        labels.health(model.health_status),
        model.last_latency_ms == null ? '—' : `${model.last_latency_ms} ms`,
        `$${(model.cost_input_per_1k || 0).toFixed(4)}`,
        model.is_default ? labels.yes : labels.no,
        model.enabled ? labels.enabled : labels.disabled,
      ];
    }),
  };
}
