import { apiRequest, authHeaders, createClientRequestId } from './http';

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
  health_status?: string;
  last_health_check_at?: string | null;
  last_success_at?: string | null;
  last_error_code?: string | null;
  tags?: string[];
  data_region?: string;
  allowed_data_classification?: string;
  no_training_confirmed?: boolean;
  retention_days?: number | null;
  data_processing_agreement_ref?: string | null;
  agreement_reviewed_at?: string | null;
  approved_endpoint_patterns?: string[];
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
  stream_supported?: boolean;
  display_name?: string;
  cost_input_per_1k?: number;
  cost_output_per_1k?: number;
  health_status?: string;
  last_latency_ms?: number | null;
  last_success_at?: string | null;
  last_error_code?: string | null;
}

export interface AIModelRoute {
  id: string;
  scene: string;
  model_id: string;
  fallback_model_id?: string;
  enabled: boolean;
  priority?: number;
  data_classification?: string;
  created_at: string;
  updated_at: string;
  health_status?: string;
  last_health_check_at?: string | null;
  last_success_at?: string | null;
  last_error_code?: string | null;
  tags?: string[];
  data_region?: string;
  allowed_data_classification?: string;
}

export interface AISecurityPolicy {
  external_ai_enabled: boolean;
  kill_switch: boolean;
  max_payload_bytes: number;
  identifiers_must_be_tokenized: boolean;
  allow_sensitive_minimization: boolean;
  allowed_provider_types: string[];
  policy_version?: string;
  allowed_classifications?: string[];
  allowed_data_regions?: string[];
  provider_kill_switches?: Record<string, boolean>;
  tenant_kill_switches?: Record<string, boolean>;
  dev_passthrough?: {
    supported: boolean;
    configured: boolean;
    enabled: boolean;
    expires_at?: string | null;
    remaining_seconds: number;
    max_minutes: number;
    environment: string;
  };
}

