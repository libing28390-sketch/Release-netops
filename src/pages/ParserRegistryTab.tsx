import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileCode2,
  GitBranch,
  Loader2,
  Maximize2,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Table2,
  Trash2,
  UploadCloud,
} from 'lucide-react';
import { ApiError, apiRequest } from '../api/http';
import Pagination from '../components/Pagination';
import ResultStatusModal from '../components/ResultStatusModal';

interface Props {
  language: string;
  currentUser?: { id?: string; username?: string; role?: string; role_profile?: string } | null;
  showToast?: (message: string, type?: 'success' | 'error' | 'info') => void;
}

interface TemplateRecord {
  id: string;
  tenant_id?: string | null;
  platform_profile_id?: string | null;
  platform_code: string;
  template_code: string;
  command?: string | null;
  source_filename?: string | null;
  name?: string;
  source?: string;
  status?: string;
  lock_version?: number;
}

interface VersionRecord {
  id: string;
  version_number: number;
  status: string;
  content: string;
  lock_version?: number;
  field_contract_json?: string;
  test_summary_json?: string;
  created_by?: string;
  submitted_by?: string;
  approved_by?: string;
  published_by?: string;
}

interface TestSummary {
  passed?: boolean;
  record_count?: number;
  fields?: string[];
  field_coverage?: Record<string, number>;
  field_contract?: Record<string, unknown>;
  duration_ms?: number;
  tested_at?: string;
  regression_count?: number;
}

interface TestResult {
  version_id?: string | null;
  records: Array<Record<string, unknown>>;
  fields: string[];
  count?: number;
  summary?: TestSummary;
}

type ResultFormat = 'table' | 'json' | 'csv';
type ResultFeedback = { type: 'success' | 'error'; text: string };

interface SampleRecord {
  id: string;
  sample_name: string;
  expected_records_json?: string;
  checksum?: string;
  created_by?: string;
  created_at?: string;
  raw_output_expires_at?: string;
}

interface ImpactRecord {
  action_count?: number;
  release_count?: number;
  profile_count?: number;
  device_count?: number;
  playbook_count?: number;
  version_count?: number;
}

interface MappingRecord {
  id: string;
  action_code: string;
  command?: string | null;
  template_command?: string | null;
  template_source_filename?: string | null;
  parser_template_version_id?: string | null;
  release_id: string;
  release_number?: number;
  release_status?: string;
  release_validation_status?: string;
  profile_id: string;
  platform_code?: string;
  parser_platform?: string;
  profile_name_zh?: string;
  profile_name_en?: string;
  profile_vendor?: string;
  profile_source?: string;
}

const normalizeBoundCommand = (value?: string | null): string => String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();

interface AuditRecord {
  id: string;
  event_type: string;
  actor_username?: string;
  metadata_json?: string;
  created_at?: string;
}

interface ListMeta {
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

interface PlatformProfileOption {
  id: string;
  platform_code: string;
  parser_platform?: string;
  connection_driver?: string;
  name_zh?: string;
  name_en?: string;
  vendor?: string;
  source?: string;
}

interface DriverPlatformOption {
  driver: string;
  parserPlatforms: string[];
  labels: string[];
}

interface ParserCapabilities {
  write_enabled: boolean;
  read_only_sandbox_enabled: boolean;
}

interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  meta?: Partial<ListMeta>;
  message?: string;
}

type DiffRow = { type: 'context' | 'added' | 'removed'; text: string };

const panelClass = 'rounded-2xl border border-black/5 bg-white shadow-sm';
const defaultContent = `Value FIELD (.*)

Start
  ^\${FIELD} -> Record
`;

const TEXTFSM_KEYWORDS = /^(Value|Start|EOF|Record|Continue|Clear|Error|Filldown|Fillup|List|Required|Key)\b/;

const highlightedTextFSM = (value: string): React.ReactNode[] => value.split('\n').map((line, index) => {
  const trimmed = line.trimStart();
  if (trimmed.startsWith('#')) return <div key={`line-${index}`} className="h-5 whitespace-pre text-slate-500">{line || ' '}</div>;
  const keyword = trimmed.match(TEXTFSM_KEYWORDS)?.[0];
  if (keyword) {
    const prefix = line.slice(0, line.length - trimmed.length);
    return <div key={`line-${index}`} className="h-5 whitespace-pre"><span className="text-slate-400">{prefix}</span><span className="text-cyan-300">{keyword}</span><span className="text-slate-200">{trimmed.slice(keyword.length) || ' '}</span></div>;
  }
  if (trimmed.includes('->')) {
    const arrow = line.indexOf('->');
    return <div key={`line-${index}`} className="h-5 whitespace-pre"><span className="text-amber-200">{line.slice(0, arrow)}</span><span className="text-fuchsia-300">-&gt;</span><span className="text-emerald-300">{line.slice(arrow + 2) || ' '}</span></div>;
  }
  return <div key={`line-${index}`} className="h-5 whitespace-pre text-slate-200">{line || ' '}</div>;
});

const parseJsonObject = (value?: string): Record<string, unknown> => {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
};

const parseSummary = (value?: string): TestSummary => {
  const parsed = parseJsonObject(value);
  return parsed as TestSummary;
};

const displayRecordValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
};

const csvCell = (value: unknown): string => {
  const text = displayRecordValue(value);
  // Keep generated CSV safe to open in spreadsheet applications when a CLI
  // value happens to begin with a formula-like character.
  const safeText = /^[=+\-@]/.test(text) ? `'${text}` : text;
  return `"${safeText.replace(/"/g, '""')}"`;
};

const recordsAsJson = (records: Array<Record<string, unknown>>): string => JSON.stringify(records, null, 2);

const recordsAsCsv = (records: Array<Record<string, unknown>>, fields: string[]): string => {
  const columns = fields.length ? fields : Array.from(new Set(records.flatMap((record) => Object.keys(record))));
  const rows = [columns.map((field) => csvCell(field)).join(',')];
  records.forEach((record) => rows.push(columns.map((field) => csvCell(record[field])).join(',')));
  return rows.join('\n');
};

const selectRecordFields = (records: Array<Record<string, unknown>>, fields: string[]): Array<Record<string, unknown>> => (
  records.map((record) => fields.reduce<Record<string, unknown>>((selected, field) => {
    selected[field] = record[field];
    return selected;
  }, {}))
);

