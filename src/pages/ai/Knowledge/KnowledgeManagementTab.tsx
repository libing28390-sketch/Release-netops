import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import JSZip from 'jszip';
import {
  BookOpen,
  Database,
  Layers,
  ShieldCheck,
  Plus,
  Trash2,
  CheckCircle2,
  Upload,
  FileText,
  HelpCircle,
  Server,
  Sparkles,
  AlertTriangle,
  FileCode,
  Folder,
  FolderOpen,
  UploadCloud,
  File,
  Filter,
  Search,
  Archive,
  X,
  Loader2,
  PackageOpen,
  FileUp,
  CheckCircle,
  XCircle,
  Eye,
  RefreshCw,
  CalendarDays,
  ChevronRight,
  Pencil,
  Info,
} from 'lucide-react';
import { getKnowledgeStats, getKnowledgeDocuments, exportKnowledgeDocuments, importKnowledgeBundle, getKnowledgeDocument, getKnowledgeDocumentFacets, getKnowledgeAssetOptions, getKnowledgeDirectories, createKnowledgeDirectory, renameKnowledgeDirectory, deleteKnowledgeDirectory, addKnowledgeDocument, importKnowledgeOfficialUrl, importKnowledgeEnterpriseSop, importKnowledgeEnterpriseSopBatch, previewKnowledgeDocumentMetadata, clearSampleKnowledge, getKnowledgeDocumentActionImpact, deleteKnowledgeDocument, disableKnowledgeDocument, enableKnowledgeDocument, reparseKnowledgeDocument, rechunkKnowledgeDocument, reindexKnowledgeDocument, batchDeleteKnowledgeDocuments, compareKnowledgeDocumentVersions, publishKnowledgeDocumentVersion, supersedeKnowledgeDocumentVersion, rollbackKnowledgeDocumentVersion, type KnowledgeAssetOptionsResponse, type KnowledgeDirectoryNode, type KnowledgeDocument, type KnowledgeDocumentDetail, type KnowledgeDocumentFacets, type KnowledgeDocumentAction, type KnowledgeDocumentActionImpact, type KnowledgeDocumentVersionComparison, type KnowledgeMetadataPreview } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { VENDOR_PLATFORMS } from '../../AssetManagement/constants';
import SourceRegistryPanel from './SourceRegistryPanel';
import RagEvaluationPanel from './RagEvaluationPanel';
import RetrievalTracePanel from './RetrievalTracePanel';
import IngestionJobsPanel from './IngestionJobsPanel';
import KnowledgeAdminNavigation, { type KnowledgeAdminView } from './KnowledgeAdminNavigation';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';

/* ── Types ── */
interface FolderCategory {
  id: string;
  name: string;
  countKey?: string;
  icon: string;
  description: string;
}

type FileQueueStatus = 'pending' | 'reading' | 'indexing' | 'done' | 'error';
type KnowledgeScope = 'all' | 'official' | 'enterprise';

interface QueueMetadataPreview {
  vendor: string;
  platform: string;
  sourceType: string;
  directoryPath: string;
  validation: 'ready' | 'warning' | 'error';
  issue?: string;
}

interface FileQueueItem {
  id: string;
  fileName: string;
  fileSize: number;
  content: string;
  status: FileQueueStatus;
  error?: string;
  fromZip?: string; // original zip name if extracted
  relativePath?: string;
  directoryCategory?: string;
  directoryVendor?: string;
  directoryPath?: string;
  metadata?: Partial<QueueMetadataPreview>;
  binaryFile?: File;
}

/* ── Supported text extensions ── */
const TEXT_EXTENSIONS = ['.md', '.markdown', '.txt', '.html', '.htm', '.json', '.yaml', '.yml', '.log', '.csv', '.xml', '.conf', '.cfg', '.ini'];
const ALL_SUPPORTED_EXTENSIONS = [...TEXT_EXTENSIONS, '.docx', '.pdf', '.zip'];

const KNOWLEDGE_DIRECTORY_OPTIONS = [
  { id: '01_product', label: '01_product · 产品知识', description: '产品、架构、功能与版本说明' },
  { id: '02_commands', label: '02_commands · 命令参考', description: '命令语法、参数与使用说明' },
  { id: '03_configuration', label: '03_configuration · 配置流程', description: '配置方法、操作步骤与变更流程' },
  { id: '04_cli_outputs', label: '04_cli_outputs · CLI 输出', description: '验证命令、预期输出与表格' },
  { id: '05_troubleshooting', label: '05_troubleshooting · 故障排查', description: '症状、原因、解决方案与排障记录' },
  { id: '06_examples', label: '06_examples · 示例案例', description: '完整案例、Runbook 与操作示例' },
] as const;

const KNOWLEDGE_DIRECTORY_IDS: Set<string> = new Set(KNOWLEDGE_DIRECTORY_OPTIONS.map((item) => item.id));
const KNOWLEDGE_DIRECTORY_DISPLAY_LABELS: Record<string, string> = {
  '01_product': '01_product · 产品知识',
  '02_commands': '02_commands · 命令参考',
  '03_configuration': '03_configuration · 配置流程',
  '04_cli_outputs': '04_cli_outputs · CLI 输出',
  '05_troubleshooting': '05_troubleshooting · 故障排查',
  '06_examples': '06_examples · 示例案例',
};
const KNOWLEDGE_VENDOR_DIRECTORY_ALIASES: Record<string, string> = {
  huawei: 'huawei',
  华为: 'huawei',
  h3c: 'h3c',
  华三: 'h3c',
  cisco: 'cisco',
  思科: 'cisco',
  ruijie: 'ruijie',
  锐捷: 'ruijie',
};

function getKnowledgeDirectoryVendor(value: string): string {
  return KNOWLEDGE_VENDOR_DIRECTORY_ALIASES[String(value || '').trim().toLowerCase()] || '';
}

function getKnowledgeDirectoryDisplayName(node: KnowledgeDirectoryNode): string {
  return KNOWLEDGE_DIRECTORY_DISPLAY_LABELS[node.name] || node.name;
}

function inferKnowledgeDirectory(relativePath: string): { category?: string; vendor?: string; path?: string } {
  const segments = String(relativePath || '').replace(/\\/g, '/').split('/').filter(Boolean);
  const categoryIndex = segments.findIndex((segment) => KNOWLEDGE_DIRECTORY_IDS.has(segment));
  if (categoryIndex < 0) return {};
  const category = segments[categoryIndex];
  const vendor = getKnowledgeDirectoryVendor(segments[categoryIndex + 1] || '');
  const pathSegments = segments.slice(categoryIndex, Math.max(categoryIndex + 1, segments.length - 1));
  return { category, vendor: vendor || undefined, path: pathSegments.join('/') || category };
}

function getFileExtension(name: string): string {
  const idx = name.lastIndexOf('.');
  return idx >= 0 ? name.substring(idx).toLowerCase() : '';
}