export interface AISecurityDryRunResult {
  decision: string;
  max_data_level: string;
  finding_categories: string[];
  payload_bytes?: number;
  reason?: string;
  external_call_made: false;
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
  estimated_cost_usd?: number;
  budget_usd?: number;
  budget_percent?: number;
  budget_alert?: boolean;
  provider_breakdown?: Record<string, { requests: number; success?: number; errors?: number; error_rate?: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number; avg_latency_ms: number }>;
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

export async function testAIProvider(id: string): Promise<{
  success: boolean;
  latency_ms: number;
  message: string;
  model_tested?: string | null;
  sample_response?: string | null;
  error_code?: string | null;
}> {
  return apiRequest<{
    success: boolean;
    latency_ms: number;
    message: string;
    model_tested?: string | null;
    sample_response?: string | null;
    error_code?: string | null;
  }>(`/api/ai/providers/${id}/test`, {
    method: 'POST',
  });
}

export async function rotateAIProviderKey(id: string, api_key: string): Promise<AIProvider> {
  return apiRequest<AIProvider>(`/api/ai/providers/${id}/rotate-key`, { method: 'POST', body: JSON.stringify({ api_key }) });
}

export async function invalidateAIProviderKey(id: string, reason?: string): Promise<AIProvider> {
  return apiRequest<AIProvider>(`/api/ai/providers/${id}/invalidate-key`, { method: 'POST', body: JSON.stringify({ reason }) });
}

export async function getAIProviderDeletePreview(id: string): Promise<any> {
  return apiRequest(`/api/ai/providers/${id}/delete-preview`);
}

export interface AIPlatformMetrics {
  requests: Record<string, number>;
  by_scene: Record<string, { requests: number; avg_latency_ms: number; p95_latency_ms: number }>;
  providers?: Record<string, {
    requests: number;
    success: number;
    errors: number;
    error_rate: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
  }>;
  limits?: Record<string, number>;
  fallbacks?: Record<string, number>;
  retrieval?: {
    queries: number;
    no_match: number;
    no_match_rate: number;
    wrong_vendor: number;
    version_conflict: number;
    low_confidence: number;
    errors: number;
  };
  jobs?: {
    events: Record<string, number>;
    queues: Record<string, Record<string, number>>;
    observability?: {
      observed_at: string;
      sources: Record<string, string>;
      queues: Record<string, Record<string, number>>;
      alerts: Array<{
        code: string;
        severity: string;
        kind: string;
        value: number;
        threshold: number;
        message: string;
      }>;
      alert_thresholds: { backlog: number; failed: number; lease_anomalies: number };
    };
  };
  database?: {
    backend: string;
    status: string;
    read_only?: boolean;
    production_authority?: string;
    relation_stats?: {
      status: string;
      tables?: Array<{
        table: string;
        status: string;
        live_rows?: number;
        dead_rows?: number;
        total_bytes?: number;
        index_bytes?: number;
        dead_to_live_ratio?: number;
        vacuum_signal?: string | null;
      }>;
    };
    cache?: { status: string; hits?: number; reads?: number; hit_rate?: number };
    slow_queries?: {
      status: string;
      threshold_ms?: number;
      sample_size?: number;
      slow_query_count?: number;
      query_text_included?: boolean;
    };
    capacity?: {
      status: string;
      database_bytes?: number;
      budget_bytes?: number;
      usage_ratio?: number;
      synthetic_rows_inserted?: boolean;
    };
  };
  tools: Record<string, number>;
  agents: Record<string, number>;
  cache: { hits: number; misses: number; note?: string };
}

export async function getAISecurityPolicy(): Promise<AISecurityPolicy> {
  return apiRequest<AISecurityPolicy>('/api/ai/security/policy');
}

export async function updateAISecurityPolicy(payload: Partial<AISecurityPolicy>): Promise<AISecurityPolicy> {
  return apiRequest<AISecurityPolicy>('/api/ai/security/policy', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function setAIKillSwitch(enabled: boolean, reason?: string): Promise<{ enabled: boolean }> {
  return apiRequest<{ enabled: boolean }>('/api/ai/security/kill-switch', {
    method: 'POST',
    body: JSON.stringify({ enabled, reason }),
  });
}

export async function setAITenantKillSwitch(tenantId: string, enabled: boolean, reason?: string): Promise<{ tenant_id: string; enabled: boolean }> {
  return apiRequest<{ tenant_id: string; enabled: boolean }>('/api/ai/security/tenant-kill-switch', {
    method: 'POST',
    body: JSON.stringify({ tenant_id: tenantId, enabled, reason }),
  });
}

export async function setAIDevPassthrough(enabled: boolean, durationMinutes?: number): Promise<NonNullable<AISecurityPolicy['dev_passthrough']>> {
  return apiRequest<NonNullable<AISecurityPolicy['dev_passthrough']>>('/api/ai/security/dev-passthrough', {
    method: 'POST',
    body: JSON.stringify({ enabled, duration_minutes: durationMinutes }),
  });
}

export async function testAISecurityPayload(messages: Array<{ role: string; content: string }>, tools?: unknown[]): Promise<AISecurityDryRunResult> {
  return apiRequest<AISecurityDryRunResult>('/api/ai/security/test-payload', {
    method: 'POST',
    body: JSON.stringify({ messages, tools }),
  });
}

export interface AISecurityEvent {
  id: string;
  request_id: string;
  policy_version: string;
  classification: string;
  data_region: string;
  decision: string;
  disposition: string;
  provider_id?: string | null;
  model_id?: string | null;
  finding_categories: string[];
  payload_bytes: number;
  error_code?: string | null;
  created_at: string;
}

export async function getAISecurityEvents(limit = 100, offset = 0): Promise<AISecurityEvent[]> {
  return apiRequest<AISecurityEvent[]>(`/api/ai/security/events?limit=${limit}&offset=${offset}`);
}

export interface AISecurityPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export async function getAISecurityEventsPage(query: { page?: number; page_size?: number; search?: string; decision?: string; classification?: string } = {}): Promise<AISecurityPage<AISecurityEvent>> {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (typeof value === 'number') params.set(key, String(value));
    else if (value?.trim()) params.set(key, value.trim());
  });
  return apiRequest<AISecurityPage<AISecurityEvent>>(`/api/ai/security/events/page?${params.toString()}`);
}

export async function exportAISecurityEvents(): Promise<string> {
  const response = await fetch('/api/ai/security/events/export', { headers: { Authorization: `Bearer ${localStorage.getItem('netops_token') || localStorage.getItem('token') || ''}` } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.text();
}

export interface AISecurityIncident {
  id: string;
  task_id?: string | null;
  request_id?: string | null;
  incident_type: string;
  severity: string;
  category: string;
  status: string;
  created_at: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
}

export async function getAISecurityIncidents(status = ''): Promise<AISecurityIncident[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  return apiRequest<AISecurityIncident[]>(`/api/ai/security/incidents${query}`);
}

export async function getAISecurityIncidentsPage(query: { page?: number; page_size?: number; search?: string; status?: string; severity?: string } = {}): Promise<AISecurityPage<AISecurityIncident>> {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (typeof value === 'number') params.set(key, String(value));
    else if (value?.trim()) params.set(key, value.trim());
  });
  return apiRequest<AISecurityPage<AISecurityIncident>>(`/api/ai/security/incidents/page?${params.toString()}`);
}

export async function resolveAISecurityIncident(id: string): Promise<{ id: string; status: string; resolved_at: string }> {
  return apiRequest(`/api/ai/security/incidents/${encodeURIComponent(id)}/resolve`, { method: 'POST' });
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

export async function updateAIModel(id: string, data: Partial<AIModel>): Promise<AIModel> {
  return apiRequest<AIModel>(`/api/ai/models/${id}`, { method: 'PUT', body: JSON.stringify(data) });
}

export async function setAIUserDefaultModel(model_id: string): Promise<{ model_id: string; tenant_id: string; updated_at: string }> {
  return apiRequest('/api/ai/models/preferences/default', { method: 'POST', body: JSON.stringify({ model_id }) });
}

export async function setAIModelAccess(id: string, data: { tenant_id?: string; subject_type: 'role' | 'user' | 'tenant'; subject_id: string; allow_access: boolean }): Promise<any> {
  return apiRequest(`/api/ai/models/${id}/access`, { method: 'POST', body: JSON.stringify(data) });
}

export interface AIAuditLog {
  id: string;
  request_id: string;
  user_id?: string | null;
  scene: string;
  provider_id?: string | null;
  model_id?: string | null;
  prompt_id?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  latency_ms?: number | null;
  status: string;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
}

export async function getAIAuditLogs(limit = 50): Promise<AIAuditLog[]> {
  return apiRequest<AIAuditLog[]>(`/api/ai/audit?limit=${limit}`);
}

export async function getAIPlatformMetrics(): Promise<AIPlatformMetrics> {
  return apiRequest<AIPlatformMetrics>('/api/ai/metrics');
}

// P2 Copilot APIs
export type AssistantProcessStepStatus = 'running' | 'completed' | 'error';

export interface AssistantProcessStep {
  event_version?: string;
  stream_id?: string;
  sequence?: number;
  id: string;
  label: string;
  status: AssistantProcessStepStatus;
  detail?: string;
  operation?: string;
  command?: string;
}

export interface AssistantStreamDoneMeta {
  event_version?: string;
  stream_id?: string;
  sequence?: number;
  status?: 'completed' | 'cancelled' | 'error' | string;
  duration_ms?: number;
  latency_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  model_id?: string;
  provider_id?: string;
  route_reason?: string;
  execution_mode?: AIExecutionMode;
  external_egress?: boolean;
  token_source?: AITokenSource;
}

export type AIExecutionMode = 'local_knowledge' | 'local_operation' | 'provider_generated' | 'local_fallback' | 'legacy_unknown';
export type AITokenSource = 'provider_reported' | 'estimated' | 'local_zero';

export interface AssistantStreamCitation {
  event_version?: string;
  stream_id?: string;
  sequence?: number;
  index?: number;
  citation: Record<string, unknown>;
}

export interface AssistantRetrievalTrace {
  request_id?: string | null;
  trace_id?: string | null;
  source?: 'local_rag' | string;
  status?: 'hit' | 'no_match' | 'not_run' | string;
  metadata_candidate_documents?: number;
  candidate_count?: number;
  dedup_document_count?: number;
  final_document_count?: number;
  vector_top_n?: number;
  request?: Record<string, unknown>;
  resolution?: {
    ambiguous?: boolean;
    platform_candidates?: string[];
    evidence?: string;
  };
  runtime?: {
    quality?: {
      no_match?: boolean;
      wrong_vendor_count?: number;
      version_conflict_count?: number;
      low_confidence_count?: number;
      low_confidence_threshold?: number;
      top_relevance_score?: number | null;
      error?: boolean;
    };
  };
}

export interface AssistantStreamMeta {
  event_version?: string;
  request_id?: string;
  stream_id?: string;
  sequence?: number;
  intent?: string;
  citations?: any[];
  facts_retrieved?: boolean;
  retrieval?: AssistantRetrievalTrace;
  copilot?: CopilotContract;
  model_id?: string;
  requested_model_id?: string;
  provider_id?: string;
  input_tokens?: number;
  output_tokens?: number;
  latency_ms?: number;
  route_reason?: string;
  selection_source?: string;
  execution_mode?: AIExecutionMode;
  external_egress?: boolean;
  token_source?: AITokenSource;
}

export interface CopilotContract {
  contract_version?: string;
  intent?: string;
  risk?: string;
  confirmed_facts?: string[];
  assumptions?: string[];
  confidence?: number;
  required_evidence?: string[];
  next_checks?: string[];
  source_labels?: string[];
  recognized?: { vendor?: string; model?: string; os?: string; version?: string; ambiguous_candidates?: string[] };
  runtime?: { device_connected?: boolean; cli_executed?: boolean; external_egress?: boolean; provider_id?: string; model_id?: string; execution_mode?: AIExecutionMode; input_tokens?: number; output_tokens?: number; latency_ms?: number };
  context_budget?: { limit_chars?: number; used_chars?: number; truncated?: boolean; summary?: string };
  engineer_evidence?: { citations?: any[]; trace_available?: boolean };
  developer_trace?: Record<string, unknown>;
}

export interface AssistantStreamError {
  event_version?: string;
  request_id?: string;
  stream_id?: string;
  sequence?: number;
  code?: string;
  message?: string;
  retryable?: boolean;
}

export interface AssistantStreamSession {
  stream_id: string;
  last_event_id: number;
}

export type AIConversationStatus = 'active' | 'archived';

export interface AIConversationSummary {
  id: string;
  tenant_id?: string;
  title: string;
  status: AIConversationStatus;
  context_budget?: number;
  selected_model_id?: string | null;
  model_locked?: boolean;
  created_at: string;
  updated_at: string;
}

export interface AIConversationMessage {
  id: string;
  conversation_id?: string;
  sequence_no?: number;
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  citations?: any[];
  requested_model_id?: string;
  actual_model_id?: string;
  provider_id?: string;
  route_reason?: string;
  fallback_used?: boolean;
  execution_mode?: AIExecutionMode;
  external_egress?: boolean | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  latency_ms?: number | null;
  token_source?: AITokenSource | null;
  created_at: string;
}

export interface AIConversationContext {
  conversation: AIConversationSummary;
  messages: AIConversationMessage[];
}

export interface AIConversationList {
  items: AIConversationSummary[];
  total: number;
  page: number;
  page_size: number;
}

export async function listAIConversations(includeArchived = true, search = '', page = 1, pageSize = 100): Promise<AIConversationList> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (includeArchived) params.set('include_archived', 'true');
  if (search.trim()) params.set('search', search.trim());
  const query = `?${params.toString()}`;
  return apiRequest<AIConversationList>(`/api/v1/ai/conversations${query}`);
}

export async function createAIConversation(title = '新对话'): Promise<AIConversationSummary> {
  return apiRequest<AIConversationSummary>('/api/v1/ai/conversations', {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

export async function getAIConversation(id: string): Promise<AIConversationContext> {
  return apiRequest<AIConversationContext>(`/api/v1/ai/conversations/${encodeURIComponent(id)}`);
}

export async function renameAIConversation(id: string, title: string): Promise<AIConversationSummary> {
  return apiRequest<AIConversationSummary>(`/api/v1/ai/conversations/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify({ title }),
  });
}

export async function archiveAIConversation(id: string, archived: boolean): Promise<AIConversationSummary> {
  return apiRequest<AIConversationSummary>(`/api/v1/ai/conversations/${encodeURIComponent(id)}/archive`, {
    method: 'POST',
    body: JSON.stringify({ archived }),
  });
}

export async function deleteAIConversation(id: string): Promise<void> {
  await apiRequest(`/api/v1/ai/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function clearAIConversation(id: string): Promise<AIConversationSummary> {
  return apiRequest<AIConversationSummary>(`/api/v1/ai/conversations/${encodeURIComponent(id)}/messages`, { method: 'DELETE' });
}

export async function importAIConversationMessages(
  id: string,
  messages: Array<{ role: 'user' | 'assistant'; content: string }>,
): Promise<{ conversation: AIConversationSummary; imported: number; skipped: number }> {
  return apiRequest(`/api/v1/ai/conversations/${encodeURIComponent(id)}/messages/import`, {
    method: 'POST',
    body: JSON.stringify({ messages }),
  });
}

export async function chatAssistant(message: string, history?: Array<{ role: string; content: string }>, modelId?: string): Promise<{ answer: string; intent: string; citations: any[]; retrieval?: AssistantRetrievalTrace; request_id: string }> {
  return apiRequest('/api/ai/assistant/chat', {
    method: 'POST',
    body: JSON.stringify({ message, history, model_id: modelId }),
  });
}

export async function chatAssistantStream(
  message: string,
  history: Array<{ role: string; content: string }> | undefined,
  onToken: (token: string) => void,
  onMeta?: (meta: AssistantStreamMeta) => void,
  onProgress?: (step: AssistantProcessStep) => void,
  onDone?: (meta: AssistantStreamDoneMeta) => void,
  onError?: (error: AssistantStreamError) => void,
  conversationId?: string,
  modelId?: string,
  context?: Record<string, unknown>,
  signal?: AbortSignal,
  onCitation?: (citation: AssistantStreamCitation) => void,
  streamId?: string,
  lastEventId?: number,
  onStreamPosition?: (session: AssistantStreamSession) => void,
): Promise<void> {
  const token = localStorage.getItem('netops_token') || localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Request-ID': createClientRequestId(),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const generatedStreamId = (() => {
    const randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto);
    if (typeof randomUUID === 'function') return `sse_${randomUUID()}`;
    return `sse_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`;
  })();
  const activeRequestStreamId = streamId || generatedStreamId;
  const activeRequestLastEventId = Math.max(0, Number(lastEventId || 0));
  const response = await fetch('/api/ai/assistant/chat-stream', {
    method: 'POST',
    headers,
    signal,
    body: JSON.stringify({
      message,
      history,
      conversation_id: conversationId,
      model_id: modelId,
      context: context || {},
      stream_id: activeRequestStreamId,
      last_event_id: activeRequestLastEventId,
    }),
  });

  if (!response.ok) {
    const errText = await response.text();
    const responseRequestId = response.headers?.get?.('X-Request-ID') || headers['X-Request-ID'];
    throw new Error(`HTTP ${response.status}: ${errText}${responseRequestId ? ` (Request ID: ${responseRequestId})` : ''}`);
  }

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = 'token';
  let pendingEventId: string | null = null;
  let activeStreamId: string | null = streamId || response.headers?.get?.('X-Stream-ID') || null;
  let lastSequence = activeRequestLastEventId;

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
      } else if (trimmed.startsWith('id:')) {
        pendingEventId = trimmed.slice(3).trim();
      } else if (trimmed.startsWith('data:')) {
        const dataStr = trimmed.slice(5).trim();
        if (!dataStr) continue;
        let parsed: any;
        try {
          parsed = JSON.parse(dataStr);
        } catch {
          // Ignore an incomplete or malformed SSE data line.
          continue;
        }

        const parsedStreamId = typeof parsed?.stream_id === 'string'
          ? parsed.stream_id
          : pendingEventId?.includes(':') ? pendingEventId.slice(0, pendingEventId.lastIndexOf(':')) : null;
        const parsedSequence = typeof parsed?.sequence === 'number'
          ? parsed.sequence
          : pendingEventId?.includes(':') ? Number(pendingEventId.slice(pendingEventId.lastIndexOf(':') + 1)) : null;
        pendingEventId = null;
        if (parsedStreamId) {
          if (activeStreamId && parsedStreamId !== activeStreamId) continue;
          activeStreamId = parsedStreamId;
          if (typeof parsedSequence === 'number' && Number.isFinite(parsedSequence)) {
            if (parsedSequence <= lastSequence) continue;
            lastSequence = parsedSequence;
            onStreamPosition?.({ stream_id: activeStreamId, last_event_id: lastSequence });
          }
        }

        if (currentEvent === 'meta' && onMeta) {
          onMeta(parsed);
        } else if (currentEvent === 'progress' && onProgress) {
          onProgress(parsed);
        } else if (currentEvent === 'citation' && onCitation && parsed.citation && typeof parsed.citation === 'object') {
          onCitation(parsed as AssistantStreamCitation);
        } else if (currentEvent === 'done' && onDone) {
          onDone(parsed);
        } else if (currentEvent === 'error') {
          if (onError) {
            onError(parsed);
          } else if (parsed.code) {
            throw new Error(parsed.code);
          }
        } else if (currentEvent === 'token' && parsed.content) {
          onToken(parsed.content);
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
export async function getKnowledgeStats(signal?: AbortSignal): Promise<{ total_documents: number; total_chunks: number; total_vendors: number; ready_indexes: number }> {
  return apiRequest('/api/ai/assistant/knowledge-stats', { signal });
}

export async function submitCopilotFeedback(data: { conversation_id: string; message_id: string; rating: 'positive' | 'negative'; reasons?: string[]; comment?: string }): Promise<{ id: string; rating: string; reasons: string[] }> {
  return apiRequest('/api/ai/assistant/feedback', { method: 'POST', body: JSON.stringify(data) });
}

export async function createCopilotCase(data: { title: string; symptom?: string; conversation_id?: string; context?: Record<string, unknown>; plan?: Array<Record<string, unknown>> }): Promise<any> {
  return apiRequest('/api/ai/assistant/cases', { method: 'POST', body: JSON.stringify(data) });
}

export async function handoffCopilotCase(caseId: string, data: { summary?: string; assignee?: string; ticket_draft?: string }): Promise<any> {
  return apiRequest(`/api/ai/assistant/cases/${encodeURIComponent(caseId)}/handoff`, { method: 'POST', body: JSON.stringify(data) });
}

export async function checkCopilotAttachment(text: string, format = 'txt'): Promise<{ decision: string; classification: string; reason_codes?: string[]; user_message: string }> {
  return apiRequest('/api/ai/security/attachment-check', { method: 'POST', body: JSON.stringify({ text, format }) });
}

export async function createDiagnosticPlan(data: { symptom: string; playbook?: string; vendor?: string; platform?: string; target: string; device_id?: string }): Promise<any> {
  return apiRequest('/api/ai/diagnostics/plan', { method: 'POST', body: JSON.stringify(data) });
}

export async function runDiagnosticPlan(data: { plan: Record<string, unknown>; authorized_steps: number[]; context?: Record<string, unknown> }): Promise<any> {
  return apiRequest('/api/ai/diagnostics/run', { method: 'POST', body: JSON.stringify(data) });
}

export interface RetrievalTestResult {
  contract_version: string;
  normalized_query?: string | null;
  entities: Record<string, unknown>;
  filters: Record<string, unknown>;
  resolution: {
    outcome?: string;
    ambiguous: boolean;
    candidates: Array<Record<string, unknown>>;
    platform_candidates: string[];
    match_method?: string;
    match_score?: number | null;
  };
  final_chunks: Array<{
    chunk_id?: string;
    document_id?: string;
    document_name?: string;
    section?: string;
    platform?: string;
    score?: number;
    score_components?: Record<string, unknown>;
    version_evidence?: string;
    content?: string;
    context_chunk_ids?: string[];
  }>;
  explanation: Record<string, unknown>;
  debug: Record<string, unknown>;
}

export async function runKnowledgeRetrievalTest(query: string, filters: Record<string, unknown> = {}, topK = 5): Promise<RetrievalTestResult> {
  return apiRequest<RetrievalTestResult>('/api/ai/assistant/knowledge-retrieval-test', {
    method: 'POST',
    body: JSON.stringify({ query, filters, top_k: topK }),
  });
}

export interface KnowledgeEvaluationGate {
  metric: string;
  actual: number;
  operator: '>=' | '<=' | string;
  threshold: number;
  passed: boolean;
}

export interface KnowledgeEvaluationCase {
  id: string;
  query: string;
  retrieval_correct: boolean;
  citation_precision: number;
  vendor_mismatch: boolean;
  version_conflict: boolean;
  latency_ms: number;
}

export interface KnowledgeEvaluationReport {
  contract_version: string;
  suite: string;
  status: 'not_run' | 'passed' | 'failed' | string;
  tenant_id: string;
  baseline_id: string;
  system_under_test: string;
  database: 'PostgreSQL' | string;
  execution_mode: string;
  production_database_write: boolean;
  external_network_call: boolean;
  rollback: string;
  case_count: number;
  dataset?: { baseline_id: string; case_count: number; domains: string[]; database: string };
  metrics: {
    retrieval_accuracy: number;
    wrong_vendor_rate: number;
    version_conflict_rate: number;
    citation_accuracy: number;
    citation_recall: number;
    latency_ms: { average: number; p50: number; p95: number; max: number };
  } | null;
  gates: KnowledgeEvaluationGate[];
  cases: KnowledgeEvaluationCase[];
  thresholds?: Record<string, { operator: string; threshold: number }>;
  started_at?: string;
  duration_ms?: number;
  last_run?: unknown;
}

export async function getKnowledgeEvaluation(includeCases = true): Promise<KnowledgeEvaluationReport> {
  const payload = await apiRequest<KnowledgeSourceEnvelope<KnowledgeEvaluationReport>>(`/api/v2/kb/evaluation?include_cases=${includeCases ? 'true' : 'false'}`);
  return payload.data;
}

export async function runKnowledgeEvaluation(suite = 'v1_baseline_postgresql'): Promise<KnowledgeEvaluationReport> {
  const payload = await apiRequest<KnowledgeSourceEnvelope<KnowledgeEvaluationReport>>('/api/v2/kb/evaluation/run', {
    method: 'POST',
    body: JSON.stringify({ suite }),
  });
  return payload.data;
}

export interface KnowledgeRetrievalTrace {
  trace_id: string;
  request_id?: string | null;
  tenant_id: string;
  actor_hash?: string | null;
  query_hash: string;
  created_at: string;
  source: string;
  status: 'hit' | 'no_match' | 'not_run' | string;
  metadata_candidate_documents: number;
  candidate_count: number;
  dedup_document_count: number;
  final_document_count: number;
  vector_top_n: number;
  clarification_required: boolean;
  cross_platform_search: boolean;
  request: Record<string, string>;
  resolution: { ambiguous: boolean; platform_candidates: string[]; evidence: string };
  citations: Array<{
    citation_id: string;
    vendor: string;
    product: string;
    software_version: string;
    source_type: string;
    status: string;
    trust: string;
    validation: string;
    warning_count: number;
  }>;
  citation_warning_count: number;
  redaction: {
    default: boolean;
    raw_query_included: false;
    raw_chunk_included: false;
    raw_sql_included: false;
    credentials_included: false;
  };
}

interface KnowledgeRetrievalTraceEnvelope<T> { success: boolean; data: T; message?: string }

export async function listKnowledgeRetrievalTraces(status = 'all', limit = 50): Promise<{ items: KnowledgeRetrievalTrace[]; limit: number; status: string; redacted: boolean }> {
  const payload = await apiRequest<KnowledgeRetrievalTraceEnvelope<{ items: KnowledgeRetrievalTrace[]; limit: number; status: string; redacted: boolean }>>(`/api/v2/kb/retrieval-traces?status=${encodeURIComponent(status)}&limit=${limit}`);
  return payload.data;
}

export async function getKnowledgeRetrievalTrace(traceId: string): Promise<KnowledgeRetrievalTrace> {
  const payload = await apiRequest<KnowledgeRetrievalTraceEnvelope<KnowledgeRetrievalTrace>>(`/api/v2/kb/retrieval-traces/${encodeURIComponent(traceId)}`);
  return payload.data;
}

export interface KnowledgeCatalogModel {
  product_model_id: string;
  tenant_id: string;
  vendor_id: string;
  vendor_name: string;
  family_code: string;
  family_name: string;
  series_code: string;
  series_name: string;
  model_code: string;
  display_name: string;
  status: string;
  review_status: string;
  source_refs: string[];
  software_scope: Record<string, unknown>;
  platform_binding_advisory: Record<string, unknown>;
  source_artifact: string;
}

export interface KnowledgeCatalogResponse {
  persistence_status: string;
  tenant_id: string;
  items: KnowledgeCatalogModel[];
  total: number;
  read_only: boolean;
  source_artifacts: string[];
  facets?: {
    vendors: string[];
    families: string[];
    series: string[];
    software_versions: string[];
  };
  meta?: { pagination: { page: number; page_size: number; total: number; total_pages: number; sort_by: string; sort_order: string }; filters: Record<string, unknown> };
}

export interface KnowledgeCatalogAlias {
  id: string;
  tenant_id: string;
  product_model_id: string;
  alias: string;
  normalized_alias: string;
  alias_kind: 'exact' | 'canonical' | 'prefix' | 'trigram' | string;
  seed_status: string;
  expected_outcome: string;
  conflict_status: string;
  conflict_group: string;
  conflict_reason: string;
  conflict_count: number;
  model?: KnowledgeCatalogModel;
}

export interface KnowledgeCatalogAliasesResponse {
  persistence_status: string;
  tenant_id: string;
  items: KnowledgeCatalogAlias[];
  conflicts: Array<Record<string, unknown>>;
  total: number;
  read_only: boolean;
  source_artifact: string;
  meta?: { pagination: { page: number; page_size: number; total: number; total_pages: number; sort_by: string; sort_order: string }; filters: Record<string, unknown> };
}

export interface KnowledgeCatalogResolveResponse {
  outcome: 'unique' | 'ambiguous' | 'candidates' | 'unknown' | string;
  query: string;
  normalized_query: string;
  candidates: Array<Record<string, unknown> & { model?: KnowledgeCatalogModel }>;
  candidate_count: number;
  conflict_groups: string[];
  requires_clarification: boolean;
  selection_allowed: boolean;
  manual_review_required: boolean;
  persistence_status: string;
  tenant_id: string;
  dry_run: boolean;
  read_only: boolean;
  driver_selection_allowed: boolean;
}

type KnowledgeCatalogApiEnvelope<T> = {
  success: boolean;
  data: T;
  message?: string;
};

/**
 * Knowledge Engine V2 endpoints use the standard `{ success, data, message }`
 * API envelope. Keep the client tolerant of the direct payload shape as well
 * so a gateway/proxy cannot turn a valid empty catalog into a render crash.
 */
function unwrapKnowledgeCatalogPayload<T>(payload: T | KnowledgeCatalogApiEnvelope<T>): T {
  if (payload && typeof payload === 'object' && 'success' in payload && 'data' in payload) {
    return (payload as KnowledgeCatalogApiEnvelope<T>).data;
  }
  return payload as T;
}

export async function getKnowledgeCatalog(filters: { search?: string; vendor_id?: string; family_code?: string; series_code?: string; model?: string; software_version?: string; status?: string; page?: number; page_size?: number; sort_by?: string; sort_order?: string } = {}): Promise<KnowledgeCatalogResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (typeof value === 'number') params.set(key, String(value));
    else if (value?.trim()) params.set(key, value.trim());
  });
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const payload = await apiRequest<KnowledgeCatalogResponse | KnowledgeCatalogApiEnvelope<KnowledgeCatalogResponse>>(`/api/v2/kb/catalog${suffix}`);
  return unwrapKnowledgeCatalogPayload(payload);
}

export async function getKnowledgeCatalogAliases(filters: { alias?: string; alias_kind?: string; conflict_status?: string; page?: number; page_size?: number; sort_by?: string; sort_order?: string } = {}): Promise<KnowledgeCatalogAliasesResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (typeof value === 'number') params.set(key, String(value));
    else if (value?.trim()) params.set(key, value.trim());
  });
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const payload = await apiRequest<KnowledgeCatalogAliasesResponse | KnowledgeCatalogApiEnvelope<KnowledgeCatalogAliasesResponse>>(`/api/v2/kb/catalog/aliases${suffix}`);
  return unwrapKnowledgeCatalogPayload(payload);
}

