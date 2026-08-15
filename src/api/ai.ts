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

export interface AISecurityPolicy {
  external_ai_enabled: boolean;
  kill_switch: boolean;
  max_payload_bytes: number;
  identifiers_must_be_tokenized: boolean;
  allow_sensitive_minimization: boolean;
  allowed_provider_types: string[];
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

export interface AIPlatformMetrics {
  requests: Record<string, number>;
  by_scene: Record<string, { requests: number; avg_latency_ms: number; p95_latency_ms: number }>;
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

export async function testAISecurityPayload(messages: Array<{ role: string; content: string }>, tools?: unknown[]): Promise<AISecurityDryRunResult> {
  return apiRequest<AISecurityDryRunResult>('/api/ai/security/test-payload', {
    method: 'POST',
    body: JSON.stringify({ messages, tools }),
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
  id: string;
  label: string;
  status: AssistantProcessStepStatus;
  detail?: string;
  operation?: string;
  command?: string;
}

export interface AssistantStreamDoneMeta {
  duration_ms?: number;
}

export interface AssistantRetrievalTrace {
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
}

export interface AssistantStreamMeta {
  intent?: string;
  citations?: any[];
  facts_retrieved?: boolean;
  retrieval?: AssistantRetrievalTrace;
}

export interface AssistantStreamError {
  code?: string;
  message?: string;
}

export type AIConversationStatus = 'active' | 'archived';

export interface AIConversationSummary {
  id: string;
  tenant_id?: string;
  title: string;
  status: AIConversationStatus;
  context_budget?: number;
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

export async function listAIConversations(includeArchived = true): Promise<AIConversationList> {
  const query = includeArchived ? '?include_archived=true&page_size=100' : '?page_size=100';
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

export async function chatAssistant(message: string, history?: Array<{ role: string; content: string }>): Promise<{ answer: string; intent: string; citations: any[]; retrieval?: AssistantRetrievalTrace; request_id: string }> {
  return apiRequest('/api/ai/assistant/chat', {
    method: 'POST',
    body: JSON.stringify({ message, history }),
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
): Promise<void> {
  const token = localStorage.getItem('netops_token') || localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch('/api/ai/assistant/chat-stream', {
    method: 'POST',
    headers,
    body: JSON.stringify({ message, history, conversation_id: conversationId }),
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
        let parsed: any;
        try {
          parsed = JSON.parse(dataStr);
        } catch {
          // Ignore an incomplete or malformed SSE data line.
          continue;
        }

        if (currentEvent === 'meta' && onMeta) {
          onMeta(parsed);
        } else if (currentEvent === 'progress' && onProgress) {
          onProgress(parsed);
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
export async function getKnowledgeStats(): Promise<{ total_documents: number; total_chunks: number; total_vendors: number; ready_indexes: number }> {
  return apiRequest('/api/ai/assistant/knowledge-stats');
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

export async function getKnowledgeCatalog(filters: { vendor_id?: string; family_code?: string; series_code?: string; model?: string; software_version?: string; status?: string } = {}): Promise<KnowledgeCatalogResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value?.trim()) params.set(key, value.trim());
  });
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const payload = await apiRequest<KnowledgeCatalogResponse | KnowledgeCatalogApiEnvelope<KnowledgeCatalogResponse>>(`/api/knowledge-v2/catalog${suffix}`);
  return unwrapKnowledgeCatalogPayload(payload);
}

export async function getKnowledgeCatalogAliases(filters: { alias?: string; alias_kind?: string; conflict_status?: string } = {}): Promise<KnowledgeCatalogAliasesResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value?.trim()) params.set(key, value.trim());
  });
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const payload = await apiRequest<KnowledgeCatalogAliasesResponse | KnowledgeCatalogApiEnvelope<KnowledgeCatalogAliasesResponse>>(`/api/knowledge-v2/catalog/aliases${suffix}`);
  return unwrapKnowledgeCatalogPayload(payload);
}

export async function resolveKnowledgeCatalogAlias(query: string, limit = 20): Promise<KnowledgeCatalogResolveResponse> {
  const payload = await apiRequest<KnowledgeCatalogResolveResponse | KnowledgeCatalogApiEnvelope<KnowledgeCatalogResolveResponse>>('/api/knowledge-v2/catalog/resolve', {
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
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  updated_at?: string;
  chunks: KnowledgeDocumentChunk[];
}

export interface KnowledgeDocumentsResponse {
  items: KnowledgeDocument[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface KnowledgeDocumentsQuery {
  sourceType?: string;
  search?: string;
  directoryPath?: string;
  page?: number;
  pageSize?: number;
}

export async function getKnowledgeDocuments({
  sourceType,
  search,
  directoryPath,
  page = 1,
  pageSize = 20,
}: KnowledgeDocumentsQuery = {}): Promise<KnowledgeDocumentsResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (sourceType) params.set('source_type', sourceType);
  if (search?.trim()) params.set('search', search.trim());
  if (directoryPath?.trim()) params.set('directory_path', directoryPath.trim());
  return apiRequest(`/api/ai/assistant/documents?${params.toString()}`);
}

export async function getKnowledgeDocument(docId: string): Promise<KnowledgeDocumentDetail> {
  return apiRequest<KnowledgeDocumentDetail>(`/api/ai/assistant/documents/${encodeURIComponent(docId)}`);
}

export async function addKnowledgeDocument(data: {
  name: string;
  content: string;
  vendor: string;
  platform?: string | null;
  knowledge_source_type?: string;
  metadata?: Record<string, unknown>;
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