interface ResultFieldSelectorProps {
  fields: string[];
  selectedFields: string[];
  language: string;
  testId: string;
  onToggle: (field: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
}

const ResultFieldSelector: React.FC<ResultFieldSelectorProps> = ({
  fields,
  selectedFields,
  language,
  testId,
  onToggle,
  onSelectAll,
  onClear,
}) => {
  if (!fields.length) return null;
  const zh = language === 'zh';
  const allSelected = selectedFields.length === fields.length;
  return (
    <details open className="rounded-lg border border-slate-200 bg-white/80" data-testid={testId}>
      <summary className="cursor-pointer list-none px-2.5 py-2 text-[10px] font-semibold text-slate-700">
        <span className="flex items-center justify-between gap-2">
          <span>{zh ? '选择导出字段' : 'Export fields'}</span>
          <span className="font-normal text-slate-400">{selectedFields.length}/{fields.length}</span>
        </span>
      </summary>
      <div className="border-t border-slate-100 px-2.5 py-2">
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <button type="button" onClick={onSelectAll} disabled={allSelected} className="rounded-md border border-cyan-200 bg-white px-2 py-1 text-[10px] font-semibold text-cyan-700 hover:bg-cyan-50 disabled:cursor-not-allowed disabled:opacity-40">
            {zh ? '全选' : 'Select all'}
          </button>
          <button type="button" onClick={onClear} disabled={!selectedFields.length} className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40">
            {zh ? '清空' : 'Clear'}
          </button>
          <span className="text-[10px] text-slate-400">{zh ? '表格、复制和下载均使用已勾选字段' : 'Table, copy and download use the selected fields'}</span>
        </div>
        <div className="flex max-h-24 flex-wrap gap-x-3 gap-y-1.5 overflow-y-auto">
          {fields.map((field) => (
            <label key={field} className="inline-flex min-w-0 items-center gap-1 text-[10px] text-slate-600">
              <input
                type="checkbox"
                checked={selectedFields.includes(field)}
                onChange={() => onToggle(field)}
                aria-label={`${zh ? '选择字段' : 'Select field'} ${field}`}
                className="h-3 w-3 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
              />
              <span className="max-w-[220px] truncate font-mono" title={field}>{field}</span>
            </label>
          ))}
        </div>
      </div>
    </details>
  );
};

const buildLineDiff = (before: string, after: string): DiffRow[] => {
  const oldLines = before.split('\n');
  const newLines = after.split('\n');
  const rows: DiffRow[] = [];
  const limit = Math.max(oldLines.length, newLines.length);
  for (let index = 0; index < limit; index += 1) {
    const oldLine = oldLines[index];
    const newLine = newLines[index];
    if (oldLine === newLine) rows.push({ type: 'context', text: oldLine || '' });
    else {
      if (oldLine !== undefined) rows.push({ type: 'removed', text: oldLine });
      if (newLine !== undefined) rows.push({ type: 'added', text: newLine });
    }
  }
  return rows;
};

const formatDate = (value: string | undefined, zh: boolean): string => {
  if (!value) return zh ? '暂无' : '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(zh ? 'zh-CN' : 'en-US');
};

const sourceLabel = (source: string | undefined, zh: boolean): string => {
  const normalized = String(source || 'CUSTOM').toUpperCase();
  if (!zh) return normalized;
  return ({ SYSTEM: '系统', CUSTOM: '自定义', FORKED: '租户副本' } as Record<string, string>)[normalized] || normalized;
};

const parserErrorMessagesZh: Record<string, string> = {
  TEMPLATE_NOT_MATCHED: '测试回显与当前 TextFSM 模板不匹配，请检查回显是否与绑定命令一致。',
  TEMPLATE_TIMEOUT: 'Sandbox 测试超时，请检查模板规则或缩小测试回显后重试。',
  TEMPLATE_SANDBOX_UNAVAILABLE: 'Sandbox 测试服务暂时不可用，请稍后重试。',
  TEMPLATE_SANDBOX_FAILED: 'Sandbox 解析服务执行失败，请稍后重试。',
  TEMPLATE_LIMIT_EXCEEDED: 'TextFSM 模板或解析结果超过限制，请缩小模板后重试。',
  OUTPUT_LIMIT_EXCEEDED: '测试回显超过限制，请缩小回显后重试。',
  RECORD_LIMIT_EXCEEDED: '解析结果记录数超过限制，请检查模板匹配范围。',
  FIELD_LIMIT_EXCEEDED: '解析结果字段超过限制，请检查模板输出。',
  SAMPLE_OUTPUT_REQUIRED: '请先填写测试回显。',
  FIELD_CONTRACT_VIOLATION: '测试回显未满足字段契约，请检查模板输出字段。',
  INVALID_FIELD_CONTRACT: '字段契约 JSON 无效，请检查 required、optional 和 types。',
  PARSER_CONTENT_REQUIRED: '请先填写 TextFSM 模板内容。',
  PARSER_TEST_REQUIRED: '解析版本必须先通过 Sandbox 测试后才能继续流转。',
  PARSER_TEMPLATE_ERROR: '解析模板操作失败，请稍后重试。',
  PARSER_TEST_FAILED: 'TextFSM 模板测试失败，请检查模板和测试回显。',
};

const errorMessage = (cause: unknown, fallback: string, zh = false): string => {
  if (cause instanceof ApiError) {
    const detail = cause.detail;
    const code = detail && typeof detail === 'object' && 'code' in detail
      ? String((detail as { code?: unknown }).code || '')
      : '';
    if (zh && parserErrorMessagesZh[code]) return parserErrorMessagesZh[code];
    if (code === 'SYSTEM_TEMPLATE_IMMUTABLE') {
      const message = zh
        ? '系统解析版本为只读，不能废弃或回滚。请先复制为租户副本。'
        : 'SYSTEM parser versions are read-only and cannot be deprecated or rolled back. Fork a tenant template first.';
      return message;
    }
    if (zh && code === 'PARSER_TEMPLATE_IN_USE') return '模板已被平台 Release 引用，请先替换命令映射再删除。';
    if (zh && code === 'PARSER_TEMPLATE_DELETE_BLOCKED') return '模板存在已发布版本，不能直接删除；请先处理 Release 映射或废弃该版本。';
    if (zh && code === 'PARSER_TEMPLATE_CONFLICT') return '模板已被其他人修改，请刷新后再保存。';
    if (zh && code === 'SELF_APPROVAL_FORBIDDEN') {
      const message = '版本创建人不能审批自己的版本，请由另一位具备审批权限的管理员审批。';
      return message;
    }
    return cause.message;
  }
  return cause instanceof Error ? cause.message : fallback;
};

const ParserRegistryTab: React.FC<Props> = ({ language, currentUser, showToast }) => {
  const zh = language === 'zh';
  const versionStatusLabel = (value?: string) => {
    const normalized = String(value || '').toUpperCase();
    if (!zh) return normalized;
    return ({
      DRAFT: '草稿', IN_REVIEW: '审核中', APPROVED: '已批准', PUBLISHED: '已发布', DEPRECATED: '已废弃',
    } as Record<string, string>)[normalized] || normalized;
  };
  const role = String(currentUser?.role || '');
  const roleProfile = String(currentUser?.role_profile || '');
  const isAdmin = role === 'Administrator';
  const roleCanEdit = isAdmin || (!roleProfile && role === 'Operator') || ['Template Developer', 'System Administrator'].includes(roleProfile);
  const roleCanReview = isAdmin || ['Release Manager', 'System Administrator'].includes(roleProfile);
  const roleCanTest = isAdmin || (!roleProfile && role === 'Operator') || ['Template Developer', 'System Administrator'].includes(roleProfile);
  const roleCanSample = roleCanEdit || isAdmin;
  const roleCanDelete = isAdmin || (!roleProfile && role === 'Operator') || ['Template Developer', 'System Administrator'].includes(roleProfile);

  const [templates, setTemplates] = useState<TemplateRecord[]>([]);
  const [platformProfiles, setPlatformProfiles] = useState<PlatformProfileOption[]>([]);
  const [capabilities, setCapabilities] = useState<ParserCapabilities | null>(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(true);
  const [capabilitiesError, setCapabilitiesError] = useState('');
  const [meta, setMeta] = useState<ListMeta>({ total: 0, page: 1, page_size: 50, pages: 0 });
  const [versions, setVersions] = useState<VersionRecord[]>([]);
  const [samples, setSamples] = useState<SampleRecord[]>([]);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [impact, setImpact] = useState<ImpactRecord | null>(null);
  const [mappings, setMappings] = useState<MappingRecord[]>([]);
  const [resultData, setResultData] = useState<TestResult | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [compareVersionId, setCompareVersionId] = useState('');
  const [newMode, setNewMode] = useState(false);
  const [search, setSearch] = useState('');
  const [driverFilter, setDriverFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [forking, setForking] = useState(false);
  const [forkModalOpen, setForkModalOpen] = useState(false);
  const [forkCode, setForkCode] = useState('');
  const [forkName, setForkName] = useState('');
  const [forkModalError, setForkModalError] = useState('');
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteModalError, setDeleteModalError] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [regressionTesting, setRegressionTesting] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [platformCode, setPlatformCode] = useState('cisco_ios');
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [templateCode, setTemplateCode] = useState('CUSTOM_TEMPLATE');
  const [templateCommand, setTemplateCommand] = useState('');
  const [templateName, setTemplateName] = useState('');
  const [content, setContent] = useState(defaultContent);
  const [contract, setContract] = useState('{}');
  const [sampleOutput, setSampleOutput] = useState('');
  const [sampleName, setSampleName] = useState('editor-sample');
  const [expectedRecords, setExpectedRecords] = useState('[]');
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [resultFormat, setResultFormat] = useState<ResultFormat>('table');
  const [resultModalOpen, setResultModalOpen] = useState(false);
  const [resultPage, setResultPage] = useState(1);
  const [resultPageSize, setResultPageSize] = useState(20);
  const [resultFieldSelection, setResultFieldSelection] = useState<string[] | null>(null);
  const [resultFeedback, setResultFeedback] = useState<ResultFeedback | null>(null);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [editorScrollLeft, setEditorScrollLeft] = useState(0);
  const [editorScrollTop, setEditorScrollTop] = useState(0);
  const templateVersionsRequestRef = useRef(0);
  const versionDetailsRequestRef = useRef(0);
  const selectedVersionRef = useRef<string | null>(null);
  const sampleScopeRef = useRef<string | null>(null);

  const resetSampleState = useCallback((scope?: string | null) => {
    setSampleOutput('');
    setSampleName('editor-sample');
    setExpectedRecords('[]');
    setTestResult(null);
    setResultData(null);
    setResultFieldSelection(null);
    setResultModalOpen(false);
    if (scope !== undefined) sampleScopeRef.current = scope;
  }, []);

  const deepLink = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    return {
      templateId: params.get('template_id') || '',
      templateCode: params.get('template_code') || '',
      versionId: params.get('version_id') || '',
    };
  }, []);

  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === selectedTemplateId) || null,
    [selectedTemplateId, templates],
  );
  const selectedVersion = useMemo(
    () => versions.find((item) => item.id === selectedVersionId) || null,
    [selectedVersionId, versions],
  );
  const compareVersion = useMemo(
    () => versions.find((item) => item.id === compareVersionId && item.id !== selectedVersionId)
      || versions.find((item) => item.id !== selectedVersionId)
      || null,
    [compareVersionId, selectedVersionId, versions],
  );
  const isSystemTemplate = selectedTemplate?.source === 'SYSTEM';
  const isMutableDraft = Boolean(selectedVersion && selectedVersion.status === 'DRAFT' && !isSystemTemplate && !newMode);
  const editorLineNumbers = useMemo(() => content.split('\n').map((_, index) => index + 1), [content]);
  const sourceDiff = useMemo(() => buildLineDiff(compareVersion?.content || '', content), [compareVersion?.content, content]);
  const activeResult = resultData || testResult;
  const currentSummary = activeResult?.summary || parseSummary(selectedVersion?.test_summary_json);
  const selectedVersionSummary = parseSummary(selectedVersion?.test_summary_json);
  const sandboxPassed = selectedVersionSummary.passed === true;
  const sandboxGateMessage = zh
    ? '请先完成 Sandbox 测试并确认通过，该版本才能提交审核。'
    : 'Run and pass the Sandbox test before submitting this version for review.';
  const resultFields = useMemo(() => {
    if (!activeResult) return [];
    return activeResult.fields.length
      ? activeResult.fields
      : Array.from(new Set(activeResult.records.flatMap((record) => Object.keys(record))));
  }, [activeResult]);
  const selectedResultFields = useMemo(
    () => resultFieldSelection === null
      ? resultFields
      : resultFields.filter((field) => resultFieldSelection.includes(field)),
    [resultFieldSelection, resultFields],
  );
  const selectedResultRecords = useMemo(
    () => activeResult ? selectRecordFields(activeResult.records, selectedResultFields) : [],
    [activeResult, selectedResultFields],
  );
  const resultJson = useMemo(() => (activeResult ? recordsAsJson(selectedResultRecords) : ''), [activeResult, selectedResultRecords]);
  const resultCsv = useMemo(() => (activeResult ? recordsAsCsv(selectedResultRecords, selectedResultFields) : ''), [activeResult, selectedResultFields, selectedResultRecords]);
  const resultExportFormat: Exclude<ResultFormat, 'table'> = resultFormat === 'json' ? 'json' : 'csv';
  const resultExportText = resultExportFormat === 'json' ? resultJson : resultCsv;
  const resultTotal = activeResult?.records.length || 0;
  const resultPageRecords = useMemo(() => {
    if (!activeResult) return [];
    const start = (resultPage - 1) * resultPageSize;
    return activeResult.records.slice(start, start + resultPageSize);
  }, [activeResult, resultPage, resultPageSize]);

  useEffect(() => {
    setResultPage(1);
    setResultFieldSelection(null);
    setResultFeedback(null);
    if (!activeResult) setResultModalOpen(false);
  }, [activeResult]);

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(resultTotal / resultPageSize));
    if (resultPage > totalPages) setResultPage(totalPages);
  }, [resultPage, resultPageSize, resultTotal]);
  const compareSummary = parseSummary(compareVersion?.test_summary_json);
  const currentFields = new Set(activeResult?.fields || currentSummary.fields || []);
  const compareFields = new Set(compareSummary.fields || []);
  const addedFields = Array.from(currentFields).filter((field) => !compareFields.has(field));
  const removedFields = Array.from(compareFields).filter((field) => !currentFields.has(field));
  const firstMapping = mappings[0];
  const mappingProfileId = firstMapping?.profile_id || selectedProfileId;
  const writeEnabled = capabilities?.write_enabled === true;
  const readOnlySandboxEnabled = !capabilitiesLoading && capabilities?.read_only_sandbox_enabled !== false;
  const canWrite = writeEnabled && roleCanEdit;
  const canEdit = canWrite;
  const canDelete = writeEnabled && roleCanDelete;
  // A published tenant version can seed a new draft, but its identity/scope
  // remains immutable until a draft exists.
  const canEditCurrent = canWrite && (newMode || Boolean(selectedVersion && !isSystemTemplate));
  const canEditMetadata = canWrite && (newMode || isMutableDraft);
  const canReview = writeEnabled && roleCanReview;
  const canSample = writeEnabled && roleCanSample;
  const canTest = roleCanTest && (isSystemTemplate ? readOnlySandboxEnabled : writeEnabled);
  const currentActorKeys = [currentUser?.id, currentUser?.username]
    .filter((value): value is string => Boolean(value))
    .map(String);
  const selfApprovalBlocked = Boolean(
    selectedVersion?.status === 'IN_REVIEW'
      && selectedVersion.created_by
      && currentActorKeys.includes(String(selectedVersion.created_by)),
  );
  const canWithdrawSelectedVersion = Boolean(
    selectedVersion?.status === 'IN_REVIEW'
      && canEdit
      && currentActorKeys.some((actor) => [selectedVersion?.submitted_by, selectedVersion?.created_by].filter(Boolean).map(String).includes(actor)),
  );

  const selectedPlatformProfile = useMemo(
    () => platformProfiles.find((profile) => profile.id === selectedProfileId) || null,
    [platformProfiles, selectedProfileId],
  );
  const profileOptions = useMemo(() => {
    if (newMode) return platformProfiles;
    return platformProfiles.filter((profile) => profile.parser_platform === platformCode || profile.platform_code === platformCode);
  }, [newMode, platformCode, platformProfiles]);
  const driverPlatformOptions = useMemo<DriverPlatformOption[]>(() => {
    const groups = new Map<string, DriverPlatformOption>();
    platformProfiles.forEach((profile) => {
      const driver = String(profile.connection_driver || profile.parser_platform || profile.platform_code || '').trim().toLowerCase();
      if (!driver) return;
      const parserPlatform = String(profile.parser_platform || profile.platform_code || '').trim().toLowerCase();
      const label = String(profile.name_zh || profile.name_en || profile.vendor || profile.platform_code || '').trim();
      const current = groups.get(driver) || { driver, parserPlatforms: [], labels: [] };
      if (parserPlatform && !current.parserPlatforms.includes(parserPlatform)) current.parserPlatforms.push(parserPlatform);
      if (label && !current.labels.includes(label)) current.labels.push(label);
      groups.set(driver, current);
    });
    return Array.from(groups.values()).sort((left, right) => left.driver.localeCompare(right.driver));
  }, [platformProfiles]);
  const driverByParserPlatform = useMemo(() => {
    const result = new Map<string, string>();
    platformProfiles.forEach((profile) => {
      const parserPlatform = String(profile.parser_platform || profile.platform_code || '').trim().toLowerCase();
      const driver = String(profile.connection_driver || profile.parser_platform || profile.platform_code || '').trim().toLowerCase();
      if (parserPlatform && driver && !result.has(parserPlatform)) result.set(parserPlatform, driver);
    });
    return result;
  }, [platformProfiles]);

  const resetFeedback = () => {
    setError('');
    setMessage('');
  };

  const loadCapabilities = useCallback(async () => {
    setCapabilitiesLoading(true);
    setCapabilitiesError('');
    try {
      const response = await apiRequest<ApiEnvelope<ParserCapabilities>>('/api/parser-templates/capabilities');
      setCapabilities(response.data || null);
    } catch (cause) {
      setCapabilities(null);
      setCapabilitiesError(errorMessage(cause, zh ? '功能开关状态读取失败，已关闭写入操作' : 'Could not read feature gate; writes are disabled'));
    } finally {
      setCapabilitiesLoading(false);
    }
  }, [zh]);

  const loadPlatformProfiles = useCallback(async () => {
    try {
      const response = await apiRequest<ApiEnvelope<PlatformProfileOption[]>>('/api/platform-registry/profiles');
      setPlatformProfiles(response.data || []);
    } catch {
      // Template editing remains available for legacy/unscoped records. A new
      // controlled template will surface a clear profile-required error.
      setPlatformProfiles([]);
    }
  }, []);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      // A Platform Registry deep link may point to a template outside the
      // first page. Use its stable template code to make the linked record
      // discoverable before applying the exact template/version ids.
      const templateSearch = search || deepLink.templateCode;
      const params = new URLSearchParams({ page: String(page), page_size: String(meta.page_size), search: templateSearch, driver_platform: driverFilter, source: sourceFilter, status: statusFilter });
      const response = await apiRequest<ApiEnvelope<TemplateRecord[]>>(`/api/parser-templates?${params.toString()}`);
      const next = response.data || [];
      setTemplates(next);
      setMeta({
        total: Number(response.meta?.total || 0),
        page: Number(response.meta?.page || page),
        page_size: Number(response.meta?.page_size || meta.page_size),
        pages: Number(response.meta?.pages || 0),
      });
      if (!newMode) {
        const linkedTemplate = next.find((item) => item.id === deepLink.templateId)
          || next.find((item) => item.template_code === deepLink.templateCode);
        setSelectedTemplateId((current) => current && next.some((item) => item.id === current)
          ? current
          : (linkedTemplate?.id || next[0]?.id || ''));
      }
    } catch (cause) {
      setError(errorMessage(cause, zh ? '模板列表加载失败' : 'Failed to load parser templates'));
    } finally {
      setLoading(false);
    }
  }, [deepLink.templateCode, deepLink.templateId, driverFilter, meta.page_size, newMode, page, search, sourceFilter, statusFilter, zh]);

  const loadVersions = useCallback(async (templateId: string) => {
    if (!templateId) return;
    const requestId = ++templateVersionsRequestRef.current;
    setDetailsLoading(true);
    try {
      const response = await apiRequest<ApiEnvelope<VersionRecord[]>>(`/api/parser-templates/${encodeURIComponent(templateId)}/versions`);
      if (requestId !== templateVersionsRequestRef.current) return;
      const next = response.data || [];
      setVersions(next);
      setSelectedVersionId((current) => current && next.some((item) => item.id === current)
        ? current
        : (next.find((item) => item.id === deepLink.versionId)?.id || next[0]?.id || ''));
    } catch (cause) {
      if (requestId === templateVersionsRequestRef.current) setError(errorMessage(cause, zh ? '版本加载失败' : 'Failed to load versions'));
    } finally {
      if (requestId === templateVersionsRequestRef.current) setDetailsLoading(false);
    }
  }, [deepLink.versionId, zh]);

  const loadVersionDetails = useCallback(async (versionId: string) => {
    const requestId = ++versionDetailsRequestRef.current;
    if (!versionId) {
      setSamples([]);
      setImpact(null);
      setAudit([]);
      setMappings([]);
      return;
    }
    setSamples([]);
    setImpact(null);
    setAudit([]);
    setMappings([]);
    try {
      const [sampleResponse, impactResponse, auditResponse, mappingResponse] = await Promise.all([
        apiRequest<ApiEnvelope<SampleRecord[]>>(`/api/parser-templates/versions/${encodeURIComponent(versionId)}/samples`),
        selectedTemplateId ? apiRequest<ApiEnvelope<ImpactRecord>>(`/api/parser-templates/${encodeURIComponent(selectedTemplateId)}/impact`) : Promise.resolve(null),
        selectedTemplateId ? apiRequest<ApiEnvelope<AuditRecord[]>>(`/api/parser-templates/${encodeURIComponent(selectedTemplateId)}/audit?limit=50`) : Promise.resolve(null),
        // Mapping visibility was added after the initial registry release;
        // keep older installations usable if this optional read endpoint is
        // not available yet.
        apiRequest<ApiEnvelope<MappingRecord[]>>(`/api/parser-templates/versions/${encodeURIComponent(versionId)}/mappings`).catch(() => null),
      ]);
      if (requestId !== versionDetailsRequestRef.current) return;
      setSamples(sampleResponse?.data || []);
      setImpact(impactResponse?.data || null);
      setAudit(auditResponse?.data || []);
      setMappings(mappingResponse?.data || []);
    } catch (cause) {
      if (requestId !== versionDetailsRequestRef.current) return;
      // Metadata is useful but should not hide the editor if an older install lacks one endpoint.
      setSamples([]);
      setAudit([]);
      setImpact(null);
      setMappings([]);
      if (cause instanceof ApiError && cause.status >= 500) setError(errorMessage(cause, zh ? '模板元数据加载失败' : 'Failed to load template metadata'));
    }
  }, [selectedTemplateId, zh]);

  useEffect(() => { void loadCapabilities(); }, [loadCapabilities]);
  useEffect(() => { void loadPlatformProfiles(); }, [loadPlatformProfiles]);

  useEffect(() => {
    if (!platformProfiles.length || selectedProfileId) return;
    const matching = platformProfiles.find((profile) => profile.parser_platform === platformCode);
    if (matching) setSelectedProfileId(matching.id);
  }, [platformCode, platformProfiles, selectedProfileId]);

  useEffect(() => { void loadTemplates(); }, [loadTemplates]);

  useEffect(() => {
    if (selectedTemplateId && !newMode) void loadVersions(selectedTemplateId);
    else {
      setVersions([]);
      setSelectedVersionId('');
      setSamples([]);
      setImpact(null);
      setAudit([]);
      setMappings([]);
    }
  }, [loadVersions, newMode, selectedTemplateId]);

  useEffect(() => {
    if (selectedVersionId && !newMode) void loadVersionDetails(selectedVersionId);
  }, [loadVersionDetails, newMode, selectedVersionId]);

  useEffect(() => {
    if (!selectedVersion || newMode) return;
    setContent(selectedVersion.content || '');
    setContract(JSON.stringify(parseJsonObject(selectedVersion.field_contract_json), null, 2));
    if (selectedVersionRef.current !== selectedVersion.id) {
      setTestResult(null);
      setResultData(null);
      setResultFieldSelection(null);
    }
    selectedVersionRef.current = selectedVersion.id;
  }, [newMode, selectedVersion]);

  useEffect(() => {
    if (newMode || !selectedTemplateId) return;
    if (sampleScopeRef.current === null) {
      sampleScopeRef.current = selectedTemplateId;
      return;
    }
    if (sampleScopeRef.current !== selectedTemplateId) {
      resetSampleState(selectedTemplateId);
    }
  }, [newMode, resetSampleState, selectedTemplateId]);

  useEffect(() => {
    if (!selectedTemplateId || newMode) return;
    const template = templates.find((item) => item.id === selectedTemplateId);
    if (!template) return;
    setPlatformCode(template.platform_code);
    setTemplateCode(template.template_code);
    setTemplateCommand(template.command || '');
    setTemplateName(template.name || template.template_code);
    const matchingProfile = platformProfiles.find((profile) => profile.id === template.platform_profile_id)
      || platformProfiles.find((profile) => profile.parser_platform === template.platform_code);
    setSelectedProfileId(matchingProfile?.id || '');
  }, [newMode, platformProfiles, selectedTemplateId, templates]);

  const startNewTemplate = () => {
    if (!canWrite) return;
    resetFeedback();
    setNewMode(true);
    setSelectedTemplateId('');
    setSelectedVersionId('');
    setVersions([]);
    setSamples([]);
    setImpact(null);
    setAudit([]);
    const defaultProfile = platformProfiles.find((profile) => profile.parser_platform === 'cisco_ios') || platformProfiles[0];
    setSelectedProfileId(defaultProfile?.id || '');
    setPlatformCode(defaultProfile?.parser_platform || 'cisco_ios');
    setTemplateCode('CUSTOM_TEMPLATE');
    setTemplateCommand('');
    setTemplateName('');
    setContent(defaultContent);
    setContract('{}');
    resetSampleState(null);
  };

  const selectTemplate = (template: TemplateRecord) => {
    // The first template is auto-selected when the list loads. Clicking that
    // already-selected row must not clear its editor while the version request
    // is still in flight (or leave it empty without triggering a new request).
    if (!newMode && selectedTemplateId === template.id) {
      if (!detailsLoading && !versions.length) void loadVersions(template.id);
      return;
    }
    resetFeedback();
    setNewMode(false);
    setSelectedTemplateId(template.id);
    setSelectedVersionId('');
    // Clear the previous template's editor immediately. If the details request
    // fails or is still in flight, never present stale Cisco/Huawei content
    // under the newly selected template metadata.
    setVersions([]);
    setSamples([]);
    setImpact(null);
    setAudit([]);
    setContent('');
    setContract('{}');
    setPlatformCode(template.platform_code);
    setTemplateCommand(template.command || '');
    const matchingProfile = platformProfiles.find((profile) => profile.id === template.platform_profile_id)
      || platformProfiles.find((profile) => profile.parser_platform === template.platform_code);
    setSelectedProfileId(matchingProfile?.id || '');
    setTemplateCode(template.template_code);
    setTemplateName(template.name || template.template_code);
    resetSampleState(template.id);
  };

  const parseContract = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(contract || '{}');
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('contract');
      return parsed as Record<string, unknown>;
    } catch {
      setError(zh ? '字段契约必须是 JSON 对象' : 'Field contract must be a JSON object');
      return null;
    }
  };

  const saveDraft = async () => {
    if (!canEdit) return;
    const parsedContract = parseContract();
    if (!parsedContract || !content.trim()) return;
    const selectedProfile = platformProfiles.find((profile) => profile.id === selectedProfileId);
    if (newMode && !selectedProfile) {
      setError(zh ? '请选择目标平台 Profile，确保 TextFSM 与平台解析器一致' : 'Select a target platform profile so the TextFSM parser matches the platform');
      return;
    }
    const effectivePlatformCode = selectedProfile?.parser_platform || platformCode.trim();
    if (newMode && selectedProfile && effectivePlatformCode !== platformCode.trim()) {
      setPlatformCode(effectivePlatformCode);
    }
    resetFeedback();
    setSaving(true);
    try {
      let templateId = selectedTemplateId;
      if (newMode || !templateId) {
        const templateResponse = await apiRequest<ApiEnvelope<TemplateRecord>>('/api/parser-templates', {
          method: 'POST',
          body: JSON.stringify({ platform_code: effectivePlatformCode, platform_profile_id: selectedProfileId, template_code: templateCode.trim().toUpperCase(), command: templateCommand.trim(), name: templateName.trim() || templateCode.trim().toUpperCase() }),
        });
        templateId = templateResponse.data.id;
        setNewMode(false);
        setSelectedTemplateId(templateId);
      }
      if (!newMode && templateId && selectedVersion?.status === 'DRAFT' && !isSystemTemplate) {
        await apiRequest<ApiEnvelope<TemplateRecord>>(`/api/parser-templates/${encodeURIComponent(templateId)}`, {
          method: 'PUT',
          body: JSON.stringify({
            platform_code: effectivePlatformCode,
            platform_profile_id: selectedProfileId || selectedTemplate?.platform_profile_id || null,
            template_code: templateCode.trim().toUpperCase(),
            command: templateCommand.trim(),
            name: templateName.trim() || templateCode.trim().toUpperCase(),
            lock_version: selectedTemplate?.lock_version,
          }),
        });
      }
      if (selectedVersion && selectedVersion.status === 'DRAFT' && !isSystemTemplate && !newMode && selectedVersion.id) {
        await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersion.id)}`, {
          method: 'PUT',
          body: JSON.stringify({ content, field_contract: parsedContract, lock_version: selectedVersion.lock_version }),
        });
      } else {
        const versionResponse = await apiRequest<ApiEnvelope<VersionRecord>>(`/api/parser-templates/${encodeURIComponent(templateId)}/versions`, {
          method: 'POST',
          body: JSON.stringify({ content, field_contract: parsedContract }),
        });
        setSelectedVersionId(versionResponse.data.id);
      }
      await loadTemplates();
      await loadVersions(templateId);
      setMessage(zh ? (newMode ? '草稿已保存' : '修改已保存') : (newMode ? 'Draft saved' : 'Changes saved'));
    } catch (cause) {
      setError(errorMessage(cause, zh ? '草稿保存失败' : 'Failed to save draft'));
    } finally {
      setSaving(false);
    }
  };

  const openDeleteModal = () => {
    if (!selectedTemplate || isSystemTemplate || !canDelete) return;
    setDeleteModalError('');
    setDeleteModalOpen(true);
  };

  const deleteSelectedTemplate = async () => {
    if (!selectedTemplate || isSystemTemplate || !canDelete) return;
    setDeleteModalError('');
    setDeleting(true);
    try {
      await apiRequest(`/api/parser-templates/${encodeURIComponent(selectedTemplate.id)}`, { method: 'DELETE' });
      setDeleteModalOpen(false);
      setSelectedTemplateId('');
      setSelectedVersionId('');
      setVersions([]);
      setSamples([]);
      setImpact(null);
      setAudit([]);
      setContent('');
      setContract('{}');
      resetSampleState(null);
      await loadTemplates();
      setMessage(zh ? '模板已删除' : 'Template deleted');
    } catch (cause) {
      const messageText = errorMessage(cause, zh ? '模板删除失败' : 'Failed to delete template', zh);
      setDeleteModalError(messageText);
    } finally {
      setDeleting(false);
    }
  };

  const openForkModal = () => {
    if (!selectedTemplate || !isSystemTemplate || !canEdit) return;
    if (!selectedProfileId) {
      setError(zh ? '请选择目标平台 Profile 后再复制' : 'Select a target platform profile before forking');
      return;
    }
    setForkCode(`${selectedTemplate.template_code}_FORK`.slice(0, 64));
    setForkName(`${selectedTemplate.name || selectedTemplate.template_code} ${zh ? '副本' : 'Fork'}`);
    setForkModalError('');
    setForkModalOpen(true);
  };

  const forkSelectedTemplate = async () => {
    if (!selectedTemplate || !isSystemTemplate || !canEdit) return;
    const normalizedCode = forkCode.trim().toUpperCase();
    const normalizedName = forkName.trim();
    if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(normalizedCode)) {
      setForkModalError(zh ? '模板编码必须以大写字母开头，只能包含大写字母、数字和下划线' : 'Template code must start with an uppercase letter and use only A-Z, 0-9, and underscore');
      return;
    }
    if (!normalizedName) {
      setForkModalError(zh ? '请输入租户模板名称' : 'Enter a tenant template name');
      return;
    }
    resetFeedback();
    setForking(true);
    try {
      const response = await apiRequest<ApiEnvelope<TemplateRecord>>(`/api/parser-templates/${encodeURIComponent(selectedTemplate.id)}/fork`, {
        method: 'POST',
        body: JSON.stringify({ template_code: normalizedCode, name: normalizedName, platform_profile_id: selectedProfileId || undefined }),
      });
      setForkModalOpen(false);
      setNewMode(false);
      setSelectedTemplateId(response.data.id);
      setSelectedVersionId('');
      setVersions([]);
      setTestResult(null);
      setResultData(null);
      setResultFieldSelection(null);
      setResultModalOpen(false);
      resetSampleState(response.data.id);
      await loadTemplates();
      setMessage(zh ? '系统模板已复制为租户副本' : 'SYSTEM template forked into a tenant template');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '复制失败' : 'Failed to fork template'));
    } finally {
      setForking(false);
    }
  };

  const toggleResultField = (field: string) => {
    setResultFieldSelection((current) => {
      const selected = current === null ? resultFields : current;
      return selected.includes(field)
        ? selected.filter((item) => item !== field)
        : [...selected, field];
    });
  };

  const selectAllResultFields = () => setResultFieldSelection(resultFields);
  const clearResultFields = () => setResultFieldSelection([]);

  const copyResult = async () => {
    const format = resultExportFormat.toUpperCase();
    if (!activeResult || !resultExportText || (resultFields.length > 0 && !selectedResultFields.length)) {
      const feedback = !activeResult || !resultExportText
        ? (zh ? '当前没有可复制的解析结果' : 'There is no parsed result to copy')
        : (zh ? '请至少选择一个字段后再复制' : 'Select at least one field before copying');
      setResultFeedback({ type: 'error', text: feedback });
      showToast?.(feedback, 'error');
      return;
    }

    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(resultExportText);
        copied = true;
      }
    } catch {
      // Clipboard API can be present but denied on an HTTP/IP origin. Fall
      // through to the legacy textarea path below.
    }

    if (!copied) {
      const textarea = document.createElement('textarea');
      textarea.value = resultExportText;
      textarea.setAttribute('readonly', 'true');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      textarea.style.top = '0';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      try {
        copied = typeof document.execCommand === 'function' && document.execCommand('copy');
      } catch {
        copied = false;
      }
      textarea.remove();
    }

    if (!copied) {
      const feedback = zh ? '复制失败，请检查浏览器剪贴板权限，或手动选择文本复制' : 'Copy failed; check clipboard permissions or select the text manually';
      setResultFeedback({ type: 'error', text: feedback });
      setError(feedback);
      showToast?.(feedback, 'error');
      return;
    }

    const feedback = zh ? `已复制 ${format} 结果` : `${format} result copied`;
    setResultFeedback({ type: 'success', text: feedback });
    setMessage(feedback);
    showToast?.(feedback, 'success');
  };

  const downloadResult = () => {
    if (!activeResult || !resultExportText || (resultFields.length > 0 && !selectedResultFields.length)) {
      const feedback = !activeResult || !resultExportText
        ? (zh ? '当前没有可下载的解析结果' : 'There is no parsed result to download')
        : (zh ? '请至少选择一个字段后再下载' : 'Select at least one field before downloading');
      setResultFeedback({ type: 'error', text: feedback });
      showToast?.(feedback, 'error');
      return;
    }
    const extension = resultExportFormat === 'json' ? 'json' : 'csv';
    const mime = resultExportFormat === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8';
    const blob = new Blob([resultExportText], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${(templateCode || 'parser-result').toLowerCase()}-sandbox.${extension}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    setMessage(zh ? `已下载 ${resultExportFormat.toUpperCase()} 结果` : `${resultExportFormat.toUpperCase()} result downloaded`);
  };

  const runTest = async () => {
    if (!canTest) return;
    const parsedContract = parseContract();
    if (!parsedContract || !sampleOutput.trim()) {
      if (!sampleOutput.trim()) setError(zh ? '请提供测试回显' : 'Provide sample output first');
      return;
    }
    resetFeedback();
    setTesting(true);
    try {
      const response = await apiRequest<ApiEnvelope<TestResult>>('/api/parser-templates/sandbox-test', {
        method: 'POST',
        body: JSON.stringify({
          version_id: selectedVersionId || undefined,
          content,
          field_contract: parsedContract,
          sample_output: sampleOutput,
          persist: isMutableDraft,
          lock_version: selectedVersion?.lock_version,
        }),
      });
      setResultData(response.data);
      setTestResult(null);
      if (isMutableDraft && selectedTemplateId) await loadVersions(selectedTemplateId);
      setMessage(zh ? `Sandbox 解析通过，共 ${response.data.records.length} 条记录` : `Sandbox passed with ${response.data.records.length} records`);
    } catch (cause) {
      setTestResult(null);
      setResultData(null);
      setError(errorMessage(cause, zh ? 'Sandbox 测试失败' : 'Sandbox test failed', zh));
    } finally {
      setTesting(false);
    }
  };

  const transition = async (action: 'submit' | 'withdraw' | 'approve' | 'reject' | 'publish' | 'rollback' | 'deprecate', reason = '') => {
    const allowed = action === 'submit' || action === 'withdraw' ? canEdit : canReview;
    if (!selectedVersionId || !allowed) return;
    if ((action === 'submit' || action === 'approve' || action === 'publish') && !sandboxPassed) {
      setError(sandboxGateMessage);
      return;
    }
    if ((action === 'approve' || action === 'reject') && selfApprovalBlocked) {
      const selfApprovalMessage = zh
        ? '版本创建人不能审核自己的版本，请由另一位具备审批权限的管理员处理。'
        : 'The creator cannot review their own parser version; ask another authorized administrator to review it.';
      setError(selfApprovalMessage);
      return;
    }
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/${action}`, {
        method: 'POST',
        ...(action === 'reject' ? { body: JSON.stringify({ reason }) } : {}),
      });
      setRejectModalOpen(false);
      setRejectReason('');
      await loadVersions(selectedTemplateId);
      await loadVersionDetails(selectedVersionId);
      setMessage(zh ? `版本${action === 'submit' ? '已提交' : action === 'withdraw' ? '已撤回到草稿' : action === 'approve' ? '已审批' : action === 'reject' ? '已驳回并退回草稿' : action === 'publish' ? '已发布' : action === 'rollback' ? '已回滚' : '已废弃'}` : `Version ${action} completed`);
    } catch (cause) {
      setError(errorMessage(cause, zh ? '版本流转失败' : 'Version transition failed', zh));
    }
  };

  const uploadSample = async () => {
    if (!selectedVersionId || !sampleOutput.trim() || !canSample || isSystemTemplate) return;
    let expected: unknown[] = [];
    try {
      const parsed = JSON.parse(expectedRecords || '[]');
      if (!Array.isArray(parsed)) throw new Error('expected_records');
      expected = parsed;
    } catch {
      setError(zh ? '期望记录必须是 JSON 数组' : 'Expected records must be a JSON array');
      return;
    }
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/versions/${encodeURIComponent(selectedVersionId)}/samples`, {
        method: 'POST',
        body: JSON.stringify({ sample_name: sampleName.trim() || 'editor-sample', sample_output: sampleOutput, expected_records: expected }),
      });
      await loadVersionDetails(selectedVersionId);
      setMessage(zh ? '样例已加密保存' : 'Sample encrypted and stored');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '样例保存失败' : 'Sample upload failed'));
    }
  };

  const removeSample = async (sampleId: string) => {
    if (!canSample || isSystemTemplate) return;
    resetFeedback();
    try {
      await apiRequest(`/api/parser-templates/samples/${encodeURIComponent(sampleId)}`, { method: 'DELETE' });
      await loadVersionDetails(selectedVersionId);
      setMessage(zh ? '样例已删除' : 'Sample deleted');
    } catch (cause) {
      setError(errorMessage(cause, zh ? '样例删除失败' : 'Sample delete failed'));
    }
  };

  const runRegression = async () => {
    if (!selectedTemplateId || !selectedVersionId || isSystemTemplate || !canWrite) return;
    resetFeedback();
    setRegressionTesting(true);
    try {
      const response = await apiRequest<ApiEnvelope<{ sample_count?: number }>>(`/api/parser-templates/${encodeURIComponent(selectedTemplateId)}/regression-test`, {
        method: 'POST',
        body: JSON.stringify({ version_id: selectedVersionId }),
      });
      setMessage(zh ? `历史样例回归通过（${response.data.sample_count || 0} 个样例）` : `Historical regression passed (${response.data.sample_count || 0} samples)`);
    } catch (cause) {
      setError(errorMessage(cause, zh ? '历史样例回归失败' : 'Historical regression failed'));
    } finally {
      setRegressionTesting(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold text-slate-800"><FileCode2 size={20} className="text-[#00bceb]" />{zh ? 'TextFSM 注册表开发' : 'TextFSM Registry Development'}</div>
          <p className="mt-1 text-xs text-slate-500">{zh ? '租户隔离草稿、沙箱解析、加密样例、影响分析与受控发布' : 'Tenant drafts, sandbox parsing, encrypted samples, impact analysis and controlled release'}</p>
        </div>
        <div className="flex items-center gap-2"><button onClick={() => setManualOpen(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-semibold text-cyan-700 hover:bg-cyan-100" data-testid="parser-manual-button"><BookOpen size={14} />{zh ? '注册手册' : 'Registration guide'}</button><button onClick={() => void loadTemplates()} className="rounded-lg border border-black/10 bg-white p-2 text-slate-500 hover:text-[#00bceb]" title={zh ? '刷新' : 'Refresh'} data-testid="parser-refresh"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button></div>
      </div>

      {(error || message) && <div className={`rounded-xl border px-3 py-2 text-xs ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{error || message}</div>}
      {capabilitiesLoading && <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">{zh ? '正在读取功能开关状态…' : 'Reading feature gate…'}</div>}
      {!capabilitiesLoading && capabilities && !capabilities.write_enabled && <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">{zh ? '当前为只读审查模式：仅允许 SYSTEM（系统）模板只读 Sandbox，不会保存版本或样例。' : 'Read-only review mode: only SYSTEM read-only Sandbox is available; no versions or samples are saved.'}</div>}
      {!capabilitiesLoading && capabilities?.write_enabled && !roleCanEdit && <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">{zh ? '当前角色没有 TextFSM 写入权限；可继续查看模板和允许的测试能力。' : 'Your current role has no TextFSM write permission; you can still view templates and allowed test capabilities.'}</div>}
      {capabilitiesError && <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{capabilitiesError}</div>}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)]" data-testid="parser-registry-layout">
        <aside className={`${panelClass} flex min-h-[300px] flex-col overflow-hidden lg:min-h-0`}>
          <div className="border-b border-black/5 p-3">
            <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-700"><span>{zh ? '模板' : 'Templates'}</span>{canWrite && <button onClick={startNewTemplate} className="inline-flex items-center gap-1 rounded-md bg-[#00bceb] px-2 py-1 text-[10px] font-semibold text-white" data-testid="parser-new-template"><Plus size={13} />{zh ? '新建' : 'New'}</button>}</div>
            <div className="relative"><Search size={13} className="absolute left-2.5 top-2.5 text-slate-400" /><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={zh ? '搜索模板/平台' : 'Search template/platform'} className="w-full rounded-lg border border-black/10 py-2 pl-8 pr-2 text-xs outline-none focus:border-cyan-400" data-testid="parser-search" /></div>
            <div className="mt-2 space-y-2">
              <select value={driverFilter} onChange={(event) => { setDriverFilter(event.target.value); setPage(1); }} className="w-full rounded-lg border border-cyan-200 bg-cyan-50/40 px-2 py-1.5 text-[10px] text-slate-700" data-testid="parser-driver-filter" aria-label={zh ? 'Netmiko 驱动平台' : 'Netmiko driver platform'}>
                <option value="">{zh ? '全部 Netmiko 驱动平台' : 'All Netmiko driver platforms'}</option>
                {driverPlatformOptions.map((option) => <option key={option.driver} value={option.driver}>{option.driver}{option.labels.length ? ` · ${option.labels.slice(0, 2).join(' / ')}` : ''}</option>)}
              </select>
              <div className="grid grid-cols-2 gap-2"><select value={sourceFilter} onChange={(event) => { setSourceFilter(event.target.value); setPage(1); }} className="rounded-lg border border-black/10 px-2 py-1.5 text-[10px] text-slate-600" data-testid="parser-source-filter"><option value="">{zh ? '全部来源' : 'All sources'}</option><option value="SYSTEM">{sourceLabel('SYSTEM', zh)}</option><option value="CUSTOM">{sourceLabel('CUSTOM', zh)}</option><option value="FORKED">{sourceLabel('FORKED', zh)}</option></select><select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} className="rounded-lg border border-black/10 px-2 py-1.5 text-[10px] text-slate-600" data-testid="parser-status-filter"><option value="">{zh ? '全部状态' : 'All statuses'}</option><option value="ACTIVE">ACTIVE</option><option value="ARCHIVED">ARCHIVED</option></select></div>
            </div>
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {templates.map((template) => {
              const parserPlatform = String(template.platform_code || '').toLowerCase();
              const driver = driverByParserPlatform.get(parserPlatform);
              return <button key={template.id} onClick={() => selectTemplate(template)} className={`w-full rounded-lg px-3 py-2.5 text-left ${!newMode && selectedTemplateId === template.id ? 'bg-cyan-50 text-cyan-800 ring-1 ring-cyan-100' : 'hover:bg-slate-50'}`} data-testid={`parser-template-${template.template_code}`} title={`${template.name || template.template_code} · ${template.template_code}`}><div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="truncate text-xs font-semibold" title={template.name || template.template_code}>{template.name || template.template_code}</div><div className="mt-1 truncate font-mono text-[10px] text-slate-500" title={template.template_code}>{template.template_code}</div></div><span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${template.source === 'SYSTEM' ? 'bg-slate-100 text-slate-500' : 'bg-cyan-50 text-cyan-700'}`}>{sourceLabel(template.source, zh)}</span></div><div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-slate-400"><span className="truncate" title={driver ? `Netmiko: ${driver} · parser: ${parserPlatform}` : parserPlatform}>{driver ? `driver: ${driver}` : `parser: ${parserPlatform}`}</span><span className="shrink-0">{template.status || 'ACTIVE'}</span></div><div className="mt-0.5 truncate font-mono text-[9px] text-slate-400" title={parserPlatform}>parser: {parserPlatform || '—'}</div></button>;
            })}
            {!templates.length && <div className="p-4 text-center text-xs text-slate-400">{zh ? '暂无可见模板' : 'No visible templates'}</div>}
          </div>
          <div className="flex items-center justify-between border-t border-black/5 px-3 py-2 text-[10px] text-slate-400"><span>{meta.total} {zh ? '个模板' : 'templates'}</span><div className="flex items-center gap-1"><button disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronLeft size={13} /></button><span>{page}/{Math.max(meta.pages, 1)}</span><button disabled={!meta.pages || page >= meta.pages} onClick={() => setPage((current) => current + 1)} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronRight size={13} /></button></div></div>
        </aside>

        <main className={`${panelClass} flex min-h-0 flex-col overflow-hidden`}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-black/5 px-4 py-3">
            <div className="flex items-center gap-2 text-xs text-slate-500"><GitBranch size={14} />{newMode ? (zh ? '新建模板' : 'New template') : selectedTemplate ? selectedTemplate.template_code : (zh ? '请选择模板' : 'Select a template')}{isSystemTemplate && <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">{sourceLabel('SYSTEM', zh)} {zh ? '只读' : 'read-only'}</span>}</div>
            <div className="flex flex-wrap gap-2">
              {isSystemTemplate && canWrite && <button onClick={openForkModal} disabled={forking || !canEdit} className="inline-flex items-center gap-1 rounded-lg bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"><GitBranch size={13} />{forking ? (zh ? '复制中' : 'Forking') : (zh ? '复制为租户模板' : 'Fork to tenant')}</button>}
              {!isSystemTemplate && canWrite && <button onClick={() => void saveDraft()} disabled={saving || !canEditCurrent} className="inline-flex items-center gap-1 rounded-lg bg-[#00bceb] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" data-testid="parser-save-draft">{saving ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}{newMode ? (zh ? '保存草稿' : 'Save draft') : selectedVersion?.status === 'DRAFT' ? (zh ? '保存修改' : 'Save changes') : (zh ? '创建草稿' : 'Create draft')}</button>}
              {!newMode && !isSystemTemplate && canDelete && <button onClick={openDeleteModal} disabled={deleting} className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 disabled:opacity-50" data-testid="parser-delete-template"><Trash2 size={13} />{zh ? '删除模板' : 'Delete template'}</button>}
              <button onClick={() => void runTest()} disabled={testing || !canTest || !content.trim() || !sampleOutput.trim()} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40" data-testid="parser-sandbox-test"><PlayCircle size={13} />{testing ? (zh ? '解析中' : 'Testing') : (zh ? 'Sandbox 测试' : 'Sandbox test')}</button>
              <button onClick={() => void uploadSample()} disabled={!selectedVersionId || isSystemTemplate || !canSample || !sampleOutput.trim()} className="inline-flex items-center gap-1 rounded-lg border border-black/10 px-3 py-1.5 text-xs font-semibold text-slate-600 disabled:opacity-40" data-testid="parser-upload-sample"><UploadCloud size={13} />{zh ? '上传加密样例' : 'Upload sample'}</button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-4" data-testid="parser-registry-scroll-area">
            <div data-testid="parser-copy-help" className="mb-3 rounded-xl border border-cyan-100 bg-cyan-50/70 px-3 py-2 text-[11px] leading-5 text-cyan-950">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="font-semibold">{zh ? '编辑提示' : 'Edit guide'}</span><span className="text-cyan-800">{zh ? '复制 → 编辑规则 → Sandbox → 保存修改 → 提交/发布' : 'Copy → edit rules → Sandbox → save changes → submit/publish'}</span><details className="ml-auto"><summary className="cursor-pointer select-none text-[10px] font-semibold text-cyan-700">{zh ? '查看字段和命令说明' : 'Show field and command guide'}</summary><div className="mt-2 grid grid-cols-1 gap-2 border-t border-cyan-100 pt-2 text-[10px] sm:grid-cols-2">
                <div data-testid="parser-command-help" className="rounded-lg border border-amber-100 bg-amber-50/70 p-2 text-amber-950"><b>{zh ? '命令绑定边界' : 'Command binding boundary'}</b><br />{zh ? '命令不在 TextFSM 页面编辑；到“平台注册 → Profile → Draft Release → 命令映射”绑定 command、action_code 和已发布解析版本。' : 'Commands are not edited in TextFSM; bind command, action_code and the published parser version in Platform Registry → Profile → Draft Release → Command mappings.'}<code className="mt-1 block font-mono text-[9px]">action_code → command + parser_template_version_id</code></div>
                <div data-testid="parser-field-guide" className="rounded-lg border border-slate-200 bg-white/80 p-2 text-slate-600"><b className="text-slate-800">{zh ? '字段说明' : 'Field guide'}</b><div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1"><span><b>Profile</b>：{zh ? '平台范围' : 'platform scope'}</span><span><b>parser_platform</b>：{zh ? '解析键' : 'parser key'}</span><span><b>template_code</b>：{zh ? '唯一编码，非命令' : 'unique code, not command'}</span><span><b>name</b>：{zh ? '显示名称' : 'display name'}</span><span><b>content</b>：{zh ? 'Value/Start/Record 规则' : 'Value/Start/Record rules'}</span><span><b>field_contract</b>：{zh ? '用 required/optional/types 约束输出字段' : 'required/optional/types constraints'}</span><span><b>sample output</b>：{zh ? '与目标命令对应的脱敏回显' : 'redacted output for the target command'}</span><span><b>sample name</b>：{zh ? '保存样例时的标识，不参与解析' : 'label for a stored sample, not parsing'}</span><span><b>expected records</b>：{zh ? '上传加密样例时保存的期望 JSON，不参与当前 Sandbox 通过判断' : 'expected JSON stored with an encrypted sample; not used by the current Sandbox pass gate'}</span></div></div>
                <div className="rounded-lg border border-cyan-100 bg-white/80 p-2 font-mono text-[9px] leading-4 text-slate-700 sm:col-span-2"><b className="font-sans text-slate-800">TextFSM</b><br />{'Value INTERFACE (\\S+)\nValue STATUS (up|down)\nStart\n  ^${INTERFACE}\\s+${STATUS} -> Record'}</div>
              </div></details></div>
            </div>
            <div className="mb-3 rounded-xl border border-cyan-100 bg-cyan-50/50 p-3" data-testid="parser-command-mappings">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-xs font-semibold text-cyan-950">{zh ? 'Release 关联（只读）' : 'Release bindings (read-only)'} <span className="font-normal text-cyan-700">({mappings.length})</span></div>
                <a href={`/automation/platforms?detail=mappings${mappingProfileId ? `&profile_id=${encodeURIComponent(mappingProfileId)}` : ''}${firstMapping?.release_id ? `&release_id=${encodeURIComponent(firstMapping.release_id)}` : ''}`} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[10px] font-semibold text-cyan-700 hover:bg-cyan-100" title={zh ? '前往平台注册编辑命令映射' : 'Open Platform Registry to edit command mappings'}>
                  <ExternalLink size={11} />{zh ? '去平台注册编辑' : 'Edit in Platform Registry'}
                </a>
              </div>
              {!selectedVersionId ? (
                <div className="text-[10px] text-slate-400">{zh ? '选择一个版本后查看它关联的 action_code、命令和 Release；此处只读。' : 'Select a version to see its action_code, command and Release bindings; this view is read-only.'}</div>
              ) : mappings.length === 0 ? (
                <div className="rounded-lg border border-dashed border-cyan-200 bg-white/70 px-2.5 py-2 text-[10px] leading-4 text-slate-500">{zh ? '当前版本尚未被 Release 动作映射引用。命令由平台注册的 Draft Release 维护；TextFSM 页面只展示关联。' : 'This version is not referenced by a Release action yet. Commands are maintained in a Platform Registry Draft Release; TextFSM only shows the relationship.'}</div>
              ) : (
                <div className="space-y-1.5">
                  {mappings.map((mapping) => (
                    <div key={mapping.id} className="rounded-lg border border-cyan-100 bg-white px-2.5 py-2 text-[10px] text-slate-600">
                      {(() => {
                        const commandMismatch = Boolean(
                          mapping.command
                            && mapping.template_command
                            && normalizeBoundCommand(mapping.command) !== normalizeBoundCommand(mapping.template_command),
                        );
                        return (
                          <>
                      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                        <span className="font-mono font-semibold text-slate-800">{mapping.action_code}</span>
                        <span className="text-slate-400">{mapping.profile_name_zh || mapping.profile_name_en || mapping.profile_vendor || mapping.platform_code || mapping.parser_platform || '—'} · v{mapping.release_number ?? '—'} {mapping.release_status || ''}</span>
                      </div>
                      <div className="mt-1 break-all font-mono text-cyan-800">{mapping.command || (zh ? '未映射命令' : 'Command not mapped')}</div>
                      {mapping.template_command && <div className="mt-1 break-all font-mono text-slate-500"><span className="font-sans text-slate-400">{zh ? 'TextFSM 绑定命令：' : 'TextFSM command: '}</span>{mapping.template_command}</div>}
                      {commandMismatch && <div className="mt-1 text-rose-700">{zh ? '命令与 TextFSM 绑定命令不一致，不能作为严格匹配使用。' : 'The action command does not match the TextFSM command binding.'}</div>}
                          </>
                        );
                      })()}
                    </div>
                  ))}
                </div>
              )}
            </div>
            {activeResult && <section data-testid="parser-result-panel" className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50/70 p-3 text-xs text-emerald-900">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 font-semibold"><Table2 size={14} />{zh ? '解析结果' : 'Parsed result'} · {activeResult.records.length} {zh ? '条记录' : 'records'}</div>
                  <div className="mt-1 text-[10px] text-emerald-800">{zh ? '已选字段' : 'Selected fields'}: {selectedResultFields.join(', ') || '—'} · {zh ? '耗时' : 'Duration'}: {currentSummary.duration_ms ?? 0} ms</div>
                  <div className="mt-1 text-[10px] text-emerald-700">{zh ? 'Sandbox 只展示本次解析结果；期望记录用于上传样例后的历史回归。' : 'Sandbox shows this parse only; expected records are for regression after an encrypted sample is uploaded.'}</div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <div className="flex rounded-lg border border-emerald-200 bg-white p-0.5" role="tablist" aria-label={zh ? '结果格式' : 'Result format'}>
                    {(['table', 'json', 'csv'] as ResultFormat[]).map((format) => <button key={format} type="button" role="tab" aria-selected={resultFormat === format} onClick={() => setResultFormat(format)} className={`rounded-md px-2 py-1 text-[10px] font-semibold ${resultFormat === format ? 'bg-emerald-600 text-white' : 'text-emerald-700 hover:bg-emerald-50'}`} data-testid={`parser-result-format-${format}`}>{format === 'table' ? (zh ? '表格' : 'Table') : format.toUpperCase()}</button>)}
                  </div>
                  <button type="button" onClick={() => setResultModalOpen(true)} className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2 py-1 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-100" data-testid="parser-result-open"><Maximize2 size={11} />{zh ? '放大查看' : 'Open viewer'}</button>
                  <button type="button" onClick={() => void copyResult()} className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2 py-1 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-100" data-testid="parser-result-copy"><Copy size={11} />{zh ? `复制 ${resultExportFormat.toUpperCase()}` : `Copy ${resultExportFormat.toUpperCase()}`}</button>
                  <button type="button" onClick={downloadResult} className="inline-flex items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2 py-1 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-100" data-testid="parser-result-download"><Download size={11} />{zh ? `下载 ${resultExportFormat.toUpperCase()}` : `Download ${resultExportFormat.toUpperCase()}`}</button>
                </div>
              </div>
              <ResultFieldSelector fields={resultFields} selectedFields={selectedResultFields} language={language} testId="parser-result-field-selector-inline" onToggle={toggleResultField} onSelectAll={selectAllResultFields} onClear={clearResultFields} />
              {resultFormat === 'table' ? <div className="mt-2 max-h-72 overflow-auto rounded-lg border border-emerald-100 bg-white" data-testid="parser-result-table"><table className="min-w-full text-left text-[10px]"><thead className="sticky top-0 bg-emerald-100/80 text-emerald-950"><tr><th className="px-2 py-1.5 font-semibold">#</th>{selectedResultFields.map((field) => <th key={field} className="whitespace-nowrap px-2 py-1.5 font-semibold">{field}</th>)}</tr></thead><tbody>{resultPageRecords.map((record, index) => <tr key={`result-row-${(resultPage - 1) * resultPageSize + index}`} className="border-t border-emerald-100 align-top"><td className="px-2 py-1.5 text-emerald-500">{(resultPage - 1) * resultPageSize + index + 1}</td>{selectedResultFields.length ? selectedResultFields.map((field) => <td key={field} className="max-w-[260px] whitespace-pre-wrap break-words px-2 py-1.5 font-mono text-emerald-900">{displayRecordValue(record[field]) || '—'}</td>) : <td className="px-2 py-1.5 text-slate-500" colSpan={Math.max(selectedResultFields.length, 1)}>{zh ? '请至少选择一个字段' : 'Select at least one field'}</td>}</tr>)}</tbody></table></div> : <pre data-testid={`parser-result-${resultFormat}`} className="mt-2 max-h-72 overflow-auto rounded-lg border border-emerald-100 bg-white p-3 font-mono text-[10px] leading-4 text-emerald-950">{resultFormat === 'json' ? resultJson : resultCsv}</pre>}
              {resultFormat === 'table' && <div data-testid="parser-result-inline-pagination" className="mt-2 overflow-hidden rounded-lg border border-emerald-100 bg-white"><Pagination currentPage={resultPage} totalItems={resultTotal} itemsPerPage={resultPageSize} onPageChange={setResultPage} onItemsPerPageChange={(size) => { setResultPageSize(size); setResultPage(1); }} language={language} alwaysVisible /></div>}
              {resultFeedback && <div data-testid="parser-result-feedback-inline" role="status" aria-live="polite" className={`mt-2 rounded-lg border px-2 py-1.5 text-[10px] ${resultFeedback.type === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>{resultFeedback.text}</div>}
            </section>}
            <div className="grid min-w-0 grid-cols-2 gap-3">
            <div className="flex min-w-0 flex-col gap-3">
              {selectedVersion && !isSystemTemplate && selectedVersion.status !== 'PUBLISHED' && selectedVersion.status !== 'DEPRECATED' && (
                <div data-testid="parser-submit-test-gate" className={`rounded-xl border px-3 py-2 text-[10px] leading-4 ${sandboxPassed ? 'border-emerald-100 bg-emerald-50 text-emerald-800' : 'border-amber-100 bg-amber-50 text-amber-900'}`}>
                  <span className="font-semibold">{zh ? 'Sandbox 门禁：' : 'Sandbox gate: '}</span>
                  {sandboxPassed ? (zh ? '已通过，允许提交审核。' : 'Passed; submission is allowed.') : sandboxGateMessage}
                </div>
              )}
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4" data-testid="parser-identity-fields">
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '目标平台 Profile' : 'Target platform Profile'}</span><select value={selectedProfileId} onChange={(event) => { const nextId = event.target.value; const nextProfile = platformProfiles.find((profile) => profile.id === nextId); setSelectedProfileId(nextId); if (nextProfile?.parser_platform) setPlatformCode(nextProfile.parser_platform); }} disabled={!canEditMetadata} aria-label={zh ? '目标平台 Profile' : 'Target platform profile'} className="w-full rounded-lg border border-cyan-200 bg-white px-2.5 py-2 text-xs font-normal text-slate-700 outline-none focus:border-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500">
                    <option value="">{zh ? '选择平台 Profile' : 'Select platform profile'}</option>
                    {profileOptions.map((profile) => <option key={profile.id} value={profile.id}>{(zh ? profile.name_zh : profile.name_en) || profile.vendor || profile.platform_code} · {profile.platform_code} / {profile.parser_platform}</option>)}
                  </select></label>
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">parser_platform</span><input value={platformCode} readOnly={!canEditMetadata || Boolean(selectedProfileId)} aria-readonly={!canEditMetadata || Boolean(selectedProfileId)} onChange={(event) => setPlatformCode(event.target.value)} placeholder="parser_platform" className={`w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal outline-none ${!canEditMetadata || Boolean(selectedProfileId) ? 'cursor-not-allowed bg-slate-100 text-slate-500' : 'bg-white focus:border-cyan-400'}`} /></label>
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">template_code</span><input value={templateCode} readOnly={!canEditMetadata} aria-readonly={!canEditMetadata} onChange={(event) => setTemplateCode(event.target.value.toUpperCase())} placeholder="TEMPLATE_CODE" className={`w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal outline-none ${!canEditMetadata ? 'cursor-not-allowed bg-slate-100 text-slate-500' : 'bg-white focus:border-cyan-400'}`} /></label>
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '绑定命令' : 'Bound command'}</span><input value={templateCommand} readOnly={!canEditMetadata} aria-readonly={!canEditMetadata} onChange={(event) => setTemplateCommand(event.target.value)} placeholder={zh ? '例如：display bgp peer ipv4 unicast' : 'e.g. display bgp peer ipv4 unicast'} className={`w-full rounded-lg border border-amber-200 px-2.5 py-2 font-mono text-[10px] font-normal outline-none ${!canEditMetadata ? 'cursor-not-allowed bg-slate-100 text-slate-500' : 'bg-white focus:border-cyan-400'}`} /></label>
                <label className="min-w-0 text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '模板名称' : 'Template name'}</span><input value={templateName} readOnly={!canEditMetadata} aria-readonly={!canEditMetadata} onChange={(event) => setTemplateName(event.target.value)} placeholder={zh ? '模板名称' : 'Template name'} className={`w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal outline-none ${!canEditMetadata ? 'cursor-not-allowed bg-slate-100 text-slate-500' : 'bg-white focus:border-cyan-400'}`} /></label>
              </div>
              {newMode && <div className="text-[10px] text-slate-400">{zh ? `平台选择决定 parser_platform：${selectedPlatformProfile?.parser_platform || '尚未选择'}；保存后只能绑定到同一 Profile。` : `The selected profile determines parser_platform: ${selectedPlatformProfile?.parser_platform || 'not selected'}; bindings are restricted to the same profile.`}</div>}
              <label className="flex min-h-[280px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600">{zh ? '模板内容（带行号）' : 'Template content (with line numbers)'}<div className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-black/10 bg-slate-950 focus-within:border-cyan-400"><div aria-hidden="true" className="pointer-events-none absolute left-0 top-0 z-10 w-10 select-none border-r border-white/10 bg-slate-900/80 px-2 py-3 text-right font-mono text-xs leading-5 text-slate-500" style={{ transform: `translateY(-${editorScrollTop}px)` }}>{editorLineNumbers.map((lineNumber) => <div key={lineNumber}>{lineNumber}</div>)}</div><pre aria-hidden="true" className="pointer-events-none absolute left-12 top-0 min-w-full py-3 pr-3 font-mono text-xs leading-5" style={{ transform: `translate(${-editorScrollLeft}px, -${editorScrollTop}px)` }}>{highlightedTextFSM(content)}</pre><textarea value={content} readOnly={!canEditCurrent} aria-label={zh ? 'TextFSM 模板内容' : 'TextFSM template content'} onChange={(event) => setContent(event.target.value)} onScroll={(event) => { setEditorScrollTop(event.currentTarget.scrollTop); setEditorScrollLeft(event.currentTarget.scrollLeft); }} className={`relative z-20 h-full min-h-[280px] w-full resize-none bg-transparent py-3 pl-12 pr-3 font-mono text-xs leading-5 outline-none selection:bg-cyan-300/30 ${!canEditCurrent ? 'cursor-not-allowed text-transparent caret-slate-400' : 'text-transparent caret-white'}`} spellCheck={false} /></div></label>
              <label className="flex min-h-[120px] flex-col gap-1 text-xs font-semibold text-slate-600"><span>{zh ? '字段契约 JSON' : 'Field contract JSON'}</span><textarea value={contract} readOnly={!canEditCurrent} onChange={(event) => setContract(event.target.value)} className={`min-h-0 flex-1 resize-none rounded-xl border border-black/10 p-3 font-mono text-xs leading-5 outline-none ${!canEditCurrent ? 'cursor-not-allowed bg-slate-100 text-slate-400' : 'bg-slate-50 text-slate-700 focus:border-cyan-400'}`} spellCheck={false} /><span className="text-[10px] font-normal text-slate-400">{zh ? '例如：{"required":["interface","ip_address"],"types":{"ip_address":"string"}}；required 非空时，0 条记录会被判定为失败。' : 'Example: {"required":["interface","ip_address"],"types":{"ip_address":"string"}}; a non-empty required list rejects zero-record samples.'}</span></label>
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 text-xs font-semibold text-slate-600">{zh ? '影响分析' : 'Impact analysis'}</div><div className="grid grid-cols-3 gap-2 text-[10px] text-slate-500"><span>Actions: <b className="text-slate-800">{impact?.action_count || 0}</b></span><span>Releases: <b className="text-slate-800">{impact?.release_count || 0}</b></span><span>Profiles: <b className="text-slate-800">{impact?.profile_count || 0}</b></span><span>Devices: <b className="text-slate-800">{impact?.device_count || 0}</b></span><span>Playbooks: <b className="text-slate-800">{impact?.playbook_count || 0}</b></span><span>Versions: <b className="text-slate-800">{impact?.version_count || 0}</b></span></div></div>
            </div>

            <div className="flex min-w-0 flex-col gap-3">
              <label className="flex min-h-[180px] flex-1 flex-col gap-1 text-xs font-semibold text-slate-600"><span className="flex items-center justify-between gap-2"><span>{zh ? '测试回显（Sandbox/加密样例）' : 'Sample output (sandbox/encrypted sample)'}</span><span id="parser-sandbox-hint" className="font-normal text-slate-400" data-testid="parser-sandbox-hint">{sampleOutput.trim() ? (zh ? '可运行只读测试' : 'Ready for read-only test') : (zh ? '请先填写测试回显' : 'Enter sample output to enable testing')}</span></span><textarea value={sampleOutput} onChange={(event) => setSampleOutput(event.target.value)} aria-describedby="parser-sandbox-hint" className="min-h-0 flex-1 resize-none rounded-xl border border-black/10 bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-700 outline-none focus:border-cyan-400" spellCheck={false} /></label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2"><label className="text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '样例名称' : 'Sample name'}</span><input value={sampleName} onChange={(event) => setSampleName(event.target.value)} placeholder="editor-sample" aria-label={zh ? '样例名称' : 'Sample name'} readOnly={isSystemTemplate || !canSample} className={`w-full rounded-lg border border-black/10 px-2.5 py-2 text-xs font-normal ${isSystemTemplate || !canSample ? 'cursor-not-allowed bg-slate-100 text-slate-400' : 'bg-white'}`} /><span className="mt-1 block font-normal text-slate-400">{isSystemTemplate ? (zh ? 'SYSTEM 只读版本不能保存加密样例；请先复制为租户模板。' : 'SYSTEM versions cannot store samples; fork a tenant template first.') : (zh ? '例如：h3c_ip_interfaces_20260804；仅用于区分已保存样例。' : 'Example: h3c_ip_interfaces_20260804; identifies a stored sample.')}</span></label><label className="text-[10px] font-semibold text-slate-600"><span className="mb-1 block">{zh ? '期望记录 JSON 数组' : 'Expected records JSON array'}</span><input value={expectedRecords} onChange={(event) => setExpectedRecords(event.target.value)} placeholder="[]" aria-label={zh ? '期望记录 JSON 数组' : 'Expected records JSON array'} readOnly={isSystemTemplate || !canSample} className={`w-full rounded-lg border border-black/10 px-2.5 py-2 font-mono text-xs font-normal ${isSystemTemplate || !canSample ? 'cursor-not-allowed bg-slate-100 text-slate-400' : 'bg-white'}`} /><span className="mt-1 block font-normal text-slate-400">{isSystemTemplate ? (zh ? 'SYSTEM 只读版本不会比较或保存期望记录；Sandbox 只显示本次解析结果。' : 'SYSTEM read-only versions do not compare or store expected records; Sandbox shows this parse only.') : (zh ? '例如：[{"interface":"GE1/0/1","ip_address":"10.0.0.1/24"}]；上传加密样例后用于历史回归。' : 'Example: [{"interface":"GE1/0/1","ip_address":"10.0.0.1/24"}]; used for regression after upload.')}</span></label></div>
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-600"><span>{zh ? '版本与发布' : 'Version lifecycle'}</span>{detailsLoading && <Loader2 size={13} className="animate-spin text-cyan-600" />}</div>{isSystemTemplate && <div className="mb-2 rounded-lg border border-amber-100 bg-amber-50 px-2.5 py-2 text-[10px] leading-4 text-amber-800">{zh ? '系统版本为只读，不能废弃或回滚；如需修改或替换，请先复制为租户副本。' : 'SYSTEM versions are read-only and cannot be deprecated or rolled back. Fork a tenant template to modify or replace the parser.'}</div>}<div className="mb-2 flex flex-wrap gap-1.5">{versions.map((version) => <button key={version.id} onClick={() => { setSelectedVersionId(version.id); setCompareVersionId(''); }} className={`rounded-md px-2 py-1 text-[10px] ${selectedVersionId === version.id ? 'bg-cyan-600 text-white' : 'bg-white text-slate-500 ring-1 ring-black/5'}`}>v{version.version_number} · {versionStatusLabel(version.status)}</button>)}{!versions.length && <span className="text-[10px] text-slate-400">{newMode ? (zh ? '保存后生成版本' : 'Save to create a version') : (zh ? '暂无版本' : 'No versions')}</span>}</div>{versions.length > 1 && <label className="mb-2 flex items-center gap-2 text-[10px] text-slate-500"><span>{zh ? '对比基线' : 'Compare baseline'}</span><select value={compareVersion?.id || ''} onChange={(event) => setCompareVersionId(event.target.value)} className="min-w-0 flex-1 rounded-md border border-black/10 bg-white px-2 py-1 text-[10px]"><option value="">{zh ? '自动选择上一版本' : 'Auto-select previous version'}</option>{versions.filter((version) => version.id !== selectedVersionId).map((version) => <option key={version.id} value={version.id}>v{version.version_number} · {versionStatusLabel(version.status)}</option>)}</select></label>}{selectedVersion && <div className="flex flex-wrap gap-1.5"><button onClick={() => void runRegression()} disabled={regressionTesting || isSystemTemplate || !canWrite} className="rounded-md border border-cyan-200 bg-white px-2 py-1 text-[10px] font-semibold text-cyan-700 disabled:opacity-40">{regressionTesting ? '…' : (zh ? '历史回归' : 'Regression')}</button>{selectedVersion.status === 'DRAFT' && canEdit && <button onClick={() => void transition('submit')} className="inline-flex items-center gap-1 rounded-md bg-amber-500 px-2 py-1 text-[10px] font-semibold text-white"><Send size={11} />{zh ? '提交审核' : 'Submit'}</button>}{selectedVersion.status === 'IN_REVIEW' && canWithdrawSelectedVersion && <button onClick={() => void transition('withdraw')} className="rounded-md border border-amber-200 bg-white px-2 py-1 text-[10px] font-semibold text-amber-700">{zh ? '撤回到草稿' : 'Withdraw'}</button>}{selectedVersion.status === 'IN_REVIEW' && canReview && <><button onClick={() => { setRejectReason(''); setRejectModalOpen(true); }} disabled={selfApprovalBlocked} title={selfApprovalBlocked ? (zh ? '创建人不能审核自己的版本，请由另一位具备审批权限的管理员处理。' : 'The creator cannot review their own parser version; ask another authorized administrator.') : undefined} className="rounded-md border border-rose-200 bg-white px-2 py-1 text-[10px] font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-50">{zh ? '驳回' : 'Reject'}</button><button onClick={() => void transition('approve')} disabled={selfApprovalBlocked} title={selfApprovalBlocked ? (zh ? '创建人不能审核自己的版本，请由另一位具备审批权限的管理员处理。' : 'The creator cannot review their own parser version; ask another authorized administrator.') : undefined} className="inline-flex items-center gap-1 rounded-md bg-indigo-500 px-2 py-1 text-[10px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"><ShieldCheck size={11} />{zh ? '审批' : 'Approve'}</button>{selfApprovalBlocked && <span className="self-center text-[10px] text-rose-600">{zh ? '创建人不能自审批' : 'Creator cannot self-review'}</span>}</>}{selectedVersion.status === 'APPROVED' && canReview && <button onClick={() => void transition('publish')} className="inline-flex items-center gap-1 rounded-md bg-emerald-600 px-2 py-1 text-xs font-semibold text-white"><CheckCircle2 size={11} />{zh ? '发布' : 'Publish'}</button>}{selectedVersion.status === 'PUBLISHED' && canReview && !isSystemTemplate && <button onClick={() => void transition('deprecate')} className="rounded-md border border-rose-200 bg-white px-2 py-1 text-[10px] font-semibold text-rose-700">{zh ? '废弃' : 'Deprecate'}</button>}{selectedVersion.status === 'DEPRECATED' && canReview && !isSystemTemplate && <button onClick={() => void transition('rollback')} className="rounded-md border border-violet-200 bg-white px-2 py-1 text-[10px] font-semibold text-violet-700">{zh ? '回滚' : 'Rollback'}</button>}</div>}</div>
              {testResult && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800"><div className="font-semibold">{zh ? '解析结果' : 'Parsed result'} · {testResult.records.length} {zh ? '条记录' : 'records'}</div><div className="mt-1">{zh ? '字段' : 'Fields'}: {testResult.fields.join(', ') || '—'} · {zh ? '耗时' : 'Duration'}: {currentSummary.duration_ms ?? 0} ms</div><div className="mt-2 max-h-48 overflow-auto rounded-lg border border-emerald-100 bg-white"><table className="min-w-full text-left text-[10px]"><thead className="bg-emerald-100/60 text-emerald-900"><tr>{testResult.fields.map((field) => <th key={field} className="px-2 py-1 font-semibold">{field}</th>)}</tr></thead><tbody>{testResult.records.slice(0, 100).map((record, index) => <tr key={`record-${index}`} className="border-t border-emerald-100"><td colSpan={Math.max(testResult.fields.length, 1)} className="px-2 py-1 align-top"><code>{JSON.stringify(record)}</code></td></tr>)}</tbody></table></div></div>}
              <div className="rounded-xl border border-black/5 bg-slate-50 p-3"><div className="mb-2 text-xs font-semibold text-slate-600">{zh ? '加密样例列表' : 'Encrypted samples'}</div>{samples.length ? <div className="space-y-1">{samples.map((sample) => <div key={sample.id} className="flex items-center justify-between gap-2 rounded-lg bg-white px-2.5 py-2 text-[10px] text-slate-500"><span className="min-w-0 truncate"><b className="text-slate-700">{sample.sample_name}</b> · {formatDate(sample.created_at, zh)}</span>{canSample && !isSystemTemplate && <button onClick={() => void removeSample(sample.id)} className="rounded p-1 text-rose-500 hover:bg-rose-50" title={zh ? '删除样例' : 'Delete sample'}><Trash2 size={12} /></button>}</div>)}</div> : <div className="text-[10px] text-slate-400">{zh ? '暂无已保存样例' : 'No stored samples'}</div>}</div>
              {compareVersion && <div className="space-y-2 rounded-xl border border-violet-100 bg-violet-50/50 p-3"><div className="flex items-center justify-between text-xs font-semibold text-violet-900"><span>{zh ? `Diff · v${compareVersion.version_number} → 当前编辑内容` : `Diff · v${compareVersion.version_number} → current editor`}</span><span className="text-[10px] font-normal">{sourceDiff.filter((row) => row.type === 'added').length} + / {sourceDiff.filter((row) => row.type === 'removed').length} −</span></div><div className="max-h-40 overflow-auto rounded-lg border border-violet-100 bg-slate-950 p-2 font-mono text-[10px] leading-5">{sourceDiff.slice(0, 300).map((row, index) => <div key={`${row.type}-${index}`} className={row.type === 'added' ? 'bg-emerald-900/50 text-emerald-200' : row.type === 'removed' ? 'bg-rose-900/50 text-rose-200' : 'text-slate-400'}><span className="mr-2 inline-block w-3 text-center text-slate-500">{row.type === 'added' ? '+' : row.type === 'removed' ? '−' : ' '}</span>{row.text || ' '}</div>)}</div><div className="text-[10px] text-violet-900">{zh ? '解析字段变化' : 'Parsed fields'}: +{addedFields.join(', ') || '—'} / −{removedFields.join(', ') || '—'}</div></div>}
              {audit.length > 0 && <details className="rounded-xl border border-black/5 bg-slate-50 p-3"><summary className="cursor-pointer text-xs font-semibold text-slate-600">{zh ? '审计记录' : 'Audit history'} ({audit.length})</summary><div className="mt-2 max-h-24 space-y-1 overflow-auto text-[10px] text-slate-500">{audit.map((item) => <div key={item.id}>{formatDate(item.created_at, zh)} · <b>{item.event_type}</b> · {item.actor_username || 'system'}</div>)}</div></details>}
            </div>
            </div>
          </div>
        </main>
      </div>
      <ResultStatusModal
        open={rejectModalOpen}
        onClose={() => setRejectModalOpen(false)}
        title={zh ? '驳回版本' : 'Reject parser version'}
        closeTitle={zh ? '关闭驳回窗口' : 'Close rejection dialog'}
        icon={ShieldCheck}
        iconClassName="bg-rose-100 text-rose-700"
        headerClassName="border-b border-rose-100 bg-rose-50/70"
        panelClassName="w-full max-w-lg rounded-2xl border border-rose-100 bg-white shadow-2xl"
        bodyClassName="p-5"
      >
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void transition('reject', rejectReason.trim()); }}>
          <p className="text-xs leading-5 text-slate-600">{zh ? '驳回后版本会退回草稿，提交人可以修改后再次提交。原因会记录在审计日志中。' : 'The version returns to DRAFT and can be corrected and resubmitted. The reason is stored in the audit log.'}</p>
          <label className="block text-xs font-semibold text-slate-700">
            {zh ? '驳回原因（可选）' : 'Rejection reason (optional)'}
            <textarea value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} maxLength={2000} autoFocus className="mt-1 min-h-28 w-full resize-y rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-rose-400 focus:ring-2 focus:ring-rose-100" />
          </label>
          <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <button type="button" onClick={() => setRejectModalOpen(false)} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100">{zh ? '取消' : 'Cancel'}</button>
            <button type="submit" className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-rose-700">{zh ? '确认驳回' : 'Confirm rejection'}</button>
          </div>
        </form>
      </ResultStatusModal>
      <ResultStatusModal
        open={resultModalOpen && Boolean(activeResult)}
        onClose={() => setResultModalOpen(false)}
        title={zh ? `解析结果 · ${activeResult?.records.length || 0} 条记录` : `Parsed result · ${activeResult?.records.length || 0} records`}
        closeTitle={zh ? '关闭解析结果' : 'Close parsed result'}
        icon={Table2}
        iconClassName="bg-emerald-100 text-emerald-700"
        headerClassName="border-b border-emerald-100 bg-emerald-50/70"
        panelClassName="w-full max-w-[min(96vw,1400px)] overflow-hidden rounded-2xl border border-emerald-100 bg-white shadow-2xl"
        bodyClassName="max-h-[82vh] overflow-y-auto p-4 sm:p-5"
      >
        {activeResult && <div className="space-y-3" data-testid="parser-result-modal">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
            <div>{zh ? '已选字段' : 'Selected fields'}: {selectedResultFields.join(', ') || '—'} · {zh ? '耗时' : 'Duration'}: {currentSummary.duration_ms ?? 0} ms</div>
            <div className="flex flex-wrap items-center gap-1.5">
              <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5" role="tablist" aria-label={zh ? '结果格式' : 'Result format'}>
                {(['table', 'json', 'csv'] as ResultFormat[]).map((format) => <button key={format} type="button" role="tab" aria-selected={resultFormat === format} onClick={() => setResultFormat(format)} className={`rounded-md px-2.5 py-1 text-[10px] font-semibold ${resultFormat === format ? 'bg-emerald-600 text-white' : 'text-slate-600 hover:bg-white'}`} data-testid={`parser-result-modal-format-${format}`}>{format === 'table' ? (zh ? '表格' : 'Table') : format.toUpperCase()}</button>)}
              </div>
              <button type="button" onClick={() => void copyResult()} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-semibold text-slate-700 hover:bg-slate-50" data-testid="parser-result-modal-copy"><Copy size={11} />{zh ? `复制 ${resultExportFormat.toUpperCase()}` : `Copy ${resultExportFormat.toUpperCase()}`}</button>
              <button type="button" onClick={downloadResult} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[10px] font-semibold text-slate-700 hover:bg-slate-50" data-testid="parser-result-modal-download"><Download size={11} />{zh ? `下载 ${resultExportFormat.toUpperCase()}` : `Download ${resultExportFormat.toUpperCase()}`}</button>
            </div>
          </div>
          {resultFeedback && <div data-testid="parser-result-feedback-modal" role="status" aria-live="polite" className={`rounded-lg border px-2 py-1.5 text-[10px] ${resultFeedback.type === 'success' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>{resultFeedback.text}</div>}
          <ResultFieldSelector fields={resultFields} selectedFields={selectedResultFields} language={language} testId="parser-result-field-selector-modal" onToggle={toggleResultField} onSelectAll={selectAllResultFields} onClear={clearResultFields} />
          {resultFormat === 'table' ? <div className="max-h-[65vh] overflow-auto rounded-xl border border-slate-200" data-testid="parser-result-modal-table"><table className="min-w-full text-left text-xs"><thead className="sticky top-0 z-10 bg-emerald-100 text-emerald-950"><tr><th className="px-3 py-2 font-semibold">#</th>{selectedResultFields.map((field) => <th key={field} className="whitespace-nowrap px-3 py-2 font-semibold">{field}</th>)}</tr></thead><tbody>{resultPageRecords.map((record, index) => <tr key={`modal-result-row-${(resultPage - 1) * resultPageSize + index}`} className="border-t border-slate-100 align-top odd:bg-white even:bg-slate-50/60"><td className="px-3 py-2 text-slate-400">{(resultPage - 1) * resultPageSize + index + 1}</td>{selectedResultFields.length ? selectedResultFields.map((field) => <td key={field} className="max-w-[420px] whitespace-pre-wrap break-words px-3 py-2 font-mono text-slate-700">{displayRecordValue(record[field]) || '—'}</td>) : <td className="px-3 py-2 text-slate-500" colSpan={Math.max(selectedResultFields.length, 1)}>{zh ? '请至少选择一个字段' : 'Select at least one field'}</td>}</tr>)}</tbody></table></div> : <pre data-testid={`parser-result-modal-${resultFormat}`} className="max-h-[65vh] overflow-auto rounded-xl border border-slate-200 bg-slate-950 p-4 font-mono text-xs leading-5 text-slate-100">{resultFormat === 'json' ? resultJson : resultCsv}</pre>}
          {resultFormat === 'table' && <div data-testid="parser-result-modal-pagination" className="overflow-hidden rounded-xl border border-slate-200 bg-white"><Pagination currentPage={resultPage} totalItems={resultTotal} itemsPerPage={resultPageSize} onPageChange={setResultPage} onItemsPerPageChange={(size) => { setResultPageSize(size); setResultPage(1); }} language={language} alwaysVisible /></div>}
          <div className="text-[10px] text-slate-400">{zh ? '表格适合查看，复制/下载使用当前 JSON 或 CSV 格式；均包含全部记录。' : 'Table is for viewing; copy/download uses the selected JSON or CSV format and includes all records.'}</div>
        </div>}
      </ResultStatusModal>
      <ResultStatusModal
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        title={zh ? 'TextFSM 注册手册' : 'TextFSM registration guide'}
        closeTitle={zh ? '关闭注册手册' : 'Close registration guide'}
        icon={BookOpen}
        iconClassName="bg-cyan-100 text-cyan-700"
        headerClassName="border-b border-cyan-100 bg-cyan-50/70"
        panelClassName="w-full max-w-3xl rounded-2xl border border-cyan-100 bg-white shadow-2xl"
        bodyClassName="max-h-[75vh] overflow-y-auto p-5"
      >
        <div data-testid="parser-registration-manual" className="space-y-5 text-xs leading-5 text-slate-600">
          <section><h3 className="font-semibold text-slate-900">{zh ? '一、复制或新建' : '1. Copy or create'}</h3><p className="mt-1">{zh ? '系统模板不能直接修改。选择系统模板后点击“复制为租户模板”，填写模板编码和名称；或点击“新建”创建租户模板。复制只生成副本，不会改变系统模板。' : 'SYSTEM templates are read-only. Select one and choose “Fork to tenant template”, then provide a code and name; or choose New to create a tenant template. Copying never changes the SYSTEM template.'}</p></section>
          <section><h3 className="font-semibold text-slate-900">{zh ? '二、填写模板' : '2. Fill in the template'}</h3><div className="mt-1 grid gap-2 sm:grid-cols-2"><div><b className="text-slate-800">Profile / parser_platform</b><br />{zh ? '先选目标平台 Profile；它决定解析平台键，必须与模板平台一致。' : 'Choose the target platform Profile first; it determines the parser key and must match the template platform.'}</div><div><b className="text-slate-800">template_code / name</b><br />{zh ? '编码是唯一标识（大写字母、数字、下划线），名称用于页面展示；两者都不是设备命令。' : 'The code is a unique identifier (A-Z, digits and underscores); the name is for display. Neither is a device command.'}</div><div><b className="text-slate-800">content</b><br />{zh ? 'TextFSM 规则通常由 Value 定义字段、Start 匹配行、Record 输出记录。' : 'TextFSM rules normally define fields with Value, match lines in Start, and emit records with Record.'}</div><div><b className="text-slate-800">field_contract</b><br />{zh ? '用 JSON 声明 required、optional 和 types，约束解析结果。' : 'Use JSON to declare required, optional and types for the parsed result.'}</div></div><pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-[10px] leading-4 text-slate-200">{'Value INTERFACE (\\S+)\nValue STATUS (up|down)\n\nStart\n  ^${INTERFACE}\\s+${STATUS} -> Record'}</pre></section>
          <section><h3 className="font-semibold text-slate-900">{zh ? '三、测试和保存' : '3. Test and save'}</h3><p className="mt-1">{zh ? '粘贴脱敏的设备 CLI 回显，点击 Sandbox 测试；确认 records、字段和类型正确后，草稿点击“保存修改”，已发布版本点击“创建草稿”生成新版本。系统模板只能只读测试。' : 'Paste redacted device CLI output and run Sandbox test. Save a draft with Save changes; for a published tenant version, choose Create draft to start a new version. SYSTEM templates are read-only.'}</p></section>
          <section><h3 className="font-semibold text-slate-900">{zh ? '四、发布版本' : '4. Release a version'}</h3><p className="mt-1">{zh ? '按“提交审核 → 审批 → 发布”推进版本。只有 PUBLISHED 版本可以被平台 Release 的命令映射引用。需要删除草稿时点击“删除模板”；若已被 Release 引用或有已发布版本，系统会阻止删除。' : 'Advance the version with Submit → Approve → Publish. Only PUBLISHED versions can be referenced by a platform Release mapping. Use Delete template for an unused draft; mappings or released versions block deletion.'}</p></section>
          <section className="rounded-xl border border-amber-100 bg-amber-50 p-3"><h3 className="font-semibold text-amber-950">{zh ? '五、命令和 Playbook 的关联' : '5. Bind the command to a Playbook'}</h3><p className="mt-1 text-amber-900">{zh ? '命令不在 TextFSM 页面填写。到“平台注册 → 平台 Profile → 命令映射”，为 action_code 绑定只读 command 和 PUBLISHED 的 parser_template_version_id；Playbook 只保存 action_code。' : 'The CLI command is not entered on this page. Go to Platform Registry → platform Profile → Command mappings and bind a read-only command plus the PUBLISHED parser_template_version_id; the Playbook stores only action_code.'}</p><code className="mt-2 block rounded-lg bg-white px-2 py-1.5 font-mono text-[10px] text-slate-700">action_code → command + parser_template_version_id</code></section>
        </div>
      </ResultStatusModal>
      <ResultStatusModal
        open={forkModalOpen}
        onClose={() => { if (!forking) setForkModalOpen(false); }}
        title={zh ? '复制为租户模板' : 'Fork to tenant template'}
        closeTitle={zh ? '关闭复制窗口' : 'Close Fork dialog'}
        icon={GitBranch}
        iconClassName="bg-amber-100 text-amber-700"
        headerClassName="border-b border-amber-100 bg-amber-50/70"
        panelClassName="w-full max-w-lg rounded-2xl shadow-2xl border border-amber-100 overflow-hidden bg-white"
        bodyClassName="p-5"
        closeDisabled={forking}
      >
        <form
          className="space-y-4"
          onSubmit={(event) => { event.preventDefault(); void forkSelectedTemplate(); }}
        >
          <div className="rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
            <div className="font-semibold text-slate-800">{selectedTemplate?.template_code || (zh ? '系统模板' : 'SYSTEM template')}</div>
            <div className="mt-1">{zh ? '复制为租户副本后，可在新模板中修改、测试并发布独立版本。' : 'The copied tenant template can be edited, tested, and released independently.'}</div>
          </div>
          <label className="block text-xs font-semibold text-slate-700">
            {zh ? '租户模板编码' : 'Tenant template code'}
            <input
              value={forkCode}
              onChange={(event) => setForkCode(event.target.value.toUpperCase())}
              maxLength={64}
              autoFocus
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 font-mono text-sm outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
              aria-label={zh ? '租户模板编码' : 'Tenant template code'}
            />
            <span className="mt-1 block text-[10px] font-normal text-slate-400">{zh ? 'A-Z 开头 · A-Z / 0-9 / _' : 'Starts with A-Z · A-Z / 0-9 / _'} · {forkCode.length}/64</span>
          </label>
          <label className="block text-xs font-semibold text-slate-700">
            {zh ? '租户模板名称' : 'Tenant template name'}
            <input
              value={forkName}
              onChange={(event) => setForkName(event.target.value)}
              maxLength={128}
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
              aria-label={zh ? '租户模板名称' : 'Tenant template name'}
            />
          </label>
          {forkModalError && <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">{forkModalError}</div>}
          <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <button type="button" onClick={() => setForkModalOpen(false)} disabled={forking} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100 disabled:opacity-50">{zh ? '取消' : 'Cancel'}</button>
            <button type="submit" disabled={forking} className="inline-flex items-center gap-1.5 rounded-xl bg-amber-500 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-amber-600 disabled:opacity-50">
              {forking && <Loader2 size={13} className="animate-spin" />}
              {forking ? (zh ? '复制中' : 'Forking') : (zh ? '确认复制' : 'Confirm Fork')}
            </button>
          </div>
        </form>
      </ResultStatusModal>
      <ResultStatusModal
        open={deleteModalOpen}
        onClose={() => { if (!deleting) setDeleteModalOpen(false); }}
        title={zh ? '删除租户模板' : 'Delete tenant template'}
        closeTitle={zh ? '关闭删除窗口' : 'Close delete dialog'}
        icon={Trash2}
        iconClassName="bg-rose-100 text-rose-700"
        headerClassName="border-b border-rose-100 bg-rose-50/70"
        panelClassName="w-full max-w-lg rounded-2xl border border-rose-100 bg-white shadow-2xl"
        bodyClassName="p-5"
        closeDisabled={deleting}
      >
        <div className="space-y-4">
          <div className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2.5 text-xs leading-5 text-rose-900">
            <div className="font-semibold">{selectedTemplate?.name || selectedTemplate?.template_code}</div>
            <div className="mt-1">{zh ? '只删除租户模板及其草稿、样例和审计数据；系统模板不会被删除。若模板已被 Release 引用或存在已发布版本，后端会阻止删除。' : 'This removes the tenant template and its drafts, samples and audit data. SYSTEM templates cannot be deleted; mappings or released versions must be removed first.'}</div>
          </div>
          {deleteModalError && <div className="rounded-xl border border-rose-200 bg-rose-100 px-3 py-2 text-xs text-rose-800">{deleteModalError}</div>}
          <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <button type="button" onClick={() => setDeleteModalOpen(false)} disabled={deleting} className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-100 disabled:opacity-50">{zh ? '取消' : 'Cancel'}</button>
            <button type="button" onClick={() => void deleteSelectedTemplate()} disabled={deleting} className="inline-flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-rose-700 disabled:opacity-50">
              {deleting && <Loader2 size={13} className="animate-spin" />}
              {deleting ? (zh ? '删除中' : 'Deleting') : (zh ? '确认删除' : 'Delete template')}
            </button>
          </div>
        </div>
      </ResultStatusModal>
    </div>
  );
};

export default ParserRegistryTab;