export async function resolveKnowledgeCatalogAlias(query: string, limit = 20): Promise<KnowledgeCatalogResolveResponse> {
  const payload = await apiRequest<KnowledgeCatalogResolveResponse | KnowledgeCatalogApiEnvelope<KnowledgeCatalogResolveResponse>>('/api/v2/kb/catalog/resolve', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
  });
  return unwrapKnowledgeCatalogPayload(payload);
}

export interface KnowledgeAssetPlatformOption {
  value: string;
  label: string;
  asset_count: number;
}

export interface KnowledgeAssetVendorOption {
  value: string;
  label: string;
  platforms: KnowledgeAssetPlatformOption[];
}

export interface KnowledgeAssetOptionsResponse {
  source: string;
  asset_count: number;
  vendors: KnowledgeAssetVendorOption[];
}

export async function getKnowledgeAssetOptions(): Promise<KnowledgeAssetOptionsResponse> {
  return apiRequest('/api/ai/assistant/knowledge-options');
}

export interface KnowledgeDirectoryNode {
  id: string;
  knowledge_base_id: string;
  tenant_id: string;
  parent_id?: string | null;
  name: string;
  path: string;
  depth: number;
  is_system: boolean;
  sort_order: number;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  children: KnowledgeDirectoryNode[];
}