function getFileNameWithoutExt(name: string): string {
  const idx = name.lastIndexOf('.');
  return idx >= 0 ? name.substring(0, idx) : name;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

const VENDOR_DISPLAY_LABELS: Record<string, string> = {
  Cisco: 'Cisco (思科)',
  Huawei: 'Huawei (华为)',
  H3C: 'H3C (华三)',
  Ruijie: 'Ruijie (锐捷)',
  ZTE: 'ZTE (中兴)',
  cisco: 'Cisco (思科)',
  huawei: 'Huawei (华为)',
  h3c: 'H3C (华三)',
  ruijie: 'Ruijie (锐捷)',
};

function getVendorDisplayLabel(vendor: string): string {
  return VENDOR_DISPLAY_LABELS[vendor] || vendor;
}

function getPlatformDisplayLabel(vendor: string, platform?: string | null): string {
  if (!platform || platform.toLowerCase() === 'all') return '通用（未指定 CLI 平台）';
  return VENDOR_PLATFORMS[vendor]?.find((item) => item.value === platform)?.label || platform;
}

interface DirectoryTreePickerProps {
  nodes: KnowledgeDirectoryNode[];
  selectedPath: string;
  loading: boolean;
  error?: string;
  disabled?: boolean;
  inline?: boolean;
  onUpload?: (node: KnowledgeDirectoryNode) => void;
  onSelect: (node: KnowledgeDirectoryNode) => void;
  onCreate: (name: string, parentId: string | null) => Promise<void>;
  onRename: (node: KnowledgeDirectoryNode, name: string) => Promise<void>;
  onDelete: (node: KnowledgeDirectoryNode) => Promise<void>;
}

const DirectoryTreePicker: React.FC<DirectoryTreePickerProps> = ({
  nodes,
  selectedPath,
  loading,
  error,
  disabled,
  inline = false,
  onUpload,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}) => {
  const [open, setOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [creatingParentId, setCreatingParentId] = useState<string | null | undefined>(undefined);
  const [draftName, setDraftName] = useState('');
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      nodes.forEach((node) => next.add(node.id));
      return next;
    });
  }, [nodes]);

  const beginCreate = (parentId: string | null) => {
    setOpen(true);
    setCreatingParentId(parentId);
    setDraftName('');
    setActionError('');
    setEditingNodeId(null);
  };

  const submitCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = draftName.trim();
    if (!name || creatingParentId === undefined) return;
    setBusyAction('create');
    setActionError('');
    try {
      await onCreate(name, creatingParentId);
      setCreatingParentId(undefined);
      setDraftName('');
    } catch (err: any) {
      setActionError(err?.message || '创建目录失败');
    } finally {
      setBusyAction(null);
    }
  };

  const beginRename = (node: KnowledgeDirectoryNode) => {
    setOpen(true);
    setCreatingParentId(undefined);
    setEditingNodeId(node.id);
    setEditingName(node.name);
    setActionError('');
  };

  const submitRename = async (event: React.FormEvent, node: KnowledgeDirectoryNode) => {
    event.preventDefault();
    const name = editingName.trim();
    if (!name) return;
    setBusyAction(`rename:${node.id}`);
    setActionError('');
    try {
      await onRename(node, name);
      setEditingNodeId(null);
    } catch (err: any) {
      setActionError(err?.message || '重命名目录失败');
    } finally {
      setBusyAction(null);
    }
  };

  const handleDelete = async (node: KnowledgeDirectoryNode) => {
    const hasChildren = node.children.length > 0;
    const message = hasChildren
      ? `确定删除目录“${node.name}”及其 ${countDirectoryNodes(node)} 个子目录吗？已入库文档不会被删除。`
      : `确定删除目录“${node.name}”吗？已入库文档不会被删除。`;
    if (!window.confirm(message)) return;
    setBusyAction(`delete:${node.id}`);
    setActionError('');
    try {
      await onDelete(node);
    } catch (err: any) {
      setActionError(err?.message || '删除目录失败');
    } finally {
      setBusyAction(null);
    }
  };

  const renderNode = (node: KnowledgeDirectoryNode): React.ReactNode => {
    const expanded = expandedIds.has(node.id);
    const selected = selectedPath === node.path;
    const editing = editingNodeId === node.id;
    const rowBusy = Boolean(busyAction && (busyAction === 'create' || busyAction.endsWith(`:${node.id}`)));
    return (
      <React.Fragment key={node.id}>
        <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: `${Math.min(node.depth, 8) * 14}px` }}>
          <button
            type="button"
            onClick={() => setExpandedIds((previous) => {
              const next = new Set(previous);
              if (next.has(node.id)) next.delete(node.id); else next.add(node.id);
              return next;
            })}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
            aria-label={expanded ? '收起子目录' : '展开子目录'}
          >
            {node.children.length > 0 ? <ChevronRight className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`} /> : <span className="w-3.5" />}
          </button>
          {editing ? (
            <form onSubmit={(event) => void submitRename(event, node)} className="flex min-w-0 flex-1 items-center gap-1">
              <input
                autoFocus
                value={editingName}
                onChange={(event) => setEditingName(event.target.value)}
                disabled={rowBusy}
                className="min-w-0 flex-1 rounded-lg border border-indigo-300 bg-white px-2 py-1 text-xs dark:border-indigo-700 dark:bg-gray-900 dark:text-white"
              />
              <button type="submit" disabled={rowBusy || !editingName.trim()} className="rounded-lg p-1 text-emerald-600 hover:bg-emerald-50 disabled:opacity-50 dark:hover:bg-emerald-950/40" title="保存重命名"><CheckCircle2 className="h-3.5 w-3.5" /></button>
              <button type="button" onClick={() => setEditingNodeId(null)} disabled={rowBusy} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700" title="取消"><X className="h-3.5 w-3.5" /></button>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => { onSelect(node); setOpen(false); }}
              disabled={disabled}
              className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition ${selected ? 'bg-indigo-50 font-semibold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300' : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'}`}
              title={`知识目录：${node.path}`}
            >
              {expanded ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-indigo-500" /> : <Folder className="h-3.5 w-3.5 shrink-0 text-indigo-400" />}
              <span className="truncate">{getKnowledgeDirectoryDisplayName(node)}</span>
            </button>
          )}
          {!editing && (
            <ActionIconGroup className="flex shrink-0 items-center gap-0.5" label="目录操作">
              {onUpload && (
                <ActionIconButton icon={UploadCloud} label="在此目录导入文件" size="xs" variant="success" onClick={() => onUpload(node)} disabled={disabled || Boolean(busyAction)} />
              )}
              <ActionIconButton icon={Plus} label="新建子目录" size="xs" variant="accent" onClick={() => beginCreate(node.id)} disabled={disabled || Boolean(busyAction)} />
              <ActionIconButton icon={Pencil} label="重命名目录" size="xs" onClick={() => beginRename(node)} disabled={disabled || Boolean(busyAction)} />
              <ActionIconButton icon={Trash2} label="删除目录" size="xs" variant="danger" onClick={() => void handleDelete(node)} disabled={disabled || Boolean(busyAction)} />
            </ActionIconGroup>
          )}
        </div>
        {editing && node.children.length > 0 && expanded && node.children.map(renderNode)}
        {!editing && expanded && node.children.map(renderNode)}
      </React.Fragment>
    );
  };

  const showTree = inline || open;
  return (
    <div className={inline ? '' : 'relative'}>
      {!inline && (
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          disabled={disabled}
          className="flex w-full items-center justify-between gap-2 rounded-xl border border-gray-300 bg-white px-3 py-2 text-left text-xs text-gray-700 shadow-sm transition hover:border-indigo-400 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-200"
        >
          <span className="flex min-w-0 items-center gap-2"><FolderOpen className="h-3.5 w-3.5 shrink-0 text-indigo-500" /><span className="truncate">{selectedPath ? `目录：${selectedPath}` : '请选择目录'}</span></span>
          <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-gray-400 transition-transform ${open ? 'rotate-90' : ''}`} />
        </button>
      )}
      {showTree && (
        <div className={inline ? 'overflow-hidden rounded-xl border border-gray-200 bg-white p-2 dark:border-gray-700 dark:bg-gray-800' : 'absolute left-0 right-0 z-40 mt-1 overflow-hidden rounded-xl border border-gray-200 bg-white p-2 shadow-xl dark:border-gray-700 dark:bg-gray-800'}>
          <div className="flex items-center justify-between gap-2 border-b border-gray-100 pb-2 dark:border-gray-700">
            <span className="text-[11px] font-semibold text-gray-700 dark:text-gray-200">目录树（选择导入位置）</span>
            <button type="button" onClick={() => beginCreate(null)} disabled={disabled || Boolean(busyAction)} className="inline-flex items-center gap-1 rounded-lg bg-indigo-50 px-2 py-1 text-[10px] font-semibold text-indigo-600 hover:bg-indigo-100 disabled:opacity-40 dark:bg-indigo-950/40 dark:text-indigo-300" title="新建根目录"><Plus className="h-3 w-3" />新建目录</button>
          </div>
          {creatingParentId !== undefined && (
            <form onSubmit={(event) => void submitCreate(event)} className="mt-2 rounded-lg border border-indigo-100 bg-indigo-50/60 p-2 dark:border-indigo-900/60 dark:bg-indigo-950/30">
              <div className="mb-1 text-[10px] text-indigo-700 dark:text-indigo-300">在 {creatingParentId ? '选定的子目录' : '根目录'} 下新建</div>
              <div className="flex items-center gap-1">
                <input autoFocus value={draftName} onChange={(event) => setDraftName(event.target.value)} placeholder="输入目录名称" disabled={busyAction === 'create'} className="min-w-0 flex-1 rounded-lg border border-indigo-200 bg-white px-2 py-1.5 text-xs dark:border-indigo-800 dark:bg-gray-900 dark:text-white" />
                <button type="submit" disabled={busyAction === 'create' || !draftName.trim()} className="rounded-lg bg-indigo-600 px-2 py-1.5 text-[10px] font-semibold text-white disabled:opacity-50">{busyAction === 'create' ? <Loader2 className="h-3 w-3 animate-spin" /> : '创建'}</button>
                <button type="button" onClick={() => setCreatingParentId(undefined)} disabled={busyAction === 'create'} className="rounded-lg p-1.5 text-gray-400 hover:bg-white dark:hover:bg-gray-700" title="取消"><X className="h-3.5 w-3.5" /></button>
              </div>
            </form>
          )}
          {(error || actionError) && <div className="mt-2 rounded-lg bg-red-50 px-2 py-1.5 text-[10px] text-red-600 dark:bg-red-950/30 dark:text-red-300">{actionError || error}</div>}
          <div className={`mt-2 overflow-y-auto pr-1 ${inline ? 'max-h-[430px]' : 'max-h-72'}`}>
            {loading ? <div className="flex items-center gap-2 px-2 py-5 text-xs text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />正在加载目录树…</div> : nodes.length === 0 ? <div className="px-2 py-5 text-center text-xs text-gray-400">暂无目录，请先新建目录</div> : nodes.map(renderNode)}
          </div>
        </div>
      )}
    </div>
  );
};

function countDirectoryNodes(node: KnowledgeDirectoryNode): number {
  return node.children.reduce((total, child) => total + 1 + countDirectoryNodes(child), 0);
}

function flattenDirectoryNodes(nodes: KnowledgeDirectoryNode[]): KnowledgeDirectoryNode[] {
  return nodes.flatMap((node) => [node, ...flattenDirectoryNodes(node.children)]);
}

function getDirectoryImportPath(directoryPath: string, vendor: string): string {
  const selectedPath = String(directoryPath || '').replace(/^\/+|\/+$/g, '');
  if (!selectedPath) return '全部知识目录';
  const hasVendorSegment = selectedPath.split('/').some((segment) => Boolean(getKnowledgeDirectoryVendor(segment)));
  const vendorSlug = getKnowledgeDirectoryVendor(vendor);
  const targetPath = !hasVendorSegment && vendorSlug ? `${selectedPath}/${vendorSlug}` : selectedPath;
  return targetPath.split('/').filter(Boolean).join(' / ');
}

export const KnowledgeManagementTab: React.FC = () => {
  const [stats, setStats] = useState({
    total_documents: 0,
    total_chunks: 0,
    total_vendors: 0,
    ready_indexes: 0,
  });

  const [selectedFolder, setSelectedFolder] = useState<string>('all');
  const [knowledgeScope, setKnowledgeScope] = useState<KnowledgeScope>('all');
  const [selectedDirectoryPath, setSelectedDirectoryPath] = useState('');
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [documentFacets, setDocumentFacets] = useState<KnowledgeDocumentFacets>({ vendors: [], families: [], series: [] });
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(20);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [semanticFilters, setSemanticFilters] = useState({
    vendor: '',
    productFamily: '',
    productSeries: '',
    productModel: '',
    osFamily: '',
    softwareRelease: '',
    featureDomain: '',
    documentCategory: '',
    status: 'active',
  });

  // Modal & File Upload State
  const [showModal, setShowModal] = useState(false);
  const [ingestionMode, setIngestionMode] = useState<'official_url' | 'enterprise_sop' | null>(null);
  const [ingestionSubmitting, setIngestionSubmitting] = useState(false);
  const [ingestionError, setIngestionError] = useState('');
  const [ingestionMessage, setIngestionMessage] = useState('');
  const [officialUrl, setOfficialUrl] = useState('');
  const [officialVendor, setOfficialVendor] = useState('Huawei');
  const [officialFamily, setOfficialFamily] = useState('');
  const [officialVersion, setOfficialVersion] = useState('');
  const [officialCompatibilityVersion, setOfficialCompatibilityVersion] = useState('');
  const [officialName, setOfficialName] = useState('');
  const [officialTerms, setOfficialTerms] = useState('pending');
  const [enterpriseSopFile, setEnterpriseSopFile] = useState<File | null>(null);
  const [enterpriseTitle, setEnterpriseTitle] = useState('');
  const [enterpriseOwner, setEnterpriseOwner] = useState('');
  const [enterpriseDepartment, setEnterpriseDepartment] = useState('');
  const [inputMode, setInputMode] = useState<'upload' | 'paste'>('upload');
  const [docName, setDocName] = useState('');
  const [content, setContent] = useState('');
  const [vendor, setVendor] = useState('');
  const [platform, setPlatform] = useState('');
  const [knowledgeDirectory, setKnowledgeDirectory] = useState('01_product');
  const [directoryTree, setDirectoryTree] = useState<KnowledgeDirectoryNode[]>([]);
  const [directoryTreeLoading, setDirectoryTreeLoading] = useState(false);
  const [directoryTreeError, setDirectoryTreeError] = useState('');
  const [directUploadStatus, setDirectUploadStatus] = useState<{
    directoryPath: string;
    phase: 'processing' | 'uploading' | 'success' | 'error';
    completed: number;
    total: number;
    message: string;
  } | null>(null);
  const [directUploading, setDirectUploading] = useState(false);
  const [sourceType, setSourceType] = useState('internal_sop');
  const [indexingStep, setIndexingStep] = useState<number>(0);
  const [submitting, setSubmitting] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  // Multi-file queue
  const [fileQueue, setFileQueue] = useState<FileQueueItem[]>([]);
  const [bundleFiles, setBundleFiles] = useState<File[]>([]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: 0 });
  const [assetOptions, setAssetOptions] = useState<KnowledgeAssetOptionsResponse>({
    source: 'physical_assets',
    asset_count: 0,
    vendors: [],
  });
  const [assetOptionsLoading, setAssetOptionsLoading] = useState(false);
  const [assetOptionsError, setAssetOptionsError] = useState('');

  // Document selection for batch delete
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [documentActionBusy, setDocumentActionBusy] = useState<string | null>(null);
  const [documentActionNotice, setDocumentActionNotice] = useState('');
  const [pendingDocumentAction, setPendingDocumentAction] = useState<{
    doc: KnowledgeDocument;
    action: KnowledgeDocumentAction;
    preview: KnowledgeDocumentActionImpact;
  } | null>(null);

  // Document viewer state
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocumentDetail | null>(null);
  const [documentDetailLoading, setDocumentDetailLoading] = useState(false);
  const [documentDetailError, setDocumentDetailError] = useState('');
  const [versionAdminBusy, setVersionAdminBusy] = useState<string | null>(null);
  const [versionAdminNotice, setVersionAdminNotice] = useState('');
  const [versionCompareResult, setVersionCompareResult] = useState<KnowledgeDocumentVersionComparison | null>(null);
  const [knowledgeAdminView, setKnowledgeAdminView] = useState<KnowledgeAdminView>('documents');

  const fileInputRef = useRef<HTMLInputElement>(null);
  const quickUploadInputRef = useRef<HTMLInputElement>(null);
  const directUploadTargetRef = useRef<KnowledgeDirectoryNode | null>(null);
  const documentsRequestIdRef = useRef(0);
  const documentDetailRequestIdRef = useRef(0);
  const documentsAbortRef = useRef<AbortController | null>(null);

  const folders: FolderCategory[] = [
    { id: 'all', name: '全部知识文档', icon: '📂', description: '汇总展示所有目录与厂商知识底座' },
    { id: 'internal_sop', name: '企业内部 SOP', icon: '📘', description: '标准化变更与日常运维指导手册' },
    { id: 'official_vendor', name: '厂商官方资料', icon: '🏢', description: 'Huawei / Cisco / H3C / Ruijie 官方资料' },
    { id: 'internal_standard', name: '企业规范标准', icon: '📜', description: 'IP 划分子网、VLAN 命名与安全基线规范' },
    { id: 'case', name: '应急处置与排查案例', icon: '🚨', description: '历史重大故障与 Emergency Runbook' },
    { id: 'sample', name: '系统初始化示例', icon: '🧪', description: '系统自带演示文档' },
  ];

  const directoryVendorOptions = useMemo(
    () => assetOptions.vendors.filter((item) => Boolean(getKnowledgeDirectoryVendor(item.value))),
    [assetOptions.vendors],
  );

  const knowledgeVendorOptions = useMemo(
    () => (documentFacets?.vendors || []).filter((item) => item.value && item.value !== 'UNKNOWN'),
    [documentFacets?.vendors],
  );

  const fetchStatsAndDocs = useCallback(async () => {
    const requestId = ++documentsRequestIdRef.current;
    documentsAbortRef.current?.abort();
    const controller = new AbortController();
    documentsAbortRef.current = controller;
    setLoading(true);
    setLoadError('');
    setPermissionDenied(false);
    try {
      const [s, docsPage, facets] = await Promise.all([
        getKnowledgeStats(controller.signal),
        getKnowledgeDocuments({
          sourceType: selectedFolder === 'all' ? undefined : selectedFolder,
          knowledgeScope,
          directoryPath: selectedDirectoryPath || undefined,
          search: searchQuery,
          ...semanticFilters,
          page: currentPage,
          pageSize: itemsPerPage,
          signal: controller.signal,
        }),
        getKnowledgeDocumentFacets({
          sourceType: selectedFolder === 'all' ? undefined : selectedFolder,
          knowledgeScope,
          directoryPath: selectedDirectoryPath || undefined,
          status: semanticFilters.status,
          signal: controller.signal,
        }),
      ]);
      if (requestId !== documentsRequestIdRef.current) return;
      setStats(s);
      setDocuments(docsPage.items);
      setTotalDocuments(docsPage.total);
      setDocumentFacets(facets);
      setCurrentPage((page) => page === docsPage.page ? page : docsPage.page);
    } catch (e: any) {
      if (requestId !== documentsRequestIdRef.current) return;
      if (e?.name === 'AbortError') return;
      const denied = Number(e?.status) === 403;
      setPermissionDenied(denied);
      setLoadError(denied ? '当前账号没有知识库查看权限。' : (e?.message || '知识文档加载失败，请重试'));
      console.error('Failed to load knowledge metrics:', e);
    } finally {
      if (requestId === documentsRequestIdRef.current) setLoading(false);
    }
  }, [currentPage, itemsPerPage, knowledgeScope, searchQuery, selectedDirectoryPath, selectedFolder, semanticFilters]);

  useEffect(() => {
    void fetchStatsAndDocs();
  }, [fetchStatsAndDocs]);

  useEffect(() => () => {
    documentsAbortRef.current?.abort();
  }, []);

  const handleKnowledgeExport = useCallback(async () => {
    if (exporting) return;
    setExporting(true);
    setDocumentActionNotice('');
    try {
      const exported = await exportKnowledgeDocuments({
        sourceType: selectedFolder === 'all' ? undefined : selectedFolder,
        knowledgeScope,
        directoryPath: selectedDirectoryPath || undefined,
        search: searchQuery,
        vendor: semanticFilters.vendor,
        productFamily: semanticFilters.productFamily,
        productSeries: semanticFilters.productSeries,
        productModel: semanticFilters.productModel,
        osFamily: semanticFilters.osFamily,
        softwareRelease: semanticFilters.softwareRelease,
        documentCategory: semanticFilters.documentCategory,
        featureDomain: semanticFilters.featureDomain,
        status: semanticFilters.status,
      });
      const url = URL.createObjectURL(exported.blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = exported.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setDocumentActionNotice(`已导出 ${exported.documentCount} 篇文档（${formatFileSize(exported.contentBytes)}）。ZIP 内含 Markdown 与 manifest，导入时会重新切片和生成向量。`);
    } catch (error: any) {
      setDocumentActionNotice(error?.message || '知识库导出失败');
    } finally {
      setExporting(false);
    }
  }, [exporting, knowledgeScope, searchQuery, selectedDirectoryPath, selectedFolder, semanticFilters]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearchQuery(searchInput.trim());
      setCurrentPage(1);
      setSelectedDocIds(new Set());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const loadAssetOptions = useCallback(async () => {
    setAssetOptionsLoading(true);
    setAssetOptionsError('');
    try {
      setAssetOptions(await getKnowledgeAssetOptions());
    } catch (error: any) {
      setAssetOptions({ source: 'physical_assets', asset_count: 0, vendors: [] });
      setAssetOptionsError(error?.message || '资产厂商同步失败');
    } finally {
      setAssetOptionsLoading(false);
    }
  }, []);

  const loadKnowledgeDirectories = useCallback(async (): Promise<KnowledgeDirectoryNode[]> => {
    setDirectoryTreeLoading(true);
    setDirectoryTreeError('');
    try {
      const response = await getKnowledgeDirectories();
      const items = response.items || [];
      setDirectoryTree(items);
      const flattened = flattenDirectoryNodes(items);
      setKnowledgeDirectory((current) => flattened.some((node) => node.path === current) ? current : (flattened[0]?.path || ''));
      return items;
    } catch (error: any) {
      setDirectoryTreeError(error?.message || '目录树加载失败');
      return [];
    } finally {
      setDirectoryTreeLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAssetOptions();
  }, [loadAssetOptions]);

  useEffect(() => {
    void loadKnowledgeDirectories();
  }, [loadKnowledgeDirectories]);

  useEffect(() => {
    if (!showModal || assetOptionsLoading || directoryVendorOptions.length === 0) return;
    const nextVendor = directoryVendorOptions.some((item) => item.value === vendor)
      ? vendor
      : directoryVendorOptions[0].value;
    const nextVendorOption = directoryVendorOptions.find((item) => item.value === nextVendor);
    setVendor((current) => current === nextVendor ? current : nextVendor);
    setPlatform((current) => (
      nextVendorOption?.platforms.some((item) => item.value === current)
        ? current
        : nextVendorOption?.platforms[0]?.value || ''
    ));
  }, [assetOptionsLoading, directoryVendorOptions, showModal, vendor]);

  /* ── Read a single text file to string ── */
  const readFileAsText = (file: File | Blob): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => resolve((e.target?.result as string) || '');
      reader.onerror = () => reject(new Error('文件读取失败'));
      reader.readAsText(file);
    });
  };

  /* ── Extract ZIP and return individual FileQueueItems ── */
  const extractZipFiles = async (file: File): Promise<FileQueueItem[]> => {
    const zip = await JSZip.loadAsync(file);
    const items: FileQueueItem[] = [];

    // Validate Nexora's control-plane manifest before accepting the bundle.
    // Generic ZIPs without this manifest remain supported, but a malformed
    // Nexora export must fail closed instead of importing a partial corpus.
    const manifestEntry = Object.entries(zip.files).find(([path, entry]) => (
      !entry.dir && path.split('/').pop()?.toLowerCase() === 'manifest.json'
    ));
    let manifest: any = null;
    if (manifestEntry) {
      try {
        manifest = JSON.parse(await manifestEntry[1].async('string'));
      } catch {
        throw new Error('知识库导出包的 manifest.json 无法解析');
      }
      if (String(manifest?.schema_version || '').startsWith('knowledge-export-')) {
        if (manifest?.embeddings_exported === true || manifest?.reindex_required_on_import !== true) {
          throw new Error('知识库导出包缺少可移植的重建索引标记');
        }
        if (!Array.isArray(manifest?.documents)) {
          throw new Error('知识库导出包缺少 documents 清单');
        }
      }
    }

    for (const [relativePath, zipEntry] of Object.entries(zip.files)) {
      if (zipEntry.dir) continue;
      // skip hidden/system files
      const segments = relativePath.split('/');
      if (segments.some(s => s === '..') || relativePath.startsWith('/')) {
        throw new Error('ZIP 中包含不安全的目录路径');
      }
      if (segments.some(s => s.startsWith('.'))) continue;
      // A Nexora export ZIP carries a control-plane manifest alongside the
      // Markdown sources.  The manifest is not knowledge content and must not
      // become an accidental RAG document on round-trip import.
      if (segments[segments.length - 1].toLowerCase() === 'manifest.json') continue;

      const ext = getFileExtension(relativePath);
      if (!TEXT_EXTENSIONS.includes(ext)) continue;

      try {
        const textContent = await zipEntry.async('string');
        if (!textContent.trim()) continue;

        const baseName = segments[segments.length - 1];
        const inferredDirectory = inferKnowledgeDirectory(relativePath);
        items.push({
          id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
          fileName: baseName,
          fileSize: textContent.length,
          content: textContent,
          status: 'pending',
          fromZip: file.name,
          relativePath,
          directoryCategory: inferredDirectory.category,
          directoryVendor: inferredDirectory.vendor,
          directoryPath: inferredDirectory.path,
        });
      } catch {
        // skip binary/corrupted entries silently
      }
    }
    if (manifest && String(manifest?.schema_version || '').startsWith('knowledge-export-')) {
      const expected = Number(manifest.document_count || 0);
      if (Number.isFinite(expected) && expected !== items.length) {
        throw new Error(`知识库导出包文档数量不一致：清单 ${expected}，可导入 ${items.length}`);
      }
    }
    return items;
  };

  /* ── Process multiple files (including ZIPs) into the queue ── */
  const processFiles = useCallback(async (files: FileList | File[]): Promise<FileQueueItem[]> => {
    const newItems: FileQueueItem[] = [];

    for (const file of Array.from(files)) {
      const ext = getFileExtension(file.name);

      if (ext === '.zip') {
        // Keep the original bundle for the server-side atomic import.  The
        // client extraction remains a preview only; it must not perform a
        // document-by-document commit on the normal knowledge upload path.
        setBundleFiles((current) => [...current, file]);
        try {
          const zipItems = await extractZipFiles(file);
          if (zipItems.length === 0) {
            newItems.push({
              id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
              fileName: file.name,
              fileSize: file.size,
              content: '',
              status: 'error',
              error: 'ZIP 中没有可识别的文本文件',
              fromZip: undefined,
            });
          } else {
            newItems.push(...zipItems);
          }
        } catch (error: any) {
          newItems.push({
            id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
            fileName: file.name,
            fileSize: file.size,
            content: '',
            status: 'error',
            error: error?.message || 'ZIP 解压失败，文件可能已损坏',
          });
        }
      } else if (TEXT_EXTENSIONS.includes(ext)) {
        try {
          const text = await readFileAsText(file);
          newItems.push({
            id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
            fileName: file.name,
            fileSize: file.size,
            content: text,
            status: 'pending',
          });
        } catch {
          newItems.push({
            id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
            fileName: file.name,
            fileSize: file.size,
            content: '',
            status: 'error',
            error: '文件读取失败',
          });
        }
      } else if (ext === '.pdf' || ext === '.docx') {
        // Binary files remain opaque in the browser and are submitted to the
        // governed server-side parser as a batch job.
        newItems.push({
          id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
          fileName: file.name,
          fileSize: file.size,
          content: '',
          status: 'pending',
          binaryFile: file,
        });
      } else {
        newItems.push({
          id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
          fileName: file.name,
          fileSize: file.size,
          content: '',
          status: 'error',
          error: `不支持的文件格式：${ext || '无扩展名'}`,
        });
      }
    }

    setFileQueue(prev => [...prev, ...newItems]);
    return newItems;
  }, []);

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files);
      // Reset input so same files can be re-selected
      e.target.value = '';
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processFiles(e.dataTransfer.files);
    }
  };

  const removeFromQueue = (id: string) => {
    setFileQueue(prev => prev.filter(item => item.id !== id));
  };

  const clearQueue = () => {
    setFileQueue([]);
    setBundleFiles([]);
  };

  const handleQuickUploadInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files ? Array.from(event.target.files) : [];
    const target = directUploadTargetRef.current;
    event.target.value = '';
    if (!target || files.length === 0) return;

    setDirectUploading(true);
    setDirectUploadStatus({
      directoryPath: target.path,
      phase: 'processing',
      completed: 0,
      total: files.length,
      message: `正在读取 ${files.length} 个文件…`,
    });
    void processFiles(files)
      .then((items) => submitDirectDirectoryUpload(target, items))
      .catch((error: any) => {
        setDirectUploading(false);
        setDirectUploadStatus({
          directoryPath: target.path,
          phase: 'error',
          completed: 0,
          total: files.length,
          message: error?.message || '文件读取失败，请重试。',
        });
      });
  };

  const handleDirectoryUpload = (node: KnowledgeDirectoryNode) => {
    if (batchSubmitting || submitting || directUploading) return;
    directUploadTargetRef.current = node;
    setKnowledgeDirectory(node.path);
    setSelectedDirectoryPath(node.path);
    setFileQueue([]);
    setBundleFiles([]);
    setBatchProgress({ done: 0, total: 0 });
    // This input is always mounted, so the directory action opens the native
    // picker directly. There is deliberately no second upload modal.
    quickUploadInputRef.current?.click();
  };

  const handleCreateDirectory = async (name: string, parentId: string | null) => {
    const created = await createKnowledgeDirectory({ name, parent_id: parentId });
    await loadKnowledgeDirectories();
    setKnowledgeDirectory(created.path);
    setSelectedDirectoryPath(created.path);
  };

  const handleRenameDirectory = async (node: KnowledgeDirectoryNode, name: string) => {
    const renamed = await renameKnowledgeDirectory(node.id, name);
    await loadKnowledgeDirectories();
    setKnowledgeDirectory((current) => {
      if (current === node.path) return renamed.path;
      if (current.startsWith(`${node.path}/`)) return `${renamed.path}${current.substring(node.path.length)}`;
      return current;
    });
    setSelectedDirectoryPath((current) => {
      if (current === node.path) return renamed.path;
      if (current.startsWith(`${node.path}/`)) return `${renamed.path}${current.substring(node.path.length)}`;
      return current;
    });
  };

  const handleDeleteDirectory = async (node: KnowledgeDirectoryNode) => {
    await deleteKnowledgeDirectory(node.id);
    await loadKnowledgeDirectories();
    setKnowledgeDirectory((current) => {
      if (current === node.path || current.startsWith(`${node.path}/`)) return '';
      return current;
    });
    setSelectedDirectoryPath((current) => (
      current === node.path || current.startsWith(`${node.path}/`) ? '' : current
    ));
  };

  const closeModal = () => {
    if (batchSubmitting || submitting) return;
    setShowModal(false);
    clearQueue();
  };

  const closeIngestionPanel = () => {
    if (ingestionSubmitting) return;
    setIngestionMode(null);
    setIngestionError('');
    setIngestionMessage('');
  };

  const handleOfficialUrlImport = async (event: React.FormEvent) => {
    event.preventDefault();
    setIngestionError('');
    setIngestionMessage('');
    if (!officialUrl.trim().toLowerCase().startsWith('https://')) {
      setIngestionError('官方来源必须使用 HTTPS URL，并由 Source Registry 做域名与重定向校验。');
      return;
    }
    if (!officialFamily.trim() || !officialVersion.trim() || !officialCompatibilityVersion.trim() || officialTerms !== 'approved') {
      setIngestionError('请填写 Product Family、主版本、兼容版本，并确认官方条款已审核。');
      return;
    }
    setIngestionSubmitting(true);
    try {
      await importKnowledgeOfficialUrl({
        url: officialUrl.trim(),
        source_kind: 'product_page',
        vendor: officialVendor,
        product_family: officialFamily.trim(),
        version_scope: { primary: officialVersion.trim(), compatibility: officialCompatibilityVersion.trim() },
        terms_review_status: 'approved',
        publish_to_knowledge_base: true,
        name: officialName.trim(),
      });
      setIngestionMessage('官方来源导入任务已提交，后续状态由 Ingestion Job 管理。');
      setOfficialUrl('');
      setOfficialFamily('');
      setOfficialVersion('');
      setOfficialCompatibilityVersion('');
      await fetchStatsAndDocs();
    } catch (error: any) {
      setIngestionError(error?.message || '官方来源导入失败');
    } finally {
      setIngestionSubmitting(false);
    }
  };

  const handleEnterpriseSopImport = async (event: React.FormEvent) => {
    event.preventDefault();
    setIngestionError('');
    setIngestionMessage('');
    if (!enterpriseSopFile) {
      setIngestionError('请选择一个企业 SOP 文件。');
      return;
    }
    if (!enterpriseTitle.trim() || !enterpriseOwner.trim() || !enterpriseDepartment.trim()) {
      setIngestionError('企业 SOP 必须填写标题、负责人和所属部门。');
      return;
    }
    if (enterpriseSopFile.size > 20_000_000) {
      setIngestionError('企业 SOP 文件不能超过 20 MB。');
      return;
    }
    setIngestionSubmitting(true);
    try {
      await importKnowledgeEnterpriseSop(enterpriseSopFile, {
        title: enterpriseTitle.trim(),
        owner: enterpriseOwner.trim(),
        department: enterpriseDepartment.trim(),
      });
      setIngestionMessage('企业 SOP 导入任务已提交；分类已由服务端固定为 INTERNAL。');
      setEnterpriseSopFile(null);
      setEnterpriseTitle('');
      setEnterpriseOwner('');
      setEnterpriseDepartment('');
      await fetchStatsAndDocs();
    } catch (error: any) {
      setIngestionError(error?.message || '企业 SOP 导入失败');
    } finally {
      setIngestionSubmitting(false);
    }
  };

  const selectedVendorOption = directoryVendorOptions.find((item) => item.value === vendor);

  const getQueueMetadataPreview = (item: FileQueueItem): QueueMetadataPreview => {
    const directoryPath = item.metadata?.directoryPath || item.directoryPath || knowledgeDirectory || '未指定目录';
    const inferredSlug = item.directoryVendor || directoryPath.split('/').map((segment) => getKnowledgeDirectoryVendor(segment)).find(Boolean) || '';
    const inferredOption = inferredSlug
      ? directoryVendorOptions.find((option) => getKnowledgeDirectoryVendor(option.value) === inferredSlug)
      : undefined;
    const selectedVendor = item.metadata?.vendor || inferredOption?.value || vendor;
    const selectedOption = directoryVendorOptions.find((option) => option.value === selectedVendor);
    const selectedPlatform = item.metadata?.platform
      || (selectedVendor === vendor ? platform : selectedOption?.platforms[0]?.value || '');
    const selectedSourceType = item.metadata?.sourceType || sourceType;
    let validation: QueueMetadataPreview['validation'] = 'ready';
    let issue = '';
    if (inferredSlug && !inferredOption) {
      validation = 'error';
      issue = `目录厂商 ${inferredSlug} 尚未同步到资产选项`;
    } else if (inferredSlug && getKnowledgeDirectoryVendor(selectedVendor) !== inferredSlug) {
      validation = 'error';
      issue = `目录厂商为 ${inferredSlug}，当前 Metadata 却选择 ${selectedVendor || '未选择'}`;
    } else if (!selectedVendor || !selectedPlatform) {
      validation = 'error';
      issue = '必须为每个文件选择可用 Vendor 和 CLI Platform';
    } else if (!inferredSlug) {
      validation = 'warning';
      issue = '未从文件路径推断厂商，将使用当前行选择的 Metadata';
    }
    return { vendor: selectedVendor, platform: selectedPlatform, sourceType: selectedSourceType, directoryPath, validation, issue };
  };

  const updateQueueMetadata = (id: string, field: 'vendor' | 'platform' | 'sourceType', value: string) => {
    setFileQueue((items) => items.map((item) => (
      item.id === id ? { ...item, error: undefined, metadata: { ...item.metadata, [field]: value } } : item
    )));
  };

  const buildKnowledgeMetadata = (overrides?: {
    category?: string;
    vendorSlug?: string;
    fileName?: string;
    relativePath?: string;
    directoryPath?: string;
  }): Record<string, unknown> => {
    const selectedPath = overrides?.directoryPath || knowledgeDirectory;
    const category = overrides?.category || selectedPath.split('/')[0] || knowledgeDirectory;
    const pathVendor = selectedPath.split('/').map((segment) => getKnowledgeDirectoryVendor(segment)).find(Boolean) || '';
    const vendorSlug = pathVendor || overrides?.vendorSlug || getKnowledgeDirectoryVendor(vendor);
    const targetPath = selectedPath && pathVendor ? selectedPath : (selectedPath && vendorSlug ? `${selectedPath}/${vendorSlug}` : selectedPath);
    return {
      knowledge_directory: category,
      knowledge_directory_vendor: vendorSlug || null,
      // Store a semantic directory reference.  The historical kb_import
      // prefix is a server storage detail and must never be exposed as user
      // metadata or copied into a new document.
      knowledge_directory_path: targetPath || null,
      source_file_name: overrides?.fileName || null,
      source_relative_path: overrides?.relativePath || null,
    };
  };

  const submitDirectDirectoryUpload = async (node: KnowledgeDirectoryNode, items: FileQueueItem[]) => {
    const pendingItems = items.filter((item) => item.status === 'pending' && item.content.trim());
    if (pendingItems.length === 0) {
      setDirectUploading(false);
      setDirectUploadStatus({
        directoryPath: node.path,
        phase: 'error',
        completed: 0,
        total: items.length,
        message: '没有可导入的文件：ZIP 中未找到可识别的文本文件，或文件读取失败。',
      });
      return;
    }

    const vendorSlug = node.path
      .split('/')
      .map((segment) => getKnowledgeDirectoryVendor(segment))
      .find(Boolean) || '';
    const directVendor = vendorSlug === 'huawei'
      ? 'Huawei'
      : vendorSlug === 'h3c'
      ? 'H3C'
      : vendorSlug === 'cisco'
      ? 'Cisco'
      : vendorSlug === 'ruijie'
      ? 'Ruijie'
      : 'all';

    const directCandidates = pendingItems.map((item) => ({
      key: item.id,
      label: item.fileName,
      name: getFileNameWithoutExt(item.fileName),
      content: item.content.trim(),
      vendor: directVendor,
      platform: null,
      knowledge_source_type: 'user_document',
      metadata: buildKnowledgeMetadata({
        category: node.path.split('/')[0] || node.path,
        vendorSlug,
        directoryPath: node.path,
        fileName: item.fileName,
        relativePath: item.relativePath,
      }),
    }));
    const directPreviews = await previewAndConfirmMetadata(directCandidates, (key, message) => {
      setFileQueue((items) => items.map((item) => item.id === key ? { ...item, error: message } : item));
    });
    if (!directPreviews) return;

    setDirectUploading(true);
    setDirectUploadStatus({
      directoryPath: node.path,
      phase: 'uploading',
      completed: 0,
      total: pendingItems.length,
      message: `正在导入到目录：${node.path}…`,
    });

    let completed = 0;
    const failures: string[] = [];
    for (const item of pendingItems) {
      try {
        const metadata = buildKnowledgeMetadata({
          category: node.path.split('/')[0] || node.path,
          vendorSlug,
          directoryPath: node.path,
          fileName: item.fileName,
          relativePath: item.relativePath,
        });
        const metadataPreview = directPreviews.get(item.id);
        if (!metadataPreview) throw new Error('Metadata 预览已失效，请重新提交');
        await addKnowledgeDocument({
          name: getFileNameWithoutExt(item.fileName),
          content: item.content.trim(),
          vendor: directVendor,
          knowledge_source_type: 'user_document',
          metadata,
          metadata_confirmation_token: metadataPreview.confirmation_token,
          metadata_confirmed: true,
        });
        completed += 1;
      } catch (error: any) {
        failures.push(`${item.fileName}: ${error?.message || '入库失败'}`);
      }
      setDirectUploadStatus({
        directoryPath: node.path,
        phase: 'uploading',
        completed,
        total: pendingItems.length,
        message: `正在导入到目录：${node.path}（${completed}/${pendingItems.length}）`,
      });
    }

    setDirectUploading(false);
    setFileQueue([]);
    setBundleFiles([]);
    await fetchStatsAndDocs();
    if (failures.length > 0) {
      setDirectUploadStatus({
        directoryPath: node.path,
        phase: 'error',
        completed,
        total: pendingItems.length,
        message: `已导入 ${completed}/${pendingItems.length} 个文件；失败：${failures.join('；')}`,
      });
      return;
    }
    setDirectUploadStatus({
      directoryPath: node.path,
      phase: 'success',
      completed,
      total: pendingItems.length,
      message: `已将 ${completed} 个文件导入目录：${node.path}。`,
    });
  };

  const ensureAssetMetadataSelection = () => {
    if (knowledgeDirectory && vendor && platform) return true;
    window.alert(assetOptionsError || '请先在资产管理中导入网络设备，系统将同步厂商和平台后再导入知识文件。');
    return false;
  };

  type MetadataPreviewCandidate = {
    key: string;
    label: string;
    name: string;
    content: string;
    vendor: string;
    platform?: string | null;
    knowledge_source_type: string;
    metadata: Record<string, unknown>;
  };

  /**
   * ING-021 gate: ask the server to normalize every candidate, show a
   * bounded, redacted summary to the operator, and only then return tokens
   * that are bound to the exact bytes/metadata that will be imported.
   */
  const previewAndConfirmMetadata = async (
    candidates: MetadataPreviewCandidate[],
    onPreviewError?: (key: string, message: string) => void,
  ): Promise<Map<string, KnowledgeMetadataPreview> | null> => {
    const previews: Array<{ candidate: MetadataPreviewCandidate; preview: KnowledgeMetadataPreview }> = [];
    for (const candidate of candidates) {
      try {
        const preview = await previewKnowledgeDocumentMetadata({
          name: candidate.name,
          content: candidate.content,
          vendor: candidate.vendor,
          platform: candidate.platform,
          knowledge_source_type: candidate.knowledge_source_type,
          metadata: candidate.metadata,
        });
        previews.push({ candidate, preview });
      } catch (error: any) {
        const message = error?.message || '服务端 Metadata 预览失败';
        onPreviewError?.(candidate.key, message);
        return null;
      }
    }
    if (previews.length === 0) return null;
    const visibleRows = previews.slice(0, 8).map(({ candidate, preview }) => {
      const normalized = preview.normalized;
      const warning = preview.warnings.length > 0 ? `；提示 ${preview.warnings.length} 项` : '';
      return `${candidate.label}: 格式=${normalized.format || 'markdown'} / Parser=${normalized.parser_name || 'legacy'} / Vendor=${normalized.vendor || 'UNKNOWN'} / Platform=${normalized.platform || 'UNKNOWN'} / 状态=${normalized.metadata_parse_status}${warning}`;
    });
    const remainder = previews.length > visibleRows.length ? `\n其余 ${previews.length - visibleRows.length} 个文件已在同一服务端预览中校验。` : '';
    const confirmed = window.confirm(
      `导入前 Metadata 预览（${previews.length} 个文件）\n\n${visibleRows.join('\n')}${remainder}\n\n确认以上规范化 Metadata，并继续导入？`,
    );
    if (!confirmed) return null;
    return new Map(previews.map(({ candidate, preview }) => [candidate.key, preview]));
  };

  /* ── Batch submit all pending files ── */
  const handleBatchSubmit = async () => {
    if (bundleFiles.length > 0) {
      if (bundleFiles.length !== 1) {
        window.alert('一次只能原子导入一个 Nexora 导出 ZIP；请先清空队列后再选择。');
        return;
      }
      const bundle = bundleFiles[0];
      setBatchSubmitting(true);
      setBatchProgress({ done: 0, total: 1 });
      try {
        const result = await importKnowledgeBundle(bundle);
        const imported = Number(result?.data?.document_count || 0);
        setFileQueue((items) => items.map((item) => (
          item.fromZip === bundle.name ? { ...item, status: 'done' as FileQueueStatus, error: undefined } : item
        )));
        setBatchProgress({ done: 1, total: 1 });
        setDocumentActionNotice(`已原子导入 ${imported} 篇文档；目标主机将重新切片和生成向量，官方来源声明已降级为待复核。`);
        setBundleFiles([]);
        await fetchStatsAndDocs();
      } catch (error: any) {
        setFileQueue((items) => items.map((item) => (
          item.fromZip === bundle.name ? { ...item, status: 'error' as FileQueueStatus, error: error?.message || 'ZIP 原子导入失败，已回滚' } : item
        )));
      } finally {
        setBatchSubmitting(false);
      }
      return;
    }
    const binaryItems = fileQueue.filter((item) => item.status === 'pending' && item.binaryFile);
    if (binaryItems.length > 0) {
      const textPending = fileQueue.some((item) => item.status === 'pending' && item.content.trim());
      if (textPending) {
        window.alert('PDF/DOCX 与文本文件请分批提交，以便清楚展示每个服务端解析任务的状态。');
        return;
      }
      setBatchSubmitting(true);
      setBatchProgress({ done: 0, total: binaryItems.length });
      setFileQueue((items) => items.map((item) => item.binaryFile && item.status === 'pending' ? { ...item, status: 'indexing' } : item));
      try {
        const result = await importKnowledgeEnterpriseSopBatch(binaryItems.map((item) => item.binaryFile as File));
        const byName = new Map(result.data.items.map((item) => [item.filename, item]));
        setFileQueue((items) => items.map((item) => {
          if (!item.binaryFile) return item;
          const outcome = byName.get(item.fileName);
          if (!outcome) return { ...item, status: 'error', error: '服务端未返回该文件的任务状态' };
          return outcome.success
            ? { ...item, status: 'done', error: outcome.status === 'queued' ? '已创建解析任务，可在“采集任务”查看进度' : undefined }
            : { ...item, status: 'error', error: outcome.error?.message || '服务端解析任务创建失败' };
        }));
        setBatchProgress({ done: result.data.total, total: result.data.total });
        setDocumentActionNotice(`批量任务已受理 ${result.data.accepted}/${result.data.total} 个文件；采用文件级提交，失败文件不会污染成功文件。`);
      } catch (error: any) {
        setFileQueue((items) => items.map((item) => item.binaryFile && item.status === 'indexing' ? { ...item, status: 'error', error: error?.message || '批量解析任务创建失败' } : item));
      } finally {
        setBatchSubmitting(false);
      }
      return;
    }
    const pendingItems = fileQueue.filter(item => item.status === 'pending' && item.content.trim());
    if (pendingItems.length === 0) return;
    if (!ensureAssetMetadataSelection()) return;

    const preparedItems = pendingItems.map((item) => ({ item, metadata: getQueueMetadataPreview(item) }));
    const invalidItems = preparedItems.filter(({ metadata }) => metadata.validation === 'error');
    if (invalidItems.length > 0) {
      setFileQueue((items) => items.map((item) => {
        const invalid = invalidItems.find(({ item: candidate }) => candidate.id === item.id);
        return invalid ? { ...item, error: invalid.metadata.issue || 'Metadata 校验失败' } : item;
      }));
      window.alert(`有 ${invalidItems.length} 个文件的 Metadata 与目录/资产不一致，请逐行修正后再提交。`);
      return;
    }

    const preparedWithMetadata = preparedItems.map(({ item, metadata: itemMetadata }) => ({
      key: item.id,
      label: item.fileName,
      name: getFileNameWithoutExt(item.fileName),
      content: item.content.trim(),
      vendor: itemMetadata.vendor,
      platform: itemMetadata.platform && itemMetadata.platform.toLowerCase() !== 'all' ? itemMetadata.platform : null,
      knowledge_source_type: itemMetadata.sourceType,
      metadata: buildKnowledgeMetadata({
        category: item.directoryCategory,
        vendorSlug: getKnowledgeDirectoryVendor(itemMetadata.vendor) || item.directoryVendor,
        directoryPath: itemMetadata.directoryPath,
        fileName: item.fileName,
        relativePath: item.relativePath,
      }),
    }));
    const metadataPreviews = await previewAndConfirmMetadata(preparedWithMetadata, (key, message) => {
      setFileQueue((items) => items.map((item) => item.id === key ? { ...item, error: message } : item));
    });
    if (!metadataPreviews) return;

    setBatchSubmitting(true);
    setBatchProgress({ done: 0, total: preparedItems.length });

    for (let i = 0; i < preparedItems.length; i++) {
      const { item, metadata: itemMetadata } = preparedItems[i];
      // Mark as indexing
      setFileQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: 'indexing' as FileQueueStatus } : f));

      try {
        const metadata = buildKnowledgeMetadata({
          category: item.directoryCategory,
          vendorSlug: getKnowledgeDirectoryVendor(itemMetadata.vendor) || item.directoryVendor,
          directoryPath: itemMetadata.directoryPath,
          fileName: item.fileName,
          relativePath: item.relativePath,
        });
        const metadataPreview = metadataPreviews.get(item.id);
        if (!metadataPreview) throw new Error('Metadata 预览已失效，请重新提交');
        await addKnowledgeDocument({
          name: getFileNameWithoutExt(item.fileName),
          content: item.content.trim(),
          vendor: itemMetadata.vendor,
          ...(itemMetadata.platform && itemMetadata.platform.toLowerCase() !== 'all' ? { platform: itemMetadata.platform } : {}),
          knowledge_source_type: itemMetadata.sourceType,
          metadata,
          metadata_confirmation_token: metadataPreview.confirmation_token,
          metadata_confirmed: true,
        });
        setFileQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: 'done' as FileQueueStatus } : f));
      } catch (err: any) {
        setFileQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: 'error' as FileQueueStatus, error: err.message || '提交失败' } : f));
      }

      setBatchProgress({ done: i + 1, total: preparedItems.length });
    }

    setBatchSubmitting(false);
    fetchStatsAndDocs();
  };

  const handleClearSample = async () => {
    if (!window.confirm('确认清空所有系统示例知识 (Sample) 吗？此操作不会影响您的企业正式 SOP。')) return;
    try {
      await clearSampleKnowledge();
      fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || '清空失败');
    }
  };

  /* ── Single-file paste mode submit ── */
  const handleCreateDocument = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!docName.trim() || !content.trim()) return;
    if (!ensureAssetMetadataSelection()) return;

    const metadata = buildKnowledgeMetadata({ fileName: docName.trim() });
    const metadataPreviews = await previewAndConfirmMetadata([{
      key: 'paste-document',
      label: docName.trim(),
      name: docName.trim(),
      content: content.trim(),
      vendor,
      platform,
      knowledge_source_type: sourceType,
      metadata,
    }]);
    const metadataPreview = metadataPreviews?.get('paste-document');
    if (!metadataPreview) return;

    setSubmitting(true);
    setIndexingStep(1);

    const steps = [1, 2, 3, 4, 5, 6];
    for (const step of steps) {
      setIndexingStep(step);
      await new Promise((resolve) => setTimeout(resolve, 200));
    }

    try {
      await addKnowledgeDocument({
        name: docName.trim(),
        content: content.trim(),
        vendor,
        platform,
        knowledge_source_type: sourceType,
        metadata,
        metadata_confirmation_token: metadataPreview.confirmation_token,
        metadata_confirmed: true,
      });

      setShowModal(false);
      setDocName('');
      setContent('');
      setIndexingStep(0);
      fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || '创建文档失败');
    } finally {
      setSubmitting(false);
    }
  };

  const sourceBadges: Record<string, { label: string; bg: string; color: string }> = {
    official_vendor: { label: '厂商官方资料', bg: 'bg-blue-50 dark:bg-blue-950/60', color: 'text-blue-600 dark:text-blue-400' },
    official_url: { label: '官方 URL / 产品目录', bg: 'bg-blue-50 dark:bg-blue-950/60', color: 'text-blue-600 dark:text-blue-400' },
    official_local: { label: '官方本地文件', bg: 'bg-blue-50 dark:bg-blue-950/60', color: 'text-blue-600 dark:text-blue-400' },
    official_template: { label: '官方配置模板', bg: 'bg-cyan-50 dark:bg-cyan-950/60', color: 'text-cyan-600 dark:text-cyan-400' },
    internal_sop: { label: '企业内部 SOP', bg: 'bg-emerald-50 dark:bg-emerald-950/60', color: 'text-emerald-600 dark:text-emerald-400' },
    internal_standard: { label: '企业规范标准', bg: 'bg-indigo-50 dark:bg-indigo-950/60', color: 'text-indigo-600 dark:text-indigo-400' },
    case: { label: '故障排查案例', bg: 'bg-amber-50 dark:bg-amber-950/60', color: 'text-amber-600 dark:text-amber-400' },
    user_document: { label: '用户上传', bg: 'bg-purple-50 dark:bg-purple-950/60', color: 'text-purple-600 dark:text-purple-400' },
    sample: { label: '系统示例 (Sample)', bg: 'bg-gray-100 dark:bg-gray-800', color: 'text-gray-600 dark:text-gray-300' },
  };

  const pipelineSteps = [
    '原始文件解析/提取',
    '转换为标准 Markdown 中间格式',
    'Heading 标题 & CLI 结构抽取',
    'Metadata JSON 提炼',
    'Heading-Aware Smart Chunking',
    'Embedding 向量与 FTS 就绪',
  ];

  /* ── Queue counts ── */
  const pendingCount = fileQueue.filter(f => f.status === 'pending').length;
  const doneCount = fileQueue.filter(f => f.status === 'done').length;
  const errorCount = fileQueue.filter(f => f.status === 'error').length;
  const totalQueueSize = fileQueue.reduce((s, f) => s + f.fileSize, 0);

  /* ── Selection helpers ── */
  const toggleDocSelection = (docId: string) => {
    setSelectedDocIds(prev => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedDocIds((previous) => {
      const next = new Set(previous);
      const allCurrentPageSelected = documents.length > 0 && documents.every((doc) => next.has(doc.id));
      documents.forEach((doc) => {
        if (allCurrentPageSelected) next.delete(doc.id);
        else next.add(doc.id);
      });
      return next;
    });
  };

  const handleFolderChange = (folderId: string) => {
    setSelectedFolder(folderId);
    if (folderId !== 'all') setKnowledgeScope('all');
    setCurrentPage(1);
    setSelectedDocIds(new Set());
  };

  const handleKnowledgeScopeChange = (scope: KnowledgeScope) => {
    setKnowledgeScope(scope);
    setSelectedFolder('all');
    setCurrentPage(1);
    setSelectedDocIds(new Set());
  };

  const setSemanticFilter = (key: keyof typeof semanticFilters, value: string) => {
    setSemanticFilters((current) => ({ ...current, [key]: value }));
    setCurrentPage(1);
    setSelectedDocIds(new Set());
  };

  const clearSemanticFilters = () => {
    setSemanticFilters({
      vendor: '',
      productFamily: '',
      productSeries: '',
      productModel: '',
      osFamily: '',
      softwareRelease: '',
      featureDomain: '',
      documentCategory: '',
      status: 'active',
    });
    setCurrentPage(1);
    setSelectedDocIds(new Set());
  };

  const openDocument = async (document: KnowledgeDocument) => {
    const requestId = ++documentDetailRequestIdRef.current;
    setSelectedDocument({ ...document, chunks: [] });
    setDocumentDetailLoading(true);
    setDocumentDetailError('');
    try {
      const detail = await getKnowledgeDocument(document.id);
      if (requestId === documentDetailRequestIdRef.current) setSelectedDocument(detail);
    } catch (err: any) {
      if (requestId === documentDetailRequestIdRef.current) setDocumentDetailError(err?.message || '文档内容加载失败');
    } finally {
      if (requestId === documentDetailRequestIdRef.current) setDocumentDetailLoading(false);
    }
  };

  const closeDocument = () => {
    documentDetailRequestIdRef.current += 1;
    setSelectedDocument(null);
    setDocumentDetailLoading(false);
    setDocumentDetailError('');
    setVersionAdminNotice('');
    setVersionCompareResult(null);
  };

  const refreshSelectedDocument = async () => {
    if (!selectedDocument) return;
    await openDocument(selectedDocument);
  };

  const compareSelectedVersions = async (versionId: string) => {
    if (!selectedDocument?.document_id) return;
    const history = selectedDocument.source_version_history || [];
    const latest = history[0];
    if (!latest || latest.id === versionId) return;
    setVersionAdminBusy(`compare:${versionId}`);
    setVersionAdminNotice('');
    try {
      const comparison = await compareKnowledgeDocumentVersions(selectedDocument.document_id, versionId, latest.id);
      setVersionCompareResult(comparison);
    } catch (err: any) {
      setVersionAdminNotice(err?.message || '版本比较失败');
    } finally {
      setVersionAdminBusy(null);
    }
  };

  const runVersionAdminAction = async (action: 'publish' | 'supersede' | 'rollback', versionId: string, replacementVersionId?: string) => {
    if (!selectedDocument?.document_id) return;
    const history = selectedDocument.source_version_history || [];
    const version = history.find((item) => item.id === versionId);
    const label = action === 'publish' ? '发布' : action === 'supersede' ? '替代' : '回滚';
    if (!version) return;
    if (action === 'supersede' && !replacementVersionId) return;
    const warning = action === 'rollback'
      ? `确认将文档回滚到 v${version.version_no}？当前版本会被标记为 Superseded。`
      : action === 'supersede'
        ? `确认将 v${version.version_no} 标记为 Superseded，并使用新版本替代？`
        : `确认发布文档 v${version.version_no}？发布后会成为当前检索版本。`;
    if (!window.confirm(warning)) return;
    setVersionAdminBusy(`${action}:${versionId}`);
    setVersionAdminNotice('');
    try {
      if (action === 'publish') await publishKnowledgeDocumentVersion(selectedDocument.document_id, versionId);
      if (action === 'supersede') await supersedeKnowledgeDocumentVersion(selectedDocument.document_id, versionId, replacementVersionId || '');
      if (action === 'rollback') await rollbackKnowledgeDocumentVersion(selectedDocument.document_id, versionId);
      setVersionAdminNotice(`${label}操作已完成，版本历史已刷新。`);
      setVersionCompareResult(null);
      await refreshSelectedDocument();
      void fetchStatsAndDocs();
    } catch (err: any) {
      setVersionAdminNotice(err?.message || `${label}操作失败`);
    } finally {
      setVersionAdminBusy(null);
    }
  };

  const versionManagementPanel = selectedDocument?.document_id && (selectedDocument.source_version_history?.length || 0) > 0 ? (() => {
    const history = selectedDocument.source_version_history || [];
    const latest = history[0];
    return (
      <section className="rounded-2xl border border-indigo-100 bg-indigo-50/40 p-4 shadow-sm dark:border-indigo-900/60 dark:bg-indigo-950/20">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-xs font-semibold text-indigo-900 dark:text-indigo-100">版本管理</div>
            <div className="mt-1 text-[10px] text-indigo-700/75 dark:text-indigo-200/70">比较只返回哈希、元数据和行数；发布、替代、回滚都会写入生命周期审计。</div>
          </div>
          {versionAdminBusy && <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />}
        </div>
        <div className="mt-3 space-y-2">
          {history.map((version) => {
            const status = version.lifecycle_status || version.status || 'draft';
            const isLatest = version.id === latest?.id;
            return (
              <div key={version.id} className="flex flex-wrap items-center gap-2 rounded-xl bg-white/80 px-3 py-2 text-[10px] dark:bg-slate-900/70">
                <span className="font-semibold text-slate-800 dark:text-slate-100">v{version.version_no}</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{status}</span>
                <span className="font-mono text-slate-500">{version.content_hash ? `${version.content_hash.slice(0, 10)}…` : 'hash 未记录'}</span>
                <div className="ml-auto flex flex-wrap gap-1">
                  {!isLatest && <button type="button" onClick={() => void compareSelectedVersions(version.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-indigo-200 px-2 py-1 font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 dark:border-indigo-800 dark:text-indigo-300">比较最新</button>}
                  {status !== 'active' && status !== 'published' && <button type="button" onClick={() => void runVersionAdminAction('publish', version.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-emerald-200 px-2 py-1 font-semibold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50 dark:border-emerald-800 dark:text-emerald-300">发布</button>}
                  {!isLatest && (latest?.lifecycle_status === 'published' || latest?.status === 'active') && status !== 'superseded' && <button type="button" onClick={() => void runVersionAdminAction('supersede', version.id, latest.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-amber-200 px-2 py-1 font-semibold text-amber-700 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-800 dark:text-amber-300">替代</button>}
                  {!isLatest && status !== 'quarantined' && status !== 'disabled' && <button type="button" onClick={() => void runVersionAdminAction('rollback', version.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-rose-200 px-2 py-1 font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50 dark:border-rose-800 dark:text-rose-300">回滚</button>}
                </div>
              </div>
            );
          })}
        </div>
        {versionAdminNotice && <div className="mt-2 rounded-lg bg-white/80 px-3 py-2 text-[10px] text-indigo-800 dark:bg-slate-900/70 dark:text-indigo-200">{versionAdminNotice}</div>}
        {versionCompareResult && (
          <div className="mt-3 rounded-xl border border-indigo-200 bg-white/80 p-3 text-[10px] text-slate-700 dark:border-indigo-800 dark:bg-slate-900/70 dark:text-slate-200">
            <div className="flex items-center justify-between gap-2 font-semibold"><span>v{versionCompareResult.left.version_no} → v{versionCompareResult.right.version_no}</span><button type="button" onClick={() => setVersionCompareResult(null)} className="text-slate-400 hover:text-slate-700" aria-label="关闭版本比较">×</button></div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4"><span>内容：{versionCompareResult.content_changed ? '已变化' : '未变化'}</span><span>Metadata：{versionCompareResult.metadata_changed ? '已变化' : '未变化'}</span><span>新增行：{versionCompareResult.line_diff.added_lines}</span><span>删除行：{versionCompareResult.line_diff.removed_lines}</span></div>
            <div className="mt-2 text-slate-500 dark:text-slate-400">变化字段：{versionCompareResult.changed_fields.join('、') || '无'}</div>
          </div>
        )}
      </section>
    );
  })() : null;

  const documentActionLabels: Record<KnowledgeDocumentAction, string> = {
    delete: '删除',
    disable: '禁用',
    enable: '启用',
    reparse: '重新解析 Metadata',
    rechunk: '重新切片',
    reindex: '重建索引',
  };

  const requestDocumentAction = async (doc: KnowledgeDocument, action: KnowledgeDocumentAction) => {
    setDocumentActionBusy(`${doc.id}:${action}:preview`);
    setDocumentActionNotice('');
    try {
      const preview = await getKnowledgeDocumentActionImpact(doc.id);
      if (!preview.safe_to_confirm) throw new Error('当前文档不满足安全确认条件');
      setPendingDocumentAction({ doc, action, preview });
    } catch (err: any) {
      alert(err.message || '无法读取危险操作影响预览');
    } finally {
      setDocumentActionBusy(null);
    }
  };

  const confirmDocumentAction = async () => {
    if (!pendingDocumentAction) return;
    const { doc, action, preview } = pendingDocumentAction;
    const busyKey = `${doc.id}:${action}`;
    const label = documentActionLabels[action];
    setPendingDocumentAction(null);
    setDocumentActionBusy(busyKey);
    setDocumentActionNotice('');
    try {
      const handlers = { delete: deleteKnowledgeDocument, disable: disableKnowledgeDocument, enable: enableKnowledgeDocument, reparse: reparseKnowledgeDocument, rechunk: rechunkKnowledgeDocument, reindex: reindexKnowledgeDocument } as const;
      const result = await handlers[action](doc.id, `knowledge admin confirmed ${action}`);
      const suffix = result.job_id ? `（任务 ${result.job_id} 已排队）` : '';
      setSelectedDocIds(prev => { const next = new Set(prev); if (action === 'delete') next.delete(doc.id); return next; });
      setDocumentActionNotice(`${label}已提交${suffix}；影响 ${preview.impact.documents} 文档 / ${preview.impact.chunks} Chunk / ${preview.impact.indexes} Index / ${preview.impact.references} 引用。恢复方式已记录。`);
      void fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || `${label}失败`);
    } finally {
      setDocumentActionBusy(null);
    }
  };

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedDocIds);
    if (ids.length === 0) return;
    setDeleting(true);
    try {
      const previews = await Promise.all(ids.map((id) => getKnowledgeDocumentActionImpact(id)));
      const impact = previews.reduce((total, item) => ({
        documents: total.documents + item.impact.documents,
        chunks: total.chunks + item.impact.chunks,
        indexes: total.indexes + item.impact.indexes,
        references: total.references + item.impact.references,
      }), { documents: 0, chunks: 0, indexes: 0, references: 0 });
      if (!window.confirm(`确认批量删除 ${impact.documents} 篇文档吗？\n影响：${impact.chunks} Chunk / ${impact.indexes} Index / ${impact.references} 引用。\n操作不可原地撤销，恢复方式为 PostgreSQL 备份恢复。`)) return;
      await batchDeleteKnowledgeDocuments(ids, 'knowledge admin confirmed batch delete');
      setSelectedDocIds(new Set());
      void fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || '批量删除失败');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6 font-sans">
      <KnowledgeAdminNavigation activeView={knowledgeAdminView} onChange={setKnowledgeAdminView} />
      {knowledgeAdminView === 'sources' ? <SourceRegistryPanel /> : knowledgeAdminView === 'evaluation' ? <RagEvaluationPanel /> : knowledgeAdminView === 'traces' ? <RetrievalTracePanel /> : <React.Fragment>
      <input
        ref={quickUploadInputRef}
        type="file"
        multiple
        accept={ALL_SUPPORTED_EXTENSIONS.join(',')}
        onChange={handleQuickUploadInputChange}
        className="hidden"
        aria-hidden="true"
      />
      {/* Header Title & Primary Action Buttons */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="nx-page-title flex items-center gap-2 text-gray-900 dark:text-white">
            <BookOpen className="w-6 h-6 text-indigo-500" />
            企业网络知识库中心 (RAG Data Engine)
          </h2>
          <p className="nx-page-description mt-1 text-gray-500 dark:text-gray-400">
            支持目录分类、多文件批量上传 (Markdown / HTML / PDF / DOCX / TXT / ZIP 压缩包) 与统一服务端解析。
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-500 dark:text-slate-400">
            <span className="inline-flex items-center gap-1"><Info className="h-3 w-3 text-indigo-500" />自定义文档推荐 UTF-8 Markdown + Front Matter；JSON/YAML 使用 Nexora envelope。</span>
            <a href="/downloads/nexora-knowledge-document-template.md" download="nexora-knowledge-document-template.md" className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2 py-1 font-semibold text-indigo-700 hover:bg-indigo-100 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-300"><FileText className="h-3 w-3" />Markdown 模板</a>
            <a href="/downloads/nexora-knowledge-document-template.json" download="nexora-knowledge-document-template.json" className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2 py-1 font-semibold text-indigo-700 hover:bg-indigo-100 dark:border-indigo-900/60 dark:bg-indigo-950/30 dark:text-indigo-300"><FileCode className="h-3 w-3" />JSON 模板</a>
            <a href="/downloads/nexora-knowledge-import-format.md" download="nexora-knowledge-import-format.md" className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 font-semibold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"><HelpCircle className="h-3 w-3" />格式说明</a>
          </div>
        </div>
        <button type="button" onClick={() => { setShowModal(true); setInputMode('upload'); setIngestionError(''); }} className="hidden items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-indigo-700 sm:inline-flex">
          <UploadCloud className="h-3.5 w-3.5" />批量上传企业文件
        </button>
      </div>

      <section className="rounded-2xl border border-slate-200/80 bg-white p-4 shadow-xs dark:border-slate-700/80 dark:bg-slate-800" aria-label="知识来源导入入口">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900 dark:text-white">受治理的知识导入</h3>
            <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">官方来源走 URL / Source Registry 校验；企业 SOP 走本地文件 / INTERNAL 分类，两套表单互不混用。</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => { setIngestionMode('official_url'); setIngestionError(''); setIngestionMessage(''); }} className={`rounded-xl px-3 py-2 text-xs font-semibold transition ${ingestionMode === 'official_url' ? 'bg-blue-600 text-white' : 'border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-200'}`}>
              <span className="mr-1.5">🌐</span>导入官方 URL
            </button>
            <button type="button" onClick={() => { setIngestionMode('enterprise_sop'); setIngestionError(''); setIngestionMessage(''); }} className={`rounded-xl px-3 py-2 text-xs font-semibold transition ${ingestionMode === 'enterprise_sop' ? 'bg-emerald-600 text-white' : 'border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200'}`}>
              <span className="mr-1.5">📄</span>上传企业 SOP
            </button>
            {ingestionMode && <button type="button" onClick={closeIngestionPanel} disabled={ingestionSubmitting} className="rounded-xl px-2.5 py-2 text-xs text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700" aria-label="关闭导入表单"><X className="h-3.5 w-3.5" /></button>}
          </div>
        </div>
        {ingestionMode === 'official_url' && (
          <form onSubmit={handleOfficialUrlImport} className="mt-4 grid gap-3 border-t border-blue-100 pt-4 dark:border-blue-900/50 md:grid-cols-2 xl:grid-cols-4">
            <label className="text-[11px] text-slate-600 dark:text-slate-300 md:col-span-2 xl:col-span-2">官方 HTTPS URL<input value={officialUrl} onChange={(event) => setOfficialUrl(event.target.value)} placeholder="https://support.huawei.com/..." className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">Vendor<select value={officialVendor} onChange={(event) => setOfficialVendor(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white"><option>Huawei</option><option>Cisco</option><option>H3C</option><option>Ruijie</option></select></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">Product Family<input value={officialFamily} onChange={(event) => setOfficialFamily(event.target.value)} placeholder="CloudEngine / Catalyst" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">版本范围<input value={officialVersion} onChange={(event) => setOfficialVersion(event.target.value)} placeholder="V800R022 / IOS XE 17.9" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">兼容版本<input value={officialCompatibilityVersion} onChange={(event) => setOfficialCompatibilityVersion(event.target.value)} placeholder="兼容版本或系列" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">名称（可选）<input value={officialName} onChange={(event) => setOfficialName(event.target.value)} placeholder="官方产品页" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">条款审核<select value={officialTerms} onChange={(event) => setOfficialTerms(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white"><option value="pending">未审核</option><option value="approved">已审核并同意</option></select></label>
            <div className="flex items-end"><button type="submit" disabled={ingestionSubmitting} className="w-full rounded-xl bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50">{ingestionSubmitting ? '提交中…' : '提交官方导入任务'}</button></div>
          </form>
        )}
        {ingestionMode === 'enterprise_sop' && (
          <form onSubmit={handleEnterpriseSopImport} className="mt-4 grid gap-3 border-t border-emerald-100 pt-4 dark:border-emerald-900/50 md:grid-cols-2 xl:grid-cols-4">
            <label className="text-[11px] text-slate-600 dark:text-slate-300 md:col-span-2">企业 SOP 文件（≤20 MB）<input type="file" accept=".md,.markdown,.txt,.log,.html,.htm,.docx,.pdf,.json,.yaml,.yml,.csv,.xml,.conf,.cfg,.ini" onChange={(event) => setEnterpriseSopFile(event.target.files?.[0] || null)} className="mt-1 block w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">标题<input value={enterpriseTitle} onChange={(event) => setEnterpriseTitle(event.target.value)} placeholder="变更 SOP" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">负责人<input value={enterpriseOwner} onChange={(event) => setEnterpriseOwner(event.target.value)} placeholder="姓名或工号" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <label className="text-[11px] text-slate-600 dark:text-slate-300">所属部门<input value={enterpriseDepartment} onChange={(event) => setEnterpriseDepartment(event.target.value)} placeholder="网络运维部" className="mt-1 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-900 dark:text-white" required /></label>
            <div className="flex items-end gap-2"><span className="flex-1 rounded-xl bg-emerald-50 px-3 py-2 text-[10px] text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-200">分类固定为 INTERNAL</span><button type="submit" disabled={ingestionSubmitting} className="rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">{ingestionSubmitting ? '提交中…' : '提交企业 SOP'}</button></div>
          </form>
        )}
        {(ingestionError || ingestionMessage) && <div className={`mt-3 rounded-xl px-3 py-2 text-[11px] ${ingestionError ? 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'}`}>{ingestionError || ingestionMessage}</div>}
      </section>

      <IngestionJobsPanel />

      {/* Top Metrics Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-4 bg-white dark:bg-gray-800 rounded-2xl border border-gray-200/80 dark:border-gray-700/80 shadow-xs space-y-1">
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>文档总数</span>
            <FileText className="w-4 h-4 text-indigo-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white font-mono">{stats.total_documents}</div>
          <div className="text-[11px] text-gray-400">已激活标准化中间文档</div>
        </div>

        <div className="p-4 bg-white dark:bg-gray-800 rounded-2xl border border-gray-200/80 dark:border-gray-700/80 shadow-xs space-y-1">
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>Heading 智能切片</span>
            <Layers className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white font-mono">{stats.total_chunks}</div>
          <div className="text-[11px] text-gray-400">标题与 CLI 结构感知切片</div>
        </div>

        <div className="p-4 bg-white dark:bg-gray-800 rounded-2xl border border-gray-200/80 dark:border-gray-700/80 shadow-xs space-y-1">
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>涵盖网络厂商</span>
            <Server className="w-4 h-4 text-blue-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900 dark:text-white font-mono">{stats.total_vendors || 4}</div>
          <div className="text-[11px] text-gray-400">Cisco / Huawei / H3C / Ruijie</div>
        </div>

        <div className="p-4 bg-white dark:bg-gray-800 rounded-2xl border border-gray-200/80 dark:border-gray-700/80 shadow-xs space-y-1">
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <span>向量 Ready 索引</span>
            <ShieldCheck className="w-4 h-4 text-amber-500" />
          </div>
          <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400 font-mono">{stats.ready_indexes}</div>
          <div className="text-[11px] text-gray-400">100% 可被 RAG 实时检索</div>
        </div>
      </div>

      {/* Full-Width Document Management Section */}
      <div className="space-y-4 w-full">
        <div className="grid gap-3 md:grid-cols-3" aria-label="官方知识与企业知识分区">
            {([
              ['all', '全部知识', '统一查看，但保留来源徽标与服务端边界', 'bg-slate-50 border-slate-200 text-slate-700 dark:bg-slate-900/50 dark:border-slate-700 dark:text-slate-200'],
              ['official', '官方知识', '厂商官方资料与 Source Registry 来源', 'bg-blue-50 border-blue-200 text-blue-800 dark:bg-blue-950/30 dark:border-blue-900 dark:text-blue-200'],
              ['enterprise', '企业知识', 'SOP、规范、案例与用户上传资料', 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/30 dark:border-emerald-900 dark:text-emerald-200'],
            ] as const).map(([scope, title, description, tone]) => (
              <button
                key={scope}
                type="button"
                onClick={() => handleKnowledgeScopeChange(scope)}
                className={`rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-sm ${tone} ${knowledgeScope === scope ? 'ring-2 ring-indigo-400 ring-offset-1 dark:ring-offset-gray-900' : ''}`}
                aria-pressed={knowledgeScope === scope}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-bold">{title}</span>
                  {knowledgeScope === scope && <CheckCircle2 className="h-4 w-4 text-indigo-500" />}
                </div>
                <span className="mt-1 block text-[10px] leading-4 opacity-75">{description}</span>
              </button>
            ))}
          </div>
          {/* Action Bar & Search */}
          <div className="flex items-center justify-between gap-4 bg-white dark:bg-gray-800 p-3 rounded-2xl border border-gray-200/80 dark:border-gray-700/80 shadow-xs">
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-400" />
              <input
                type="text"
                placeholder="搜索文档名称、厂商、型号或知识库内容..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl focus:outline-none focus:border-indigo-500 dark:text-white"
              />
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => void handleKnowledgeExport()}
                disabled={exporting || loading || permissionDenied || totalDocuments === 0}
                className="inline-flex items-center gap-1.5 rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 shadow-xs transition hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-200"
                title="导出当前筛选范围的知识文档与元数据"
              >
                {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PackageOpen className="h-3.5 w-3.5" />}
                {exporting ? '导出中…' : '导出当前筛选'}
              </button>
              {selectedDocIds.size > 0 && (
                <ActionButton icon={Trash2} variant="danger" size="sm" onClick={handleBatchDelete} disabled={deleting}>
                  {deleting ? '删除中...' : `批量删除 (${selectedDocIds.size})`}
                </ActionButton>
              )}
              <div className="text-xs text-gray-500 dark:text-gray-400">
                共计 <strong className="text-gray-800 dark:text-gray-200 font-semibold">{totalDocuments}</strong> 篇知识文档
              </div>
            </div>
          </div>
          {documentActionNotice && (
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200" role="status">
              {documentActionNotice}
            </div>
          )}

          <div className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-3 shadow-xs dark:border-indigo-900/60 dark:bg-indigo-950/20" aria-label="产品层级浏览">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div>
                <span className="text-[11px] font-semibold text-indigo-900 dark:text-indigo-200">产品层级浏览</span>
                <span className="ml-2 text-[10px] text-indigo-700/70 dark:text-indigo-300/70">Vendor / Product Family / Series</span>
              </div>
              <span className="text-[10px] text-indigo-700/70 dark:text-indigo-300/70">点击层级即可应用服务端筛选</span>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {([
                ['Vendor', documentFacets.vendors, 'vendor'],
                ['Product Family', documentFacets.families, 'productFamily'],
                ['Series', documentFacets.series, 'productSeries'],
              ] as const).map(([label, items, filterKey]) => (
                <div key={label} className="min-w-0">
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-indigo-700/70 dark:text-indigo-300/70">{label}</div>
                  <div className="flex min-h-8 flex-wrap gap-1.5">
                    {items.slice(0, 12).map((item) => (
                      <button
                        key={`${label}-${item.value}`}
                        type="button"
                        onClick={() => setSemanticFilter(filterKey, item.value === 'UNKNOWN' ? '' : item.value)}
                        className={`rounded-full border px-2 py-1 text-[10px] font-medium transition ${semanticFilters[filterKey] === item.value ? 'border-indigo-500 bg-indigo-600 text-white' : 'border-indigo-200 bg-white text-indigo-800 hover:border-indigo-400 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200'}`}
                        title={`筛选 ${item.value}`}
                      >
                        {item.value} <span className="opacity-60">{item.count}</span>
                      </button>
                    ))}
                    {items.length === 0 && <span className="text-[10px] text-indigo-700/50 dark:text-indigo-300/50">暂无已解析层级</span>}
                    {items.length > 12 && <span className="self-center text-[10px] text-indigo-700/60 dark:text-indigo-300/60">+{items.length - 12}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-gray-200/80 bg-white p-3 shadow-xs dark:border-gray-700/80 dark:bg-gray-800" aria-label="知识文档服务端筛选">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold text-gray-600 dark:text-gray-300">语义筛选（服务端执行）</span>
              <button
                type="button"
                onClick={clearSemanticFilters}
                disabled={!Object.entries(semanticFilters).some(([key, value]) => key === 'status' ? value !== 'active' : Boolean(value))}
                className="text-[10px] font-medium text-indigo-600 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-40 dark:text-indigo-300"
              >
                清除筛选
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <select
                value={selectedFolder}
                onChange={(event) => handleFolderChange(event.target.value)}
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按知识来源类型筛选"
              >
                {folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
              </select>
              <select
                value={semanticFilters.vendor}
                onChange={(event) => setSemanticFilter('vendor', event.target.value)}
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按厂商筛选"
              >
                <option value="">全部厂商</option>
                {knowledgeVendorOptions.map((item) => <option key={item.value} value={item.value}>{getVendorDisplayLabel(item.value)}</option>)}
              </select>
              <input
                value={semanticFilters.productFamily}
                onChange={(event) => setSemanticFilter('productFamily', event.target.value)}
                placeholder="产品 Family"
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 placeholder:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按产品 Family 筛选"
              />
              <input
                value={semanticFilters.productModel}
                onChange={(event) => setSemanticFilter('productModel', event.target.value)}
                placeholder="型号 Model"
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 placeholder:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按产品型号筛选"
              />
              <input
                value={semanticFilters.productSeries}
                onChange={(event) => setSemanticFilter('productSeries', event.target.value)}
                placeholder="产品 Series"
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 placeholder:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按产品 Series 筛选"
              />
              <input
                value={semanticFilters.osFamily}
                onChange={(event) => setSemanticFilter('osFamily', event.target.value)}
                placeholder="OS Family"
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 placeholder:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按 OS Family 筛选"
              />
              <input
                value={semanticFilters.softwareRelease}
                onChange={(event) => setSemanticFilter('softwareRelease', event.target.value)}
                placeholder="软件版本"
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 placeholder:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按软件版本筛选"
              />
              <input
                value={semanticFilters.featureDomain}
                onChange={(event) => setSemanticFilter('featureDomain', event.target.value)}
                placeholder="主题 / Feature Domain"
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 placeholder:text-gray-400 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按主题筛选"
              />
              <select
                value={semanticFilters.documentCategory}
                onChange={(event) => setSemanticFilter('documentCategory', event.target.value)}
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按文档类型筛选"
              >
                <option value="">全部文档类型</option>
                {KNOWLEDGE_DIRECTORY_OPTIONS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
              <select
                value={semanticFilters.status}
                onChange={(event) => setSemanticFilter('status', event.target.value)}
                className="rounded-xl border border-gray-200 bg-gray-50 px-2.5 py-2 text-[11px] text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
                aria-label="按生命周期状态筛选"
              >
                <option value="active">已启用</option>
                <option value="all">全部状态</option>
                <option value="published">已发布</option>
                <option value="draft">草稿</option>
                <option value="quarantined">已隔离</option>
                <option value="disabled">已禁用</option>
              </select>
            </div>
          </div>

          {/* Table Container */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-700/80 rounded-2xl overflow-hidden shadow-xs">
            {loading ? (
              <div className="p-8 text-center text-xs text-gray-400">数据加载中...</div>
            ) : loadError ? (
              <div className="p-10 text-center">
                <XCircle className={`mx-auto h-8 w-8 ${permissionDenied ? 'text-amber-400' : 'text-rose-400'}`} />
                <div className={`mt-3 text-sm font-semibold ${permissionDenied ? 'text-amber-700 dark:text-amber-300' : 'text-rose-700 dark:text-rose-300'}`}>{permissionDenied ? '无权限查看知识文档' : '知识文档加载失败'}</div>
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{loadError}</p>
                {!permissionDenied && <button type="button" onClick={() => void fetchStatsAndDocs()} className="mt-4 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700">重试</button>}
              </div>
            ) : documents.length === 0 ? (
              <div className="p-12 text-center space-y-3">
                <BookOpen className="w-8 h-8 text-gray-300 mx-auto" />
                <div className="text-sm font-semibold text-gray-700 dark:text-gray-300">当前目录暂无符合条件的知识文档</div>
                <p className="text-xs text-gray-400">点击上方“上传本地知识文件”导入属于您的企业文档。</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="nx-data-table min-w-full text-left">
                <thead className="sticky top-0 z-10 bg-gray-50 shadow-sm dark:bg-gray-900/95 text-gray-500 dark:text-gray-400 font-semibold">
                  <tr>
                    <th className="px-3 py-3 w-10">
                      <input
                        type="checkbox"
                        checked={documents.length > 0 && documents.every((doc) => selectedDocIds.has(doc.id))}
                        onChange={toggleSelectAll}
                        className="w-3.5 h-3.5 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                        title="全选 / 取消全选"
                      />
                    </th>
                    <th className="px-4 py-3">文档名称</th>
                    <th className="px-4 py-3">目录 / 知识类型</th>
                    <th className="px-4 py-3">适配厂商/平台</th>
                    <th className="px-4 py-3">Heading 智能切片</th>
                    <th className="px-4 py-3">索引状态</th>
                    <th className="px-4 py-3">入库时间</th>
                    <th className="px-4 py-3 text-center">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700 bg-white dark:bg-gray-800">
                  {documents.map((doc) => {
                    const badge = sourceBadges[doc.knowledge_source_type] || sourceBadges.user_document;
                    const isSelected = selectedDocIds.has(doc.id);
                    return (
                      <tr key={doc.id} className={`hover:bg-gray-50 dark:hover:bg-gray-700/50 transition ${isSelected ? 'bg-indigo-50/40 dark:bg-indigo-950/20' : ''}`}>
                        <td className="px-3 py-3">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleDocSelection(doc.id)}
                            className="w-3.5 h-3.5 rounded border-gray-300 dark:border-gray-600 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                          />
                        </td>
                        <td className="px-4 py-3 font-semibold text-gray-900 dark:text-white">
                          <button
                            type="button"
                            onClick={() => void openDocument(doc)}
                            className="group flex max-w-[260px] items-center gap-2 text-left transition hover:text-indigo-600 dark:hover:text-indigo-300"
                            title="查看文档内容"
                          >
                            <FileCode className="w-4 h-4 flex-shrink-0 text-indigo-500" />
                            <span className="min-w-0">
                              <span className="block truncate underline-offset-4 group-hover:underline">{doc.name}</span>
                              {(doc.product_family || doc.product_model || doc.document_category) && (
                                <span className="mt-0.5 block truncate text-[10px] font-normal text-gray-400">
                                  {[doc.product_family, doc.product_model, doc.document_category].filter(Boolean).join(' · ')}
                                </span>
                              )}
                            </span>
                            <Eye className="h-3.5 w-3.5 flex-shrink-0 text-slate-300 opacity-0 transition group-hover:text-indigo-400 group-hover:opacity-100" />
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded-full font-medium text-[11px] ${badge.bg} ${badge.color}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-600 dark:text-gray-300">
                          <span className="block">{getVendorDisplayLabel(doc.vendor)} / {getPlatformDisplayLabel(doc.vendor, doc.platform)}</span>
                          {(doc.os_family || doc.software_release) && (
                            <span className="mt-0.5 block text-[10px] text-gray-400">{[doc.os_family, doc.software_release].filter(Boolean).join(' · ')}</span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-700 dark:text-gray-200">
                          {doc.chunk_count || 1} 切片
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center gap-1 font-medium ${doc.status === 'active' && !doc.exclude_from_rag ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`}>
                            {doc.status === 'active' && !doc.exclude_from_rag ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
                            {doc.status === 'active' && !doc.exclude_from_rag ? 'Ready (就绪)' : `${doc.status || '待处理'}${doc.exclude_from_rag ? ' · 已排除 RAG' : ''}`}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-400 font-mono text-[11px]">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <button
                              type="button"
                              onClick={() => void requestDocumentAction(doc, doc.status === 'disabled' ? 'enable' : 'disable')}
                              disabled={Boolean(documentActionBusy)}
                              className="rounded-lg p-1.5 text-gray-400 transition hover:bg-amber-50 hover:text-amber-600 disabled:cursor-wait disabled:opacity-40 dark:hover:bg-amber-950/40"
                              title={doc.status === 'disabled' ? '启用文档（独立确认）' : '禁用文档（独立确认）'}
                              aria-label={doc.status === 'disabled' ? '启用文档' : '禁用文档'}
                            >
                              {doc.status === 'disabled' ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Archive className="h-3.5 w-3.5" />}
                            </button>
                            <button
                              type="button"
                              onClick={() => void requestDocumentAction(doc, 'reparse')}
                              disabled={Boolean(documentActionBusy)}
                              className="rounded-lg p-1.5 text-gray-400 transition hover:bg-blue-50 hover:text-blue-600 disabled:cursor-wait disabled:opacity-40 dark:hover:bg-blue-950/40"
                              title="重新解析 Metadata（独立确认）"
                              aria-label="重新解析 Metadata"
                            >
                              <FileText className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => void requestDocumentAction(doc, 'rechunk')}
                              disabled={Boolean(documentActionBusy)}
                              className="rounded-lg p-1.5 text-gray-400 transition hover:bg-violet-50 hover:text-violet-600 disabled:cursor-wait disabled:opacity-40 dark:hover:bg-violet-950/40"
                              title="重新切片（独立确认）"
                              aria-label="重新切片"
                            >
                              <Layers className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => void requestDocumentAction(doc, 'reindex')}
                              disabled={Boolean(documentActionBusy)}
                              className="rounded-lg p-1.5 text-gray-400 transition hover:bg-indigo-50 hover:text-indigo-600 disabled:cursor-wait disabled:opacity-40 dark:hover:bg-indigo-950/40"
                              title="重建索引（独立确认）"
                              aria-label="重建索引"
                            >
                              <RefreshCw className="h-3.5 w-3.5" />
                            </button>
                            <ActionIconButton
                              icon={Trash2}
                              label="删除此文档（独立确认）"
                              size="sm"
                              variant="danger"
                              onClick={() => void requestDocumentAction(doc, 'delete')}
                              disabled={Boolean(documentActionBusy)}
                            />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                </table>
              </div>
            )}
            {!loading && totalDocuments > 0 && (
              <Pagination
                currentPage={currentPage}
                totalItems={totalDocuments}
                itemsPerPage={itemsPerPage}
                onPageChange={setCurrentPage}
                onItemsPerPageChange={(size) => {
                  setItemsPerPage(size);
                  setCurrentPage(1);
                  setSelectedDocIds(new Set());
                }}
                language="zh"
              />
            )}
          </div>
        </div>

      {/* Document Content Viewer */}
      {selectedDocument && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-[2px]"
          role="dialog"
          aria-modal="true"
          aria-labelledby="knowledge-document-title"
          onClick={closeDocument}
        >
          <aside
            className="ml-auto flex h-full w-full max-w-3xl flex-col border-l border-white/60 bg-white shadow-2xl shadow-slate-950/20 dark:border-slate-700 dark:bg-slate-900"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-5 dark:border-slate-800 sm:px-7">
              <div className="min-w-0">
                <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-500">
                  <BookOpen className="h-3.5 w-3.5" />
                  文档查看器
                </div>
                <h2 id="knowledge-document-title" className="truncate text-xl font-bold tracking-tight text-slate-950 dark:text-white">{selectedDocument.name}</h2>
                <p className="mt-1 truncate font-mono text-[11px] text-slate-400" title={selectedDocument.id}>{selectedDocument.id}</p>
              </div>
              <button type="button" onClick={closeDocument} aria-label="关闭文档查看器" title="关闭文档查看器" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-4 dark:border-slate-800 sm:px-7">
              {(() => {
                const badge = sourceBadges[selectedDocument.knowledge_source_type] || sourceBadges.user_document;
                return <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${badge.bg} ${badge.color}`}>{badge.label}</span>;
              })()}
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{getVendorDisplayLabel(selectedDocument.vendor)} / {getPlatformDisplayLabel(selectedDocument.vendor, selectedDocument.platform)}</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"><CheckCircle2 className="h-3.5 w-3.5" />{selectedDocument.status === 'active' ? 'Ready（就绪）' : selectedDocument.status}</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-500 dark:bg-slate-800 dark:text-slate-400"><Layers className="h-3.5 w-3.5" />{selectedDocument.chunk_count} 个切片</span>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
              {documentDetailLoading ? (
                <div className="space-y-4" aria-label="正在加载文档内容">
                  {[0, 1, 2].map((item) => <div key={item} className="animate-pulse rounded-2xl border border-slate-100 p-4 dark:border-slate-800"><div className="h-4 w-1/3 rounded bg-slate-100 dark:bg-slate-800" /><div className="mt-4 h-20 rounded-xl bg-slate-100 dark:bg-slate-800" /></div>)}
                </div>
              ) : documentDetailError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300">
                  <div className="flex items-start gap-3"><XCircle className="mt-0.5 h-5 w-5 shrink-0" /><div><p className="font-semibold">文档内容加载失败</p><p className="mt-1 text-xs leading-5 opacity-80">{documentDetailError}</p><button type="button" onClick={() => void openDocument(selectedDocument)} className="mt-3 rounded-lg bg-white/80 px-3 py-1.5 text-xs font-semibold dark:bg-rose-900/30">重试</button></div></div>
                </div>
              ) : selectedDocument.chunks.length === 0 ? (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <section className="rounded-2xl border border-slate-200/90 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-900/50">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Raw Source / 原始来源</div>
                      <div className="mt-2 text-xs font-medium text-slate-700 dark:text-slate-200">{selectedDocument.raw_source?.source || selectedDocument.source || '未记录来源'}</div>
                    </section>
                    <section className="rounded-2xl border border-slate-200/90 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-900/50">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Version / Index</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-700 dark:text-slate-200">
                        <span>文档版本：{selectedDocument.document_version || '未记录'}</span>
                        <span>索引版本：{selectedDocument.index_version || '未记录'}</span>
                        <span>Parser：{selectedDocument.parser_version || '未记录'}</span>
                        <span>历史：{selectedDocument.source_version_history?.length || 0} 条</span>
                      </div>
                    </section>
                  </div>
                  {versionManagementPanel}
                  {selectedDocument.original_content && <details className="rounded-2xl border border-slate-200/90 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/40"><summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-slate-700 dark:text-slate-200">查看原始正文（按需展开）</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-slate-100 px-4 py-4 font-mono text-xs leading-6 text-slate-700 dark:border-slate-800 dark:text-slate-300">{selectedDocument.original_content}</pre></details>}
                  <div className="rounded-2xl border border-dashed border-slate-300 px-5 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">当前文档没有可展示的内容切片。</div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <section className="rounded-2xl border border-slate-200/90 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-900/50">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Raw Source / 原始来源</div>
                      <div className="mt-2 text-xs font-medium text-slate-700 dark:text-slate-200">{selectedDocument.raw_source?.source || selectedDocument.source || '未记录来源'}</div>
                      {selectedDocument.raw_source?.references?.map((reference, index) => (
                        <div key={`${String(reference.source_registry_id || 'source')}-${index}`} className="mt-1 truncate text-[10px] text-slate-500 dark:text-slate-400" title={String(reference.canonical_url || '')}>{String(reference.canonical_url || reference.source_version_id || '来源观察记录')}</div>
                      ))}
                    </section>
                    <section className="rounded-2xl border border-slate-200/90 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-900/50">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">Version / Index</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-slate-700 dark:text-slate-200">
                        <span>文档版本：{selectedDocument.document_version || '未记录'}</span>
                        <span>索引版本：{selectedDocument.index_version || '未记录'}</span>
                        <span>Parser：{selectedDocument.parser_version || '未记录'}</span>
                        <span>版本历史：{selectedDocument.source_version_history?.length || 0} 条</span>
                      </div>
                    </section>
                  </div>
                  {versionManagementPanel}
                  {selectedDocument.original_content && (
                    <details className="rounded-2xl border border-slate-200/90 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/40">
                      <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-slate-700 dark:text-slate-200">查看原始正文（按需展开）</summary>
                      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-slate-100 px-4 py-4 font-mono text-xs leading-6 text-slate-700 dark:border-slate-800 dark:text-slate-300">{selectedDocument.original_content}</pre>
                    </details>
                  )}
                  <div className="flex items-center gap-2 rounded-2xl border border-indigo-100 bg-indigo-50/60 px-4 py-3 text-xs leading-5 text-indigo-900/70 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-200/70"><Info className="h-4 w-4 shrink-0 text-indigo-500" />文档已按 Heading / CLI 结构拆分为切片，以下内容按原始顺序展示。</div>
                  {selectedDocument.chunks.map((chunk, index) => (
                    <section key={chunk.id} className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/40">
                      <div className="flex items-start gap-3 border-b border-slate-100 bg-slate-50/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/70">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-[11px] font-bold text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">{String(chunk.page || index + 1).padStart(2, '0')}</span>
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-bold text-slate-800 dark:text-slate-100">{chunk.section || 'General Overview'}</h3>
                          <p className="mt-0.5 text-[10px] uppercase tracking-[0.12em] text-slate-400">Chunk {index + 1} · ordinal {chunk.ordinal ?? index}</p>
                        </div>
                        <div className="ml-auto flex shrink-0 flex-wrap justify-end gap-1 text-[10px]">
                          {chunk.chunk_role && <span className="rounded-full bg-indigo-100 px-2 py-0.5 font-medium text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">{chunk.chunk_role}</span>}
                          {chunk.chunk_type && <span className="rounded-full bg-slate-200 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{chunk.chunk_type}</span>}
                        </div>
                      </div>
                      <pre className="whitespace-pre-wrap break-words px-4 py-4 font-mono text-xs leading-6 text-slate-700 dark:text-slate-300">{chunk.content}</pre>
                      <div className="grid gap-2 border-t border-slate-100 bg-slate-50/50 px-4 py-3 text-[10px] dark:border-slate-800 dark:bg-slate-900/40 sm:grid-cols-2">
                        <div className="flex flex-wrap items-center gap-1.5 text-slate-500 dark:text-slate-400">
                          <span className="font-semibold text-slate-600 dark:text-slate-300">可检索：</span>{chunk.is_retrieval_candidate === false ? '否' : '是'}
                          <span className="ml-2 font-semibold text-slate-600 dark:text-slate-300">Token：</span>{chunk.token_count ?? 0}
                          {chunk.content_hash && <span className="ml-2 font-mono" title={chunk.content_hash}>hash {chunk.content_hash.slice(0, 10)}…</span>}
                        </div>
                        <div className="text-right text-slate-400">{chunk.chunking_version || 'chunker 未记录'} · {chunk.parser_version || selectedDocument.parser_version || 'parser 未记录'}</div>
                      </div>
                      {(chunk.parent_chunk || (chunk.neighbors && chunk.neighbors.length > 0)) && (
                        <div className="space-y-2 border-t border-slate-100 px-4 py-3 dark:border-slate-800">
                          {chunk.parent_chunk && (
                            <details className="rounded-xl border border-amber-200/80 bg-amber-50/50 px-3 py-2 dark:border-amber-900/60 dark:bg-amber-950/20">
                              <summary className="cursor-pointer text-[10px] font-semibold text-amber-800 dark:text-amber-200">Parent Chunk · {chunk.parent_chunk.section || chunk.parent_chunk.id}</summary>
                              <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap break-words border-t border-amber-200/60 pt-2 font-mono text-[10px] leading-5 text-amber-900/80 dark:border-amber-900/50 dark:text-amber-100/80">{chunk.parent_chunk.content || 'Parent 内容为空'}</pre>
                            </details>
                          )}
                          {chunk.neighbors && chunk.neighbors.length > 0 && (
                            <details className="rounded-xl border border-sky-200/80 bg-sky-50/50 px-3 py-2 dark:border-sky-900/60 dark:bg-sky-950/20">
                              <summary className="cursor-pointer text-[10px] font-semibold text-sky-800 dark:text-sky-200">Neighbor Chunks · {chunk.neighbors.length}</summary>
                              <div className="mt-2 space-y-2 border-t border-sky-200/60 pt-2 dark:border-sky-900/50">
                                {chunk.neighbors.map((neighbor) => <div key={neighbor.id} className="rounded-lg bg-white/70 p-2 dark:bg-slate-950/40"><div className="font-semibold text-[10px] text-sky-800 dark:text-sky-200">{neighbor.section || neighbor.id} · ordinal {neighbor.ordinal ?? '—'}</div><pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-5 text-slate-600 dark:text-slate-300">{neighbor.content || 'Neighbor 内容为空'}</pre></div>)}
                              </div>
                            </details>
                          )}
                        </div>
                      )}
                      <details className="border-t border-slate-100 px-4 py-3 dark:border-slate-800">
                        <summary className="cursor-pointer text-[10px] font-semibold text-slate-600 dark:text-slate-300">Metadata / 来源定位 / 版本字段</summary>
                        <div className="mt-2 grid gap-3 border-t border-slate-100 pt-2 dark:border-slate-800 sm:grid-cols-2">
                          <div><div className="mb-1 text-[10px] font-semibold text-slate-400">Metadata</div><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950/[0.03] p-2 font-mono text-[10px] leading-5 text-slate-600 dark:bg-white/[0.04] dark:text-slate-300">{JSON.stringify(chunk.metadata || {}, null, 2)}</pre></div>
                          <div><div className="mb-1 text-[10px] font-semibold text-slate-400">Source locator</div><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950/[0.03] p-2 font-mono text-[10px] leading-5 text-slate-600 dark:bg-white/[0.04] dark:text-slate-300">{JSON.stringify(chunk.source_locator || {}, null, 2)}</pre><div className="mt-2 text-[10px] text-slate-400">Document：{chunk.document_version || selectedDocument.document_version || '未记录'} · Index：{chunk.index_version || selectedDocument.index_version || '未记录'}</div></div>
                        </div>
                      </details>
                    </section>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 text-xs text-slate-400 dark:border-slate-800 sm:px-7"><span className="inline-flex items-center gap-1.5"><CalendarDays className="h-3.5 w-3.5" />入库于 {new Date(selectedDocument.created_at).toLocaleString()}</span><button type="button" onClick={closeDocument} className="rounded-xl bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700">关闭</button></div>
          </aside>
        </div>
      )}

      {pendingDocumentAction && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-labelledby="knowledge-action-impact-title">
          <div className="w-full max-w-xl rounded-2xl border border-rose-200 bg-white p-5 shadow-2xl dark:border-rose-900/60 dark:bg-slate-900">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300"><AlertTriangle className="h-5 w-5" /></div>
              <div className="min-w-0">
                <h3 id="knowledge-action-impact-title" className="text-base font-bold text-slate-950 dark:text-white">危险操作影响确认</h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{documentActionLabels[pendingDocumentAction.action]}「{pendingDocumentAction.preview.name}」前，请确认以下服务端预览。</p>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {([
                ['文档', pendingDocumentAction.preview.impact.documents],
                ['Chunk', pendingDocumentAction.preview.impact.chunks],
                ['Index', pendingDocumentAction.preview.impact.indexes],
                ['引用', pendingDocumentAction.preview.impact.references],
              ] as const).map(([label, value]) => (
                <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-950/50">
                  <div className="text-[10px] text-slate-400">{label}</div>
                  <div className="mt-1 font-mono text-lg font-bold text-slate-900 dark:text-white">{value}</div>
                </div>
              ))}
            </div>
            {pendingDocumentAction.preview.impact.reference_details && pendingDocumentAction.preview.impact.reference_details.length > 0 && (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200">
                引用明细：{pendingDocumentAction.preview.impact.reference_details.map((item) => `${item.type} ${item.count}`).join('、')}
              </div>
            )}
            <div className="mt-3 rounded-xl border border-indigo-100 bg-indigo-50/70 px-3 py-2 text-[11px] leading-5 text-indigo-900 dark:border-indigo-900/60 dark:bg-indigo-950/25 dark:text-indigo-200">
              <span className="font-semibold">恢复方式：</span>{pendingDocumentAction.preview.recovery[pendingDocumentAction.action] || '按租户动作审计与任务状态恢复'}
            </div>
            <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] leading-5 text-rose-800 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200">
              {pendingDocumentAction.action === 'delete' ? '删除会移除文档与全部切片，不能在系统内原地撤销；请确认已具备 PostgreSQL 备份恢复条件。' : '动作会写入租户动作审计；任务型操作失败时保留源文档并允许重试。'}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" onClick={() => setPendingDocumentAction(null)} disabled={Boolean(documentActionBusy)} className="rounded-xl px-4 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-100 disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-800">取消</button>
              <button type="button" onClick={() => void confirmDocumentAction()} disabled={Boolean(documentActionBusy)} className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-rose-700 disabled:cursor-wait disabled:opacity-50">确认{documentActionLabels[pendingDocumentAction.action]}</button>
            </div>
          </div>
        </div>
      )}

      {/* Upload File & Create Document Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-700 pb-3">
              <h3 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <UploadCloud className="w-5 h-5 text-indigo-500" />
                新增与上传企业知识文件
              </h3>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-700 p-1 rounded-xl text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setInputMode('upload')}
                    className={`px-3 py-1 rounded-lg transition cursor-pointer ${
                      inputMode === 'upload' ? 'bg-white dark:bg-gray-800 text-indigo-600 dark:text-indigo-400 shadow-2xs' : 'text-gray-500'
                    }`}
                  >
                    📁 批量上传文件
                  </button>
                  <button
                    type="button"
                    onClick={() => setInputMode('paste')}
                    className={`px-3 py-1 rounded-lg transition cursor-pointer ${
                      inputMode === 'paste' ? 'bg-white dark:bg-gray-800 text-indigo-600 dark:text-indigo-400 shadow-2xs' : 'text-gray-500'
                    }`}
                  >
                    📝 手动录入文本
                  </button>
                </div>
                <button
                  type="button"
                  onClick={closeModal}
                  disabled={batchSubmitting || submitting}
                  aria-label="关闭上传窗口"
                  title="关闭上传窗口"
                  className="p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-40"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className={`rounded-xl px-3 py-2 text-[11px] ${
              assetOptionsError || directoryVendorOptions.length === 0
                ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300'
                : 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300'
            }`}>
              {assetOptionsLoading
                ? '正在同步资产管理中的网络设备厂商与平台...'
                : assetOptionsError
                ? assetOptionsError
                : directoryVendorOptions.length === 0
                ? '资产管理中暂无 Huawei / H3C / Cisco / Ruijie 设备，请先导入对应设备资产。'
                : `已同步 ${assetOptions.asset_count} 台网络设备，目录厂商与平台选项来自资产管理。`}
            </div>

            {/* ═══════════ MODE: BATCH UPLOAD ═══════════ */}
            {inputMode === 'upload' && (
              <div className="space-y-4">
                {/* Dropzone */}
                <div
                  onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-2xl p-6 text-center transition cursor-pointer ${
                    isDragOver
                      ? 'border-indigo-500 bg-indigo-50/50 dark:bg-indigo-950/40'
                      : fileQueue.length > 0
                      ? 'border-emerald-400 bg-emerald-50/30 dark:bg-emerald-950/20'
                      : 'border-gray-300 dark:border-gray-600 hover:border-indigo-400 bg-gray-50/50 dark:bg-gray-900/50'
                  }`}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".md,.markdown,.html,.htm,.txt,.json,.yaml,.yml,.docx,.pdf,.zip,.csv,.xml,.conf,.cfg,.ini"
                    onChange={handleFileInputChange}
                    className="hidden"
                  />

                  <div className="space-y-1.5">
                    <div className="flex items-center justify-center gap-3">
                      <UploadCloud className="w-7 h-7 text-indigo-500" />
                      <Archive className="w-6 h-6 text-amber-500" />
                    </div>
                    <div className="text-xs font-semibold text-gray-800 dark:text-gray-200">
                      点击选择文件 或 拖拽到此处 · 支持同时选择多个文件
                    </div>
                    <div className="text-[11px] text-gray-400 space-y-0.5">
                      <div>
                        文本格式：<strong>.md / .html / .txt / .json / .yaml / .csv / .xml / .conf / .cfg / .ini / .log</strong>（服务端按扩展名校验并规范化）
                      </div>
                      <div>
                        自定义文档：<strong>.md</strong> 使用 Front Matter；<strong>.json / .yaml</strong> 可使用 <strong>nexora-knowledge-document</strong> 的 metadata + content envelope；缺少 envelope 的结构化文件按正文处理，不会猜测型号。
                      </div>
                      <div>
                        压缩包：<strong className="text-amber-500">.zip</strong>（Nexora 导出包走服务端原子回导；普通 ZIP 仅解压预览并按文件解析）
                      </div>
                      <div>
                        二进制：<strong>.docx / .pdf</strong>（请使用“上传企业 SOP”入口，由服务端解析；解析失败不会入库）
                      </div>
                      <div className="pt-1 text-indigo-500 dark:text-indigo-300">
                        Nexora 导出 ZIP 可直接回导：服务端会先完整校验 manifest、路径、大小与 SHA-256，确认后用一个事务原子写入；任一文件失败全部回滚。目标机重新切片和生成向量，不复制旧主机 Embedding，官方来源声明会降级为“待复核”。
                      </div>
                    </div>
                  </div>
                </div>

                {/* Metadata selectors (shared for all files in batch) */}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">知识分类目录</label>
                    <select
                      value={knowledgeDirectory}
                      onChange={(e) => setKnowledgeDirectory(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      {KNOWLEDGE_DIRECTORY_OPTIONS.map((item) => (
                        <option key={item.id} value={item.id}>{item.label}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">资料来源 (文档元数据)</label>
                    <select
                      value={sourceType}
                      onChange={(e) => setSourceType(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="internal_sop">📘 企业内部 SOP 目录</option>
                      <option value="internal_standard">📜 企业规范标准库</option>
                      <option value="case">🚨 应急处置与排查案例</option>
                      <option value="sample">🧪 系统示例知识 (Sample)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标网络厂商 (资产同步)</label>
                    <select
                      value={vendor}
                      onChange={(e) => {
                        const nextVendor = e.target.value;
                        setVendor(nextVendor);
                        const nextOption = directoryVendorOptions.find((item) => item.value === nextVendor);
                        setPlatform(nextOption?.platforms[0]?.value || '');
                      }}
                      disabled={assetOptionsLoading || directoryVendorOptions.length === 0}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="">请选择资产厂商</option>
                      {directoryVendorOptions.map((item) => (
                        <option key={item.value} value={item.value}>{getVendorDisplayLabel(item.value)}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标平台 (资产同步)</label>
                    <select
                      value={platform}
                      onChange={(e) => setPlatform(e.target.value)}
                      disabled={assetOptionsLoading || !selectedVendorOption}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="">请选择对应平台</option>
                      {(selectedVendorOption?.platforms || []).map((item) => (
                        <option key={item.value} value={item.value}>{getPlatformDisplayLabel(vendor, item.value)}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 px-3 py-2 text-[11px] text-indigo-800 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-200">
                  导入目录前缀：<span className="font-mono font-semibold">{getDirectoryImportPath(knowledgeDirectory, vendor)}</span>
                  <span className="ml-2 text-indigo-600/70 dark:text-indigo-300/70">ZIP 内已有的目录路径会保留在文档元数据中。</span>
                </div>

                {/* File Queue List */}
                {fileQueue.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
                        <FileUp className="w-4 h-4 text-indigo-500" />
                        文件队列
                        <span className="text-[10px] font-mono text-gray-400">
                          ({fileQueue.length} 个文件 · {formatFileSize(totalQueueSize)})
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-[10px] font-mono">
                        {pendingCount > 0 && <span className="text-blue-500">待提交 {pendingCount}</span>}
                        {doneCount > 0 && <span className="text-emerald-500">已完成 {doneCount}</span>}
                        {errorCount > 0 && <span className="text-red-500">失败 {errorCount}</span>}
                        <button
                          type="button"
                          onClick={clearQueue}
                          disabled={batchSubmitting}
                          className="text-gray-400 hover:text-red-500 transition cursor-pointer disabled:opacity-40"
                        >
                          清空队列
                        </button>
                      </div>
                    </div>

                    <div className="max-h-72 overflow-y-auto space-y-1 pr-1">
                      {fileQueue.map((item) => {
                        const metadata = getQueueMetadataPreview(item);
                        return (
                        <div
                          key={item.id}
                          className={`flex items-center gap-3 px-3 py-2 rounded-xl text-xs transition ${
                            item.status === 'done'
                              ? 'bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200/60 dark:border-emerald-800/60'
                              : item.status === 'error'
                              ? 'bg-red-50 dark:bg-red-950/30 border border-red-200/60 dark:border-red-800/60'
                              : item.status === 'indexing'
                              ? 'bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-200/60 dark:border-indigo-800/60'
                              : 'bg-gray-50 dark:bg-gray-900/50 border border-gray-200/60 dark:border-gray-700/60'
                          }`}
                        >
                          {/* Status icon */}
                          <div className="flex-shrink-0">
                            {item.status === 'done' && <CheckCircle className="w-4 h-4 text-emerald-500" />}
                            {item.status === 'error' && <XCircle className="w-4 h-4 text-red-500" />}
                            {item.status === 'indexing' && <Loader2 className="w-4 h-4 text-indigo-500 animate-spin" />}
                            {item.status === 'pending' && <FileText className="w-4 h-4 text-gray-400" />}
                          </div>

                          {item.status === 'pending' && (
                            <div className="w-full basis-full rounded-xl border border-slate-200 bg-white/80 p-2 dark:border-slate-700 dark:bg-slate-900/60">
                              <div className="mb-1 flex items-center justify-between gap-2 text-[10px] font-semibold text-slate-500 dark:text-slate-400">
                                <span>本文件 Metadata 预览</span>
                                <span className={metadata.validation === 'error' ? 'text-rose-600' : metadata.validation === 'warning' ? 'text-amber-600' : 'text-emerald-600'}>{metadata.validation === 'error' ? '需修正' : metadata.validation === 'warning' ? '请确认' : '可提交'}</span>
                              </div>
                              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                                <select value={metadata.vendor} onChange={(event) => updateQueueMetadata(item.id, 'vendor', event.target.value)} className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-[10px] dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label={`${item.fileName} Vendor Metadata`}>
                                  <option value="">Vendor</option>
                                  {directoryVendorOptions.map((option) => <option key={option.value} value={option.value}>{option.value}</option>)}
                                </select>
                                <select value={metadata.platform} onChange={(event) => updateQueueMetadata(item.id, 'platform', event.target.value)} className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-[10px] dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label={`${item.fileName} Platform Metadata`}>
                                  <option value="">CLI Platform</option>
                                  {(directoryVendorOptions.find((option) => option.value === metadata.vendor)?.platforms || []).map((option) => <option key={option.value} value={option.value}>{option.value}</option>)}
                                </select>
                                <select value={metadata.sourceType} onChange={(event) => updateQueueMetadata(item.id, 'sourceType', event.target.value)} className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-[10px] dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" aria-label={`${item.fileName} source type Metadata`}>
                                  <option value="internal_sop">企业 SOP</option>
                                  <option value="internal_standard">企业规范</option>
                                  <option value="case">排查案例</option>
                                  <option value="sample">系统示例</option>
                                  <option value="user_document">用户上传</option>
                                </select>
                              </div>
                              <div className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">目录：{metadata.directoryPath}{metadata.issue ? ` · ${metadata.issue}` : ''}</div>
                            </div>
                          )}

                          {/* File info */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-gray-800 dark:text-gray-200 truncate">{item.fileName}</span>
                              <span className="text-[10px] text-gray-400 font-mono flex-shrink-0">{formatFileSize(item.fileSize)}</span>
                            </div>
                            {item.fromZip && (
                              <div className="text-[10px] text-amber-500 flex items-center gap-1 mt-0.5">
                                <PackageOpen className="w-3 h-3" />
                                来自压缩包: {item.fromZip}
                              </div>
                            )}
                            {item.relativePath && (
                              <div className="text-[10px] text-indigo-500 truncate mt-0.5" title={item.relativePath}>
                                目录路径: {item.relativePath}
                              </div>
                            )}
                            {item.error && (
                              <div className="text-[10px] text-red-500 mt-0.5">{item.error}</div>
                            )}
                          </div>

                          {/* Status label */}
                          <div className="flex-shrink-0 text-[10px] font-mono">
                            {item.status === 'pending' && <span className="text-blue-500">等待提交</span>}
                            {item.status === 'indexing' && <span className="text-indigo-500">索引中...</span>}
                            {item.status === 'done' && <span className="text-emerald-500">已入库</span>}
                            {item.status === 'error' && <span className="text-red-500">失败</span>}
                          </div>

                          {/* Remove button */}
                          {item.status !== 'indexing' && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); removeFromQueue(item.id); }}
                              disabled={batchSubmitting}
                              className="flex-shrink-0 p-1 text-gray-400 hover:text-red-500 transition cursor-pointer disabled:opacity-40"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                        );
                      })}
                    </div>

                    {/* Batch progress bar */}
                    {batchSubmitting && (
                      <div className="p-3 bg-indigo-50 dark:bg-indigo-950/30 rounded-xl border border-indigo-200/60 dark:border-indigo-800/60 space-y-2">
                        <div className="flex items-center justify-between text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                          <span className="flex items-center gap-2">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            正在批量解析与建立索引...
                          </span>
                          <span className="font-mono">{batchProgress.done} / {batchProgress.total}</span>
                        </div>
                        <div className="w-full bg-indigo-200 dark:bg-indigo-900 rounded-full h-1.5">
                          <div
                            className="bg-indigo-600 h-1.5 rounded-full transition-all duration-300"
                            style={{ width: `${batchProgress.total > 0 ? (batchProgress.done / batchProgress.total) * 100 : 0}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Action buttons */}
                <div className="flex justify-end gap-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                  <button
                    type="button"
                    onClick={closeModal}
                    disabled={batchSubmitting}
                    className="px-4 py-2 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-xl cursor-pointer disabled:opacity-40"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={handleBatchSubmit}
                    disabled={batchSubmitting || pendingCount === 0 || !vendor || !platform || assetOptionsLoading}
                    className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold disabled:opacity-50 transition shadow-xs cursor-pointer flex items-center gap-2"
                  >
                    {batchSubmitting ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        批量索引中...
                      </>
                    ) : (
                      <>
                        <UploadCloud className="w-3.5 h-3.5" />
                        批量解析并建立索引 ({pendingCount} 个文件)
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* ═══════════ MODE: MANUAL PASTE ═══════════ */}
            {inputMode === 'paste' && (
              <form onSubmit={handleCreateDocument} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">文档标题</label>
                  <input
                    type="text"
                    required
                    placeholder="例如：华为 S6800 OSPF 异常排查 SOP"
                    value={docName}
                    onChange={(e) => setDocName(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">知识分类目录</label>
                    <select
                      value={knowledgeDirectory}
                      onChange={(e) => setKnowledgeDirectory(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      {KNOWLEDGE_DIRECTORY_OPTIONS.map((item) => (
                        <option key={item.id} value={item.id}>{item.label}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">资料来源 (文档元数据)</label>
                    <select
                      value={sourceType}
                      onChange={(e) => setSourceType(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="internal_sop">📘 企业内部 SOP 目录</option>
                      <option value="internal_standard">📜 企业规范标准库</option>
                      <option value="case">🚨 应急处置与排查案例</option>
                      <option value="sample">🧪 系统示例知识 (Sample)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标网络厂商 (资产同步)</label>
                    <select
                      value={vendor}
                      onChange={(e) => {
                        const nextVendor = e.target.value;
                        setVendor(nextVendor);
                        const nextOption = directoryVendorOptions.find((item) => item.value === nextVendor);
                        setPlatform(nextOption?.platforms[0]?.value || '');
                      }}
                      disabled={assetOptionsLoading || directoryVendorOptions.length === 0}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="">请选择资产厂商</option>
                      {directoryVendorOptions.map((item) => (
                        <option key={item.value} value={item.value}>{getVendorDisplayLabel(item.value)}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标平台 (资产同步)</label>
                    <select
                      value={platform}
                      onChange={(e) => setPlatform(e.target.value)}
                      disabled={assetOptionsLoading || !selectedVendorOption}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="">请选择对应平台</option>
                      {(selectedVendorOption?.platforms || []).map((item) => (
                        <option key={item.value} value={item.value}>{getPlatformDisplayLabel(vendor, item.value)}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 px-3 py-2 text-[11px] text-indigo-800 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-200">
                  导入目录：<span className="font-mono font-semibold">{getDirectoryImportPath(knowledgeDirectory, vendor)}</span>
                  <span className="ml-2 text-indigo-600/70 dark:text-indigo-300/70">资料来源会单独保存为文档元数据。</span>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    文档正文预览 (已自动提取 Heading 与 CLI 语法结构)
                  </label>
                  <textarea
                    required
                    rows={5}
                    placeholder="在此粘贴 Markdown 正文、HTML 手册或包含 Heading / CLI 代码块的 SOP 步骤..."
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white font-mono leading-relaxed"
                  />
                </div>

                {/* 6-Step Indexing Stepper */}
                {submitting && (
                  <div className="p-3 bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 space-y-2">
                    <div className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 flex items-center justify-between">
                      <span>标准化中间格式解析与 RAG 索引构建...</span>
                      <span>{indexingStep} / 6</span>
                    </div>
                    <div className="grid grid-cols-6 gap-1">
                      {pipelineSteps.map((stepLabel, idx) => {
                        const isCompleted = idx + 1 <= indexingStep;
                        return (
                          <div
                            key={idx}
                            className={`h-1.5 rounded-full transition-colors ${
                              isCompleted ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700'
                            }`}
                            title={stepLabel}
                          />
                        );
                      })}
                    </div>
                    <div className="text-[11px] text-gray-500 font-mono text-center pt-1">
                      当前阶段: {pipelineSteps[Math.max(0, indexingStep - 1)]}
                    </div>
                  </div>
                )}

                <div className="flex justify-end gap-3 pt-3 border-t border-gray-200 dark:border-gray-700">
                  <button
                    type="button"
                    onClick={closeModal}
                    disabled={submitting}
                    className="px-4 py-2 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-xl cursor-pointer"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    disabled={submitting || !docName.trim() || !content.trim() || !vendor || !platform || assetOptionsLoading}
                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold disabled:opacity-50 transition shadow-xs cursor-pointer"
                  >
                    {submitting ? '标准化解析中...' : '解析并建立索引'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
      </React.Fragment>}
    </div>
  );
};

export default KnowledgeManagementTab;

