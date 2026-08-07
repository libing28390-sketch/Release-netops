import { apiRequest } from './http';

export interface AIProvider {
  id: string;
  name: string;
  provider_type: string;
  base_url?: string;
  api_key_masked?: string;
  timeout: number;
  max_retries: number;
  proxy_url?: string;
  enabled: boolean;
  created_by?: string;
  created_at: string;
  updated_at: string;
}

export interface AIModel {
  id: string;
  provider_id: string;
  name: string;
  model_code: string;
  model_type: string;
  thinking_supported: boolean;
  tool_call_supported: boolean;
  json_supported: boolean;
  context_length: number;
  max_output_tokens: number;
  default_temperature: number;
  default_max_tokens: number;
  enabled: boolean;
  is_default: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
}

export interface AIModelRoute {
  id: string;
  scene: string;
  model_id: string;
  fallback_model_id?: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AIPrompt {
  id: string;
  code: string;
  name: string;
  scene: string;
  vendor: string;
  platform: string;
  system_prompt: string;
  user_prompt_template: string;
  output_schema: string;
  temperature: number;
  max_tokens: number;
  version: number;
  enabled: boolean;
  created_by?: string;
  created_at: string;
  updated_at: string;
}

export interface CommandAnalysisRequest {
  command: string;
  output: string;
  vendor?: string;
  platform?: string;
}

export interface CommandAnalysisResponse {
  request_id: string;
  command_purpose: string;
  summary: string;
  important_fields: Array<Record<string, any>>;
  abnormalities: string[];
  recommendations: string[];
}

export interface ConfigAnalysisRequest {
  config_text: string;
  vendor?: string;
  platform?: string;
}

export interface ConfigAnalysisResponse {
  request_id: string;
  summary: string;
  routing_protocols: string[];
  security_risks: Array<Record<string, any>>;
  network_services: string[];
  management_services: string[];
  risk_items: Array<Record<string, any>>;
  recommendations: string[];
}

export interface DiffAnalysisRequest {
  diff_text: string;
  vendor?: string;
  platform?: string;
}

export interface DiffAnalysisResponse {
  request_id: string;
  summary: string;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  changes: Array<{
    type: string;
    risk: string;
    description: string;
    possible_impact: string[];
  }>;
  affected_services: string[];
  verification_commands: string[];
  rollback_recommendation: string[];
}

export interface AlarmAnalysisRequest {
  alarm_title: string;
  severity: string;
  fingerprint?: string;
  raw_content?: string;
  context_data?: Record<string, any>;
}

export interface AlarmAnalysisResponse {
  request_id: string;
  incident_summary: string;
  suspected_root_cause: string;
  confidence: number;
  evidence: string[];
  affected_scope: string[];
  recommended_actions: string[];
}

export interface AIUsageSummary {
  total_requests: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  avg_latency_ms: number;
  scene_breakdown: Record<string, number>;
}

export interface AgentRunResponse {
  run_id: string;
  agent_code: string;
  question: string;
  status: string;
  steps: Array<{
    step_no: number;
    step_type?: string;
    tool_name?: string;
    tool_input?: any;
    tool_output?: any;
    status?: string;
  }>;
  final_result: string;
}

// API functions
export async function getAIProviders(): Promise<AIProvider[]> {
  return apiRequest<AIProvider[]>('/api/ai/providers');
}

export async function createAIProvider(data: Partial<AIProvider> & { api_key?: string; default_model_code?: string }): Promise<AIProvider> {
  return apiRequest<AIProvider>('/api/ai/providers', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updateAIProvider(id: string, data: Partial<AIProvider> & { api_key?: string }): Promise<AIProvider> {
  return apiRequest<AIProvider>(`/api/ai/providers/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteAIProvider(id: string): Promise<void> {
  return apiRequest<void>(`/api/ai/providers/${id}`, {
    method: 'DELETE',
  });
}

export async function testAIProvider(id: string): Promise<{ success: boolean; latency_ms: number; message: string; sample_response?: string }> {
  return apiRequest<{ success: boolean; latency_ms: number; message: string; sample_response?: string }>(`/api/ai/providers/${id}/test`, {
    method: 'POST',
  });
}

export async function getAIModels(): Promise<AIModel[]> {
  return apiRequest<AIModel[]>('/api/ai/models');
}

export async function createAIModel(data: Partial<AIModel>): Promise<AIModel> {
  return apiRequest<AIModel>('/api/ai/models', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deleteAIModel(id: string): Promise<void> {
  return apiRequest<void>(`/api/ai/models/${id}`, {
    method: 'DELETE',
  });
}

export async function getAIModelRoutes(): Promise<AIModelRoute[]> {
  return apiRequest<AIModelRoute[]>('/api/ai/models/routes');
}

export async function upsertAIModelRoute(data: Partial<AIModelRoute>): Promise<AIModelRoute> {
  return apiRequest<AIModelRoute>('/api/ai/models/routes', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getAIPrompts(): Promise<AIPrompt[]> {
  return apiRequest<AIPrompt[]>('/api/ai/prompts');
}

export async function createAIPrompt(data: Partial<AIPrompt>): Promise<AIPrompt> {
  return apiRequest<AIPrompt>('/api/ai/prompts', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}


export async function analyzeCommand(data: CommandAnalysisRequest): Promise<CommandAnalysisResponse> {
  return apiRequest<CommandAnalysisResponse>('/api/ai/analyze/command', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function analyzeConfig(data: ConfigAnalysisRequest): Promise<ConfigAnalysisResponse> {
  return apiRequest<ConfigAnalysisResponse>('/api/ai/analyze/config', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function analyzeDiff(data: DiffAnalysisRequest): Promise<DiffAnalysisResponse> {
  return apiRequest<DiffAnalysisResponse>('/api/ai/analyze/diff', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function analyzeAlarm(data: AlarmAnalysisRequest): Promise<AlarmAnalysisResponse> {
  return apiRequest<AlarmAnalysisResponse>('/api/ai/analyze/alarm', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getAIUsageSummary(): Promise<AIUsageSummary> {
  return apiRequest<AIUsageSummary>('/api/ai/usage/summary');
}

export async function getAIAuditLogs(limit = 50): Promise<Array<Record<string, any>>> {
  return apiRequest<Array<Record<string, any>>>(`/api/ai/audit?limit=${limit}`);
}

// P2 Copilot APIs
export async function chatAssistant(message: string, history?: Array<{ role: string; content: string }>): Promise<{ answer: string; intent: string; citations: any[]; request_id: string }> {
  return apiRequest('/api/ai/assistant/chat', {
    method: 'POST',
    body: JSON.stringify({ message, history }),
  });
}

export async function chatAssistantStream(
  message: string,
  history: Array<{ role: string; content: string }> | undefined,
  onToken: (token: string) => void,
  onMeta?: (meta: { intent?: string; citations?: any[] }) => void
): Promise<void> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/ai/assistant/chat-stream', {
    method: 'POST',
    headers,
    body: JSON.stringify({ message, history }),
  });

  if (!response.ok) {
    const errText = await response.text();
    throw new Error(`HTTP ${response.status}: ${errText}`);
  }

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = 'token';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('event:')) {
        currentEvent = trimmed.slice(6).trim();
      } else if (trimmed.startsWith('data:')) {
        const dataStr = trimmed.slice(5).trim();
        if (!dataStr) continue;
        try {
          const parsed = JSON.parse(dataStr);
          if (currentEvent === 'meta' && onMeta) {
            onMeta(parsed);
          } else if (currentEvent === 'token' && parsed.content) {
            onToken(parsed.content);
          }
        } catch (e) {
          // ignore chunk parse error
        }
      }
    }
  }
}

export async function locateIP(ip: string): Promise<any> {
  return apiRequest('/api/ai/assistant/ip-location', {
    method: 'POST',
    body: JSON.stringify({ ip }),
  });
}

export async function locateMAC(mac: string): Promise<any> {
  return apiRequest('/api/ai/assistant/mac-location', {
    method: 'POST',
    body: JSON.stringify({ mac }),
  });
}

// P3 Agent APIs
export async function getRegisteredTools(): Promise<any[]> {
  return apiRequest<any[]>('/api/ai/agents/tools');
}

export async function runAgent(question: string, agentCode = 'troubleshooting_agent'): Promise<AgentRunResponse> {
  return apiRequest<AgentRunResponse>('/api/ai/agents/run', {
    method: 'POST',
    body: JSON.stringify({ agent_code: agentCode, question }),
  });
}

export async function getAgentRunTrace(runId: string): Promise<any> {
  return apiRequest(`/api/ai/agents/runs/${runId}/trace`);
}

// P4 Governance APIs
export async function generateAIConfig(intent: string, vendor = 'Huawei', platform = 'huawei_vrp'): Promise<any> {
  return apiRequest('/api/ai/governance/generate-config', {
    method: 'POST',
    body: JSON.stringify({ intent, vendor, platform }),
  });
}

export async function createChangeDraft(data: { title: string; device_id: string; commands: string[]; verification_commands?: string[]; rollback_commands?: string[] }): Promise<any> {
  return apiRequest('/api/ai/governance/create-draft', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

// Knowledge Base Management APIs
export async function getKnowledgeStats(): Promise<{ total_documents: number; total_chunks: number; total_vendors: number; ready_indexes: number }> {
  return apiRequest('/api/ai/assistant/knowledge-stats');
}

export async function getKnowledgeDocuments(sourceType?: string): Promise<any[]> {
  const url = sourceType ? `/api/ai/assistant/documents?source_type=${encodeURIComponent(sourceType)}` : '/api/ai/assistant/documents';
  return apiRequest(url);
}

export async function addKnowledgeDocument(data: {
  name: string;
  content: string;
  vendor?: string;
  platform?: string;
  knowledge_source_type?: string;
}): Promise<any> {
  return apiRequest('/api/ai/assistant/documents', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function clearSampleKnowledge(): Promise<any> {
  return apiRequest('/api/ai/assistant/clear-sample-knowledge', {
    method: 'POST',
  });
}

export async function deleteKnowledgeDocument(docId: string): Promise<any> {
  return apiRequest(`/api/ai/assistant/documents/${encodeURIComponent(docId)}`, {
    method: 'DELETE',
  });
}

export async function batchDeleteKnowledgeDocuments(docIds: string[]): Promise<any> {
  return apiRequest('/api/ai/assistant/documents/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ doc_ids: docIds }),
  });
}