export interface KnowledgeDirectoriesResponse {
  items: KnowledgeDirectoryNode[];
  total: number;
}

export async function getKnowledgeDirectories(): Promise<KnowledgeDirectoriesResponse> {
  return apiRequest('/api/ai/assistant/knowledge-directories');
}

export async function createKnowledgeDirectory(data: { name: string; parent_id?: string | null }): Promise<KnowledgeDirectoryNode> {
  return apiRequest('/api/ai/assistant/knowledge-directories', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function renameKnowledgeDirectory(directoryId: string, name: string): Promise<KnowledgeDirectoryNode> {
  return apiRequest(`/api/ai/assistant/knowledge-directories/${encodeURIComponent(directoryId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  });
}

export async function deleteKnowledgeDirectory(directoryId: string): Promise<{ deleted_count: number; directory_id: string }> {
  return apiRequest(`/api/ai/assistant/knowledge-directories/${encodeURIComponent(directoryId)}`, {
    method: 'DELETE',
  });
}

export interface KnowledgeDocument {
  id: string;
  knowledge_base_id: string;
  name: string;
  source?: string;
  vendor: string;
  platform?: string | null;
  cli_platform?: string | null;
  document_id?: string | null;
  document_category?: string | null;
  product_family?: string | null;
  product_series?: string | null;
  product_model?: string | null;
  os_family?: string | null;
  os_generation?: string | null;
  software_train?: string | null;
  software_release?: string | null;
  feature_domain?: string | null;
  feature?: string | null;
  subfeature?: string | null;
  risk_level?: string | null;
  verification_level?: string | null;
  rag_priority?: number | null;
  metadata_parse_status?: string | null;
  exclude_from_rag?: boolean;
  status: string;
  knowledge_source_type: string;
  tenant_id?: string;
  acl?: Record<string, unknown>;
  source_trust_level?: string;
  created_at: string;
  chunk_count: number;
}

export interface KnowledgeDocumentChunk {
  id: string;
  page: number;
  section: string;
  content: string;
  created_at?: string;
  parent_chunk_id?: string | null;
  parent_chunk?: KnowledgeDocumentChunkContext | null;
  neighbors?: KnowledgeDocumentChunkContext[];
  chunk_role?: string | null;
  chunk_type?: string | null;
  ordinal?: number;
  metadata?: Record<string, unknown>;
  heading_path?: unknown[];
  token_count?: number;
  content_hash?: string | null;
  source_locator?: Record<string, unknown>;
  chunking_version?: string | null;
  document_version?: string | null;
  index_version?: string | null;
  parser_version?: string | null;
  is_retrieval_candidate?: boolean;
}

export interface KnowledgeDocumentChunkContext {
  id: string;
  page?: number;
  section?: string;
  ordinal?: number;
  chunk_role?: string | null;
  content?: string;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  updated_at?: string;
  document_id?: string | null;
  original_content?: string;
  normalized_content?: string;
  metadata?: Record<string, unknown>;
  document_version?: string | null;
  index_version?: string | null;
  parser_version?: string | null;
  raw_source?: {
    source?: string | null;
    references?: Array<Record<string, unknown>>;
  };
  source_version_history?: Array<{
    id: string;
    version_no: number;
    source_version_id?: string | null;
    content_hash?: string | null;
    status?: string | null;
    lifecycle_status?: string | null;
    mime_type?: string | null;
    byte_size?: number;
    created_at?: string | null;
    updated_at?: string | null;
  }>;
  chunks: KnowledgeDocumentChunk[];
}

export interface KnowledgeDocumentVersion {
  id: string;
  version_no: number;
  source_version_id?: string | null;
  content_hash?: string | null;
  metadata_hash?: string | null;
  normalized_content_hash?: string | null;
  status?: string | null;
  lifecycle_status?: string | null;
  mime_type?: string | null;
  byte_size?: number;
  parser_name?: string | null;
  parser_version?: string | null;
  trust_level?: string | null;
  metadata_keys?: string[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface KnowledgeDocumentVersionComparison {
  document_id: string;
  left: KnowledgeDocumentVersion;
  right: KnowledgeDocumentVersion;
  changed_fields: string[];
  content_changed: boolean;
  metadata_changed: boolean;
  line_diff: {
    available: boolean;
    left_lines: number;
    right_lines: number;
    added_lines: number;
    removed_lines: number;
  };
  raw_content_included: false;
}

export interface KnowledgeSourceRegistry {
  id: string;
  tenant_id: string;
  source_type: string;
  source_kind: string;
  name: string;
  description?: string;
  canonical_url: string;
  allowed_host: string;
  trust_level: string;
  status: string;
  fetch_enabled: boolean;
  validation_status: string;
  validation?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  updated_at?: string;
  created_at?: string;
}

export interface KnowledgeSourceRefreshObservation {
  id: string;
  source_registry_id: string;
  source_version_id?: string | null;
  checked_at?: string;
  outcome: string;
  detection_type?: string;
  content_hash?: string;
  byte_size?: number;
  http_status?: number | null;
  error_code?: string;
  metadata?: Record<string, unknown>;
  version_signal?: Record<string, unknown>;
}

export interface KnowledgeSourceRefreshStatus {
  source_id: string;
  tenant_id: string;
  registry_status: string;
  validation_status: string;
  fetch_enabled: boolean;
  freshness_status: 'healthy' | 'failed' | 'attention' | 'never_checked' | 'not_configured' | string;
  last_checked_at?: string | null;
  last_outcome?: string | null;
  last_detection_type?: string;
  last_error_code?: string;
  last_content_hash?: string;
  last_source_version_id?: string;
  last_http_status?: number | null;
  observation_count: number;
  counts: Record<string, number>;
  latest_version?: { id: string; content_hash: string; byte_size: number; fetched_at?: string; status?: string } | null;
  error_code?: string;
}

export interface OfficialSourceSuggestion {
  id: string;
  trace_id: string;
  request_id?: string | null;
  vendor: string;
  product_model?: string | null;
  software_release?: string | null;
  feature?: string | null;
  label: string;
  suggested_url: string;
  reviewed_url?: string | null;
  source_kind: string;
  status: 'pending' | 'approved' | 'collecting' | 'imported' | 'failed' | 'rejected' | string;
  recheck_trace_id?: string | null;
  recheck_status?: string | null;
  error_code?: string | null;
  created_at: string;
  updated_at: string;
}

interface KnowledgeSourceEnvelope<T> {
  success: boolean;
  data: T;
  message?: string;
  meta?: {
    pagination?: { page: number; page_size: number; total: number; total_pages: number; sort_by?: string; sort_order?: string };
  };
}

export interface KnowledgeSourcePage {
  items: KnowledgeSourceRegistry[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export async function listKnowledgeSources(status = 'all', page = 1, pageSize = 20): Promise<KnowledgeSourcePage> {
  const params = new URLSearchParams({ status, page: String(page), page_size: String(pageSize) });
  const payload = await apiRequest<KnowledgeSourceEnvelope<KnowledgeSourceRegistry[]>>(`/api/v2/kb/sources?${params.toString()}`);
  const pagination = payload.meta?.pagination;
  const items = payload.data || [];
  return {
    items,
    page: pagination?.page || page,
    page_size: pagination?.page_size || pageSize,
    total: pagination?.total ?? items.length,
    total_pages: pagination?.total_pages || 1,
  };
}

export async function getKnowledgeSourceRefreshStatus(sourceId: string): Promise<KnowledgeSourceRefreshStatus> {
  const payload = await apiRequest<KnowledgeSourceEnvelope<KnowledgeSourceRefreshStatus>>(`/api/v2/kb/sources/${encodeURIComponent(sourceId)}/refresh-status`);
  return payload.data;
}

export async function listKnowledgeSourceRefreshObservations(sourceId: string, limit = 50): Promise<KnowledgeSourceRefreshObservation[]> {
  const payload = await apiRequest<KnowledgeSourceEnvelope<KnowledgeSourceRefreshObservation[]>>(`/api/v2/kb/sources/${encodeURIComponent(sourceId)}/refresh-observations?limit=${limit}`);
  return payload.data || [];
}

export async function validateKnowledgeSource(sourceId: string): Promise<Record<string, unknown>> {
  const payload = await apiRequest<KnowledgeSourceEnvelope<Record<string, unknown>>>(`/api/v2/kb/sources/${encodeURIComponent(sourceId)}/validate`, { method: 'POST' });
  return payload.data;
}

export async function refreshKnowledgeSource(sourceId: string): Promise<Record<string, unknown>> {
  const payload = await apiRequest<KnowledgeSourceEnvelope<Record<string, unknown>>>(`/api/v2/kb/sources/${encodeURIComponent(sourceId)}/fetch`, { method: 'POST', body: JSON.stringify({ method: 'GET' }) });
  return payload.data;
}

export async function listOfficialSourceSuggestions(status = 'pending', search = ''): Promise<{
  items: OfficialSourceSuggestion[]; total: number; page: number; page_size: number; total_pages: number;
}> {
  const params = new URLSearchParams({ status, search, page: '1', page_size: '100' });
  const payload = await apiRequest<KnowledgeSourceEnvelope<{ items: OfficialSourceSuggestion[]; total: number; page: number; page_size: number; total_pages: number }>>(`/api/v2/kb/ingestion/official-source-suggestions?${params.toString()}`);
  return payload.data;
}

export async function reviewOfficialSourceSuggestion(suggestionId: string, fields: {
  decision: 'approve' | 'reject'; vendor?: string; product_model?: string; software_release?: string;
  feature?: string; url?: string; source_kind?: string;
}): Promise<OfficialSourceSuggestion> {
  const payload = await apiRequest<KnowledgeSourceEnvelope<OfficialSourceSuggestion>>(`/api/v2/kb/ingestion/official-source-suggestions/${encodeURIComponent(suggestionId)}/review`, {
    method: 'POST', body: JSON.stringify(fields),
  });
  return payload.data;
}

export interface KnowledgeDocumentsResponse {
  items: KnowledgeDocument[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface KnowledgeDocumentFacet {
  value: string;
  count: number;
}

export interface KnowledgeDocumentFacets {
  vendors: KnowledgeDocumentFacet[];
  families: KnowledgeDocumentFacet[];
  series: KnowledgeDocumentFacet[];
}

export interface KnowledgeDocumentsQuery {
  sourceType?: string;
  knowledgeScope?: 'all' | 'official' | 'enterprise';
  search?: string;
  directoryPath?: string;
  vendor?: string;
  productFamily?: string;
  productSeries?: string;
  productModel?: string;
  osFamily?: string;
  osGeneration?: string;
  softwareTrain?: string;
  softwareRelease?: string;
  cliPlatform?: string;
  documentCategory?: string;
  featureDomain?: string;
  status?: string;
  sourceTrustLevel?: string;
  page?: number;
  pageSize?: number;
  signal?: AbortSignal;
}

const KNOWLEDGE_DOCUMENT_CATEGORY_ALIASES: Record<string, string> = {
  '01_product': 'hardware',
  '02_commands': 'command',
  '03_configuration': 'configuration',
  '04_cli_outputs': 'cli_output',
  '05_troubleshooting': 'troubleshooting',
  '06_examples': 'example',
};

function canonicalKnowledgeDocumentCategory(value?: string): string | undefined {
  const normalized = value?.trim().toLowerCase().replace(/-/g, '_');
  return normalized ? (KNOWLEDGE_DOCUMENT_CATEGORY_ALIASES[normalized] || normalized) : undefined;
}

export async function getKnowledgeDocuments({
  sourceType,
  knowledgeScope,
  search,
  directoryPath,
  vendor,
  productFamily,
  productSeries,
  productModel,
  osFamily,
  osGeneration,
  softwareTrain,
  softwareRelease,
  cliPlatform,
  documentCategory,
  featureDomain,
  status,
  sourceTrustLevel,
  page = 1,
  pageSize = 20,
  signal,
}: KnowledgeDocumentsQuery = {}): Promise<KnowledgeDocumentsResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (sourceType) params.set('source_type', sourceType);
  if (knowledgeScope && knowledgeScope !== 'all') params.set('knowledge_scope', knowledgeScope);
  if (search?.trim()) params.set('search', search.trim());
  if (directoryPath?.trim()) params.set('directory_path', directoryPath.trim());
  const filterParams: Array<[string, string | undefined]> = [
    ['vendor', vendor],
    ['product_family', productFamily],
    ['product_series', productSeries],
    ['product_model', productModel],
    ['os_family', osFamily],
    ['os_generation', osGeneration],
    ['software_train', softwareTrain],
    ['software_release', softwareRelease],
    ['cli_platform', cliPlatform],
    ['document_category', canonicalKnowledgeDocumentCategory(documentCategory)],
    ['feature_domain', featureDomain],
    ['status', status],
    ['source_trust_level', sourceTrustLevel],
  ];
  filterParams.forEach(([key, value]) => {
    if (value?.trim()) params.set(key, value.trim());
  });
  return apiRequest(`/api/ai/assistant/documents?${params.toString()}`, { signal });
}

export async function exportKnowledgeDocuments(query: Omit<KnowledgeDocumentsQuery, 'page' | 'pageSize' | 'signal'> = {}): Promise<{ blob: Blob; filename: string; documentCount: number; contentBytes: number }> {
  const params = new URLSearchParams();
  if (query.sourceType) params.set('source_type', query.sourceType);
  if (query.knowledgeScope && query.knowledgeScope !== 'all') params.set('knowledge_scope', query.knowledgeScope);
  if (query.search?.trim()) params.set('search', query.search.trim());
  if (query.directoryPath?.trim()) params.set('directory_path', query.directoryPath.trim());
  const filterParams: Array<[string, string | undefined]> = [
    ['vendor', query.vendor],
    ['product_family', query.productFamily],
    ['product_series', query.productSeries],
    ['product_model', query.productModel],
    ['os_family', query.osFamily],
    ['os_generation', query.osGeneration],
    ['software_train', query.softwareTrain],
    ['software_release', query.softwareRelease],
    ['cli_platform', query.cliPlatform],
    ['document_category', canonicalKnowledgeDocumentCategory(query.documentCategory)],
    ['feature_domain', query.featureDomain],
    ['status', query.status],
    ['source_trust_level', query.sourceTrustLevel],
  ];
  filterParams.forEach(([key, value]) => {
    if (value?.trim()) params.set(key, value.trim());
  });
  const response = await fetch(`/api/ai/assistant/knowledge-export?${params.toString()}`, {
    headers: authHeaders(false),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload?.detail;
    const message = typeof detail === 'string' ? detail : detail?.message || payload?.message || `HTTP ${response.status}`;
    throw new Error(message);
  }
  const disposition = response.headers.get('Content-Disposition') || '';
  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return {
    blob: await response.blob(),
    filename: filenameMatch?.[1] || 'nexora-knowledge-export.zip',
    documentCount: Number(response.headers.get('X-Knowledge-Export-Documents') || 0),
    contentBytes: Number(response.headers.get('X-Knowledge-Export-Content-Bytes') || 0),
  };
}

export async function importKnowledgeBundle(file: File): Promise<{ success: boolean; data: { document_count: number; atomic: boolean; official_claims?: string } }> {
  const form = new FormData();
  form.append('file', file);
  return apiRequest('/api/ai/assistant/documents/import-bundle', {
    method: 'POST',
    body: form,
  });
}

export async function getKnowledgeDocumentFacets({
  sourceType,
  knowledgeScope,
  directoryPath,
  status = 'active',
  signal,
}: {
  sourceType?: string;
  knowledgeScope?: 'all' | 'official' | 'enterprise';
  directoryPath?: string;
  status?: string;
  signal?: AbortSignal;
} = {}): Promise<KnowledgeDocumentFacets> {
  const params = new URLSearchParams();
  if (sourceType) params.set('source_type', sourceType);
  if (knowledgeScope && knowledgeScope !== 'all') params.set('knowledge_scope', knowledgeScope);
  if (directoryPath?.trim()) params.set('directory_path', directoryPath.trim());
  if (status) params.set('status', status);
  return apiRequest<KnowledgeDocumentFacets>(`/api/ai/assistant/documents/facets?${params.toString()}`, { signal });
}

export async function getKnowledgeDocument(docId: string): Promise<KnowledgeDocumentDetail> {
  return apiRequest<KnowledgeDocumentDetail>(`/api/ai/assistant/documents/${encodeURIComponent(docId)}`);
}

export async function listKnowledgeDocumentVersions(docId: string): Promise<KnowledgeDocumentVersion[]> {
  return apiRequest<KnowledgeDocumentVersion[]>(`/api/v2/kb/documents/${encodeURIComponent(docId)}/versions`);
}

export async function compareKnowledgeDocumentVersions(docId: string, leftVersionId: string, rightVersionId: string): Promise<KnowledgeDocumentVersionComparison> {
  const params = new URLSearchParams({ left_version_id: leftVersionId, right_version_id: rightVersionId });
  return apiRequest<KnowledgeDocumentVersionComparison>(`/api/v2/kb/documents/${encodeURIComponent(docId)}/versions/compare?${params.toString()}`);
}

export async function publishKnowledgeDocumentVersion(docId: string, versionId: string, reason = 'published by knowledge administrator'): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v2/kb/documents/${encodeURIComponent(docId)}/versions/${encodeURIComponent(versionId)}/publish`, { method: 'POST', body: JSON.stringify({ confirm: true, reason }) });
}

export async function supersedeKnowledgeDocumentVersion(docId: string, versionId: string, replacementVersionId: string, reason = 'superseded by knowledge administrator'): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v2/kb/documents/${encodeURIComponent(docId)}/versions/${encodeURIComponent(versionId)}/supersede`, { method: 'POST', body: JSON.stringify({ confirm: true, replacement_version_id: replacementVersionId, reason }) });
}

export async function rollbackKnowledgeDocumentVersion(docId: string, versionId: string, reason = 'rollback by knowledge administrator'): Promise<Record<string, unknown>> {
  return apiRequest(`/api/v2/kb/documents/${encodeURIComponent(docId)}/versions/${encodeURIComponent(versionId)}/rollback`, { method: 'POST', body: JSON.stringify({ confirm: true, reason }) });
}

export interface KnowledgeOfficialUrlImportPayload {
  url: string;
  source_kind: string;
  vendor: string;
  product_family: string;
  version_scope: Record<string, string>;
  terms_review_status: string;
  publish_to_knowledge_base?: boolean;
  reviewer?: string;
  name?: string;
  description?: string;
  idempotency_key?: string;
}

export interface KnowledgeMetadataPreviewRequest {
  name: string;
  content: string;
  vendor?: string;
  platform?: string | null;
  knowledge_source_type?: string;
  source_trust_level?: string;
  chunk_size?: number;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeMetadataPreview {
  preview_id: string;
  confirmation_token: string;
  expires_at: number;
  metadata_parse_status: string;
  normalized: {
    name: string;
    vendor: string;
    platform: string | null;
    knowledge_source_type: string;
    source_trust_level: string;
    chunk_size: number;
    metadata_parse_status: string;
    format: string;
    parser_name: string;
    parser_version: string;
    parse_warnings: string[];
    metadata: Record<string, unknown>;
    metadata_columns: Record<string, unknown>;
    content_sha256: string;
    content_bytes: number;
    body_characters: number;
  };
  warnings: string[];
  requires_confirmation: true;
}

export type KnowledgeIngestionExecutionState = 'all' | 'queued' | 'running' | 'retry_wait' | 'paused' | 'cancel_requested' | 'cancelled' | 'succeeded' | 'failed';

export interface KnowledgeIngestionJobSummary {
  id: string;
  job_kind: string;
  status?: string;
  lifecycle_status?: string;
  execution_state: string;
  phase: string;
  phase_started_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  retry_of_job_id?: string | null;
  total_count: number;
  processed_count: number;
  parsed_count: number;
  failed_count: number;
  succeeded_count: number;
  skipped_count: number;
  retryable_failed_count: number;
  error_count: number;
  progress_percent: number;
  retry_count: number;
  max_retries: number;
  attempt_no: number;
  next_retry_at?: string | null;
  last_error_code?: string | null;
  last_error_at?: string | null;
  cancel_requested_at?: string | null;
  cancelled_at?: string | null;
  lease_held?: boolean;
}

export interface KnowledgeIngestionJobsResponse {
  items: KnowledgeIngestionJobSummary[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface KnowledgeIngestionJobsQuery {
  executionState?: Exclude<KnowledgeIngestionExecutionState, 'all'> | '';
  phase?: string;
  jobKind?: string;
  search?: string;
  page?: number;
  pageSize?: number;
  signal?: AbortSignal;
}

export interface KnowledgeIngestionJobErrors {
  job_id: string;
  phase: string;
  execution_state: string;
  last_error_code?: string | null;
  last_error_at?: string | null;
  error_count: number;
  errors: Array<{
    code?: string;
    safe_message?: string;
    message?: string;
    phase?: string;
    attempt_no?: number;
    retryable?: boolean;
    occurred_at?: string;
    correlation_id?: string;
  }>;
}

export async function listKnowledgeIngestionJobs({
  executionState,
  phase,
  jobKind,
  search,
  page = 1,
  pageSize = 20,
  signal,
}: KnowledgeIngestionJobsQuery = {}): Promise<KnowledgeIngestionJobsResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (executionState) params.set('execution_state', executionState);
  if (phase?.trim()) params.set('phase', phase.trim());
  if (jobKind?.trim()) params.set('job_kind', jobKind.trim());
  if (search?.trim()) params.set('search', search.trim());
  const payload = await apiRequest<{
    items?: KnowledgeIngestionJobSummary[];
    data?: KnowledgeIngestionJobSummary[];
    total?: number;
    count?: number;
    page?: number;
    page_size?: number;
    total_pages?: number;
  }>(`/api/v2/kb/ingestion/jobs?${params.toString()}`, { signal });
  const total = Number(payload.total ?? payload.count ?? 0);
  const resolvedPageSize = Number(payload.page_size ?? pageSize);
  return {
    items: payload.items ?? payload.data ?? [],
    total,
    page: Number(payload.page ?? page),
    page_size: resolvedPageSize,
    total_pages: Number(payload.total_pages ?? Math.max(1, Math.ceil(total / resolvedPageSize))),
  };
}

export async function getKnowledgeIngestionJobErrors(jobId: string, signal?: AbortSignal): Promise<KnowledgeIngestionJobErrors> {
  const payload = await apiRequest<{ data: KnowledgeIngestionJobErrors }>(`/api/v2/kb/ingestion/jobs/${encodeURIComponent(jobId)}/errors`, { signal });
  return payload.data;
}

export async function retryKnowledgeIngestionJob(jobId: string, requestId = ''): Promise<KnowledgeIngestionJobSummary> {
  const payload = await apiRequest<{ data: KnowledgeIngestionJobSummary }>(`/api/v2/kb/ingestion/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
    body: JSON.stringify(requestId ? { request_id: requestId } : {}),
  });
  return payload.data;
}

export async function importKnowledgeOfficialUrl(payload: KnowledgeOfficialUrlImportPayload): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>('/api/v2/kb/ingestion/official-url', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function previewKnowledgeDocumentMetadata(payload: KnowledgeMetadataPreviewRequest): Promise<KnowledgeMetadataPreview> {
  const response = await apiRequest<{ data: KnowledgeMetadataPreview }>('/api/ai/assistant/documents/metadata-preview', {
    method: 'POST',
    body: JSON.stringify({
      name: payload.name,
      content: payload.content,
      vendor: payload.vendor ?? 'all',
      platform: payload.platform ?? null,
      knowledge_source_type: payload.knowledge_source_type ?? 'user_document',
      source_trust_level: payload.source_trust_level ?? 'internal',
      chunk_size: payload.chunk_size ?? 800,
      metadata: payload.metadata ?? {},
    }),
  });
  return response.data;
}

export async function importKnowledgeEnterpriseSop(file: File, fields: {
  title: string;
  owner: string;
  department: string;
  description?: string;
}): Promise<Record<string, unknown>> {
  const form = new FormData();
  form.append('file', file);
  form.append('title', fields.title);
  form.append('owner', fields.owner);
  form.append('department', fields.department);
  form.append('classification', 'INTERNAL');
  if (fields.description) form.append('description', fields.description);
  return apiRequest<Record<string, unknown>>('/api/v2/kb/ingestion/enterprise-sop', {
    method: 'POST',
    body: form,
  });
}

export interface KnowledgeEnterpriseSopBatchItem {
  filename: string;
  status: 'queued' | 'succeeded' | 'failed';
  success: boolean;
  job?: KnowledgeIngestionJobSummary | null;
  error?: { code?: string; message?: string } | null;
}

export async function importKnowledgeEnterpriseSopBatch(files: File[]): Promise<{
  success: boolean;
  data: { strategy: 'file_level_commit'; total: number; accepted: number; failed: number; items: KnowledgeEnterpriseSopBatchItem[] };
}> {
  const form = new FormData();
  files.forEach((file) => form.append('files', file));
  form.append('classification', 'INTERNAL');
  return apiRequest('/api/v2/kb/ingestion/enterprise-sop/batch', { method: 'POST', body: form });
}

export async function addKnowledgeDocument(data: {
  name: string;
  content: string;
  vendor: string;
  platform?: string | null;
  knowledge_source_type?: string;
  metadata?: Record<string, unknown>;
  metadata_confirmation_token?: string;
  metadata_confirmed?: boolean;
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

export type KnowledgeDocumentAction = 'delete' | 'disable' | 'enable' | 'reparse' | 'rechunk' | 'reindex';

export interface KnowledgeDocumentActionResult {
  action_id: string;
  action: KnowledgeDocumentAction;
  document_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  job_id?: string;
  idempotent?: boolean;
  previous_status?: string;
  current_status?: string;
  impact: { documents: number; chunks: number; indexes: number; references: number; reference_details?: Array<{ type: string; count: number }>; reference_scope?: string };
  recovery: { recovery: string };
  job?: Record<string, unknown>;
}

export interface KnowledgeDocumentActionImpact {
  document_id: string;
  name: string;
  current_status: string;
  impact: KnowledgeDocumentActionResult['impact'];
  recovery: Record<string, string>;
  safe_to_confirm: boolean;
}

export async function getKnowledgeDocumentActionImpact(docId: string): Promise<KnowledgeDocumentActionImpact> {
  return apiRequest<KnowledgeDocumentActionImpact>(`/api/ai/assistant/documents/${encodeURIComponent(docId)}/actions/impact`);
}

export async function runKnowledgeDocumentAction(docId: string, action: KnowledgeDocumentAction, data: { confirm: boolean; reason?: string }): Promise<KnowledgeDocumentActionResult> {
  return apiRequest<KnowledgeDocumentActionResult>(`/api/ai/assistant/documents/${encodeURIComponent(docId)}/actions/${action}`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function deleteKnowledgeDocument(docId: string, reason = 'confirmed by knowledge administrator'): Promise<KnowledgeDocumentActionResult> {
  return runKnowledgeDocumentAction(docId, 'delete', { confirm: true, reason });
}

export async function disableKnowledgeDocument(docId: string, reason = 'confirmed by knowledge administrator'): Promise<KnowledgeDocumentActionResult> {
  return runKnowledgeDocumentAction(docId, 'disable', { confirm: true, reason });
}

export async function reparseKnowledgeDocument(docId: string, reason = 'confirmed by knowledge administrator'): Promise<KnowledgeDocumentActionResult> {
  return runKnowledgeDocumentAction(docId, 'reparse', { confirm: true, reason });
}

export async function rechunkKnowledgeDocument(docId: string, reason = 'confirmed by knowledge administrator'): Promise<KnowledgeDocumentActionResult> {
  return runKnowledgeDocumentAction(docId, 'rechunk', { confirm: true, reason });
}

export async function reindexKnowledgeDocument(docId: string, reason = 'confirmed by knowledge administrator'): Promise<KnowledgeDocumentActionResult> {
  return runKnowledgeDocumentAction(docId, 'reindex', { confirm: true, reason });
}

export async function enableKnowledgeDocument(docId: string, reason = 'confirmed by knowledge administrator'): Promise<KnowledgeDocumentActionResult> {
  return runKnowledgeDocumentAction(docId, 'enable', { confirm: true, reason });
}

export async function batchDeleteKnowledgeDocuments(docIds: string[], reason = 'confirmed by knowledge administrator'): Promise<any> {
  return apiRequest('/api/ai/assistant/documents/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ doc_ids: docIds, confirm: true, reason }),
  });
}
