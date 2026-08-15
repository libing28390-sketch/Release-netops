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
  CalendarDays,
  ChevronRight,
  Pencil,
  Info,
} from 'lucide-react';
import { getKnowledgeStats, getKnowledgeDocuments, getKnowledgeDocument, getKnowledgeAssetOptions, getKnowledgeDirectories, createKnowledgeDirectory, renameKnowledgeDirectory, deleteKnowledgeDirectory, addKnowledgeDocument, clearSampleKnowledge, deleteKnowledgeDocument, batchDeleteKnowledgeDocuments, type KnowledgeAssetOptionsResponse, type KnowledgeDirectoryNode, type KnowledgeDocument, type KnowledgeDocumentDetail } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import { VENDOR_PLATFORMS } from '../../AssetManagement/constants';

/* ── Types ── */
interface FolderCategory {
  id: string;
  name: string;
  countKey?: string;
  icon: string;
  description: string;
}

type FileQueueStatus = 'pending' | 'reading' | 'indexing' | 'done' | 'error';

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
              title={`kb_import/${node.path}`}
            >
              {expanded ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-indigo-500" /> : <Folder className="h-3.5 w-3.5 shrink-0 text-indigo-400" />}
              <span className="truncate">{getKnowledgeDirectoryDisplayName(node)}</span>
            </button>
          )}
          {!editing && (
            <div className="flex shrink-0 items-center gap-0.5">
              {onUpload && (
                <button type="button" onClick={() => onUpload(node)} disabled={disabled || Boolean(busyAction)} className="rounded-lg p-1 text-gray-400 hover:bg-emerald-50 hover:text-emerald-600 disabled:opacity-40 dark:hover:bg-emerald-950/40" title="在此目录导入文件"><UploadCloud className="h-3.5 w-3.5" /></button>
              )}
              <button type="button" onClick={() => beginCreate(node.id)} disabled={disabled || Boolean(busyAction)} className="rounded-lg p-1 text-gray-400 hover:bg-indigo-50 hover:text-indigo-600 disabled:opacity-40 dark:hover:bg-indigo-950/40" title="新建子目录"><Plus className="h-3.5 w-3.5" /></button>
              <button type="button" onClick={() => beginRename(node)} disabled={disabled || Boolean(busyAction)} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-40 dark:hover:bg-gray-700 dark:hover:text-gray-200" title="重命名目录"><Pencil className="h-3.5 w-3.5" /></button>
              <button type="button" onClick={() => void handleDelete(node)} disabled={disabled || Boolean(busyAction)} className="rounded-lg p-1 text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40 dark:hover:bg-red-950/40" title="删除目录"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
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
          <span className="flex min-w-0 items-center gap-2"><FolderOpen className="h-3.5 w-3.5 shrink-0 text-indigo-500" /><span className="truncate">{selectedPath ? `kb_import/${selectedPath}` : '请选择目录'}</span></span>
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
  if (!selectedPath) return 'kb_import/';
  const hasVendorSegment = selectedPath.split('/').some((segment) => Boolean(getKnowledgeDirectoryVendor(segment)));
  const vendorSlug = getKnowledgeDirectoryVendor(vendor);
  const targetPath = !hasVendorSegment && vendorSlug ? `${selectedPath}/${vendorSlug}` : selectedPath;
  return `kb_import/${targetPath}/`;
}

export const KnowledgeManagementTab: React.FC = () => {
  const [stats, setStats] = useState({
    total_documents: 0,
    total_chunks: 0,
    total_vendors: 0,
    ready_indexes: 0,
  });

  const [selectedFolder, setSelectedFolder] = useState<string>('all');
  const [selectedDirectoryPath, setSelectedDirectoryPath] = useState('');
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(20);
  const [loading, setLoading] = useState(true);
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  // Modal & File Upload State
  const [showModal, setShowModal] = useState(false);
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

  // Document viewer state
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocumentDetail | null>(null);
  const [documentDetailLoading, setDocumentDetailLoading] = useState(false);
  const [documentDetailError, setDocumentDetailError] = useState('');

  const fileInputRef = useRef<HTMLInputElement>(null);
  const quickUploadInputRef = useRef<HTMLInputElement>(null);
  const directUploadTargetRef = useRef<KnowledgeDirectoryNode | null>(null);
  const documentsRequestIdRef = useRef(0);
  const documentDetailRequestIdRef = useRef(0);

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

  const fetchStatsAndDocs = useCallback(async () => {
    const requestId = ++documentsRequestIdRef.current;
    setLoading(true);
    try {
      const [s, docsPage] = await Promise.all([
        getKnowledgeStats(),
        getKnowledgeDocuments({
          sourceType: selectedFolder === 'all' ? undefined : selectedFolder,
          directoryPath: selectedDirectoryPath || undefined,
          search: searchQuery,
          page: currentPage,
          pageSize: itemsPerPage,
        }),
      ]);
      if (requestId !== documentsRequestIdRef.current) return;
      setStats(s);
      setDocuments(docsPage.items);
      setTotalDocuments(docsPage.total);
      setCurrentPage((page) => page === docsPage.page ? page : docsPage.page);
    } catch (e) {
      if (requestId !== documentsRequestIdRef.current) return;
      console.error('Failed to load knowledge metrics:', e);
    } finally {
      if (requestId === documentsRequestIdRef.current) setLoading(false);
    }
  }, [currentPage, itemsPerPage, searchQuery, selectedDirectoryPath, selectedFolder]);

  useEffect(() => {
    void fetchStatsAndDocs();
  }, [fetchStatsAndDocs]);

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
    if (showModal) void loadAssetOptions();
  }, [loadAssetOptions, showModal]);

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

    for (const [relativePath, zipEntry] of Object.entries(zip.files)) {
      if (zipEntry.dir) continue;
      // skip hidden/system files
      const segments = relativePath.split('/');
      if (segments.some(s => s.startsWith('.'))) continue;

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
    return items;
  };

  /* ── Process multiple files (including ZIPs) into the queue ── */
  const processFiles = useCallback(async (files: FileList | File[]): Promise<FileQueueItem[]> => {
    const newItems: FileQueueItem[] = [];

    for (const file of Array.from(files)) {
      const ext = getFileExtension(file.name);

      if (ext === '.zip') {
        // Extract ZIP client-side
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
        } catch {
          newItems.push({
            id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
            fileName: file.name,
            fileSize: file.size,
            content: '',
            status: 'error',
            error: 'ZIP 解压失败，文件可能已损坏',
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
      } else {
        // Binary .docx/.pdf – placeholder
        newItems.push({
          id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
          fileName: file.name,
          fileSize: file.size,
          content: `[已导入二进制文件: ${file.name}]\n系统自动提取文档文本与结构索引并转换为 Standard Markdown...`,
          status: 'pending',
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

  const selectedVendorOption = directoryVendorOptions.find((item) => item.value === vendor);

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
      knowledge_directory_path: targetPath ? `kb_import/${targetPath}` : null,
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

    setDirectUploading(true);
    setDirectUploadStatus({
      directoryPath: node.path,
      phase: 'uploading',
      completed: 0,
      total: pendingItems.length,
      message: `正在导入到 kb_import/${node.path}/…`,
    });

    let completed = 0;
    const failures: string[] = [];
    for (const item of pendingItems) {
      try {
        await addKnowledgeDocument({
          name: getFileNameWithoutExt(item.fileName),
          content: item.content.trim(),
          vendor: directVendor,
          knowledge_source_type: 'user_document',
          metadata: buildKnowledgeMetadata({
            category: node.path.split('/')[0] || node.path,
            vendorSlug,
            directoryPath: node.path,
            fileName: item.fileName,
            relativePath: item.relativePath,
          }),
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
        message: `正在导入到 kb_import/${node.path}/（${completed}/${pendingItems.length}）`,
      });
    }

    setDirectUploading(false);
    setFileQueue([]);
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
      message: `已将 ${completed} 个文件导入 kb_import/${node.path}/。`,
    });
  };

  const ensureAssetMetadataSelection = () => {
    if (knowledgeDirectory && vendor && platform) return true;
    window.alert(assetOptionsError || '请先在资产管理中导入网络设备，系统将同步厂商和平台后再导入知识文件。');
    return false;
  };

  /* ── Batch submit all pending files ── */
  const handleBatchSubmit = async () => {
    const pendingItems = fileQueue.filter(item => item.status === 'pending' && item.content.trim());
    if (pendingItems.length === 0) return;
    if (!ensureAssetMetadataSelection()) return;

    setBatchSubmitting(true);
    setBatchProgress({ done: 0, total: pendingItems.length });

    for (let i = 0; i < pendingItems.length; i++) {
      const item = pendingItems[i];
      // Mark as indexing
      setFileQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: 'indexing' as FileQueueStatus } : f));

      try {
        await addKnowledgeDocument({
          name: getFileNameWithoutExt(item.fileName),
          content: item.content.trim(),
          vendor,
          ...(platform && platform.toLowerCase() !== 'all' ? { platform } : {}),
          knowledge_source_type: sourceType,
          metadata: buildKnowledgeMetadata({
            category: item.directoryCategory,
            vendorSlug: item.directoryVendor,
            directoryPath: item.directoryPath,
            fileName: item.fileName,
            relativePath: item.relativePath,
          }),
        });
        setFileQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: 'done' as FileQueueStatus } : f));
      } catch (err: any) {
        setFileQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: 'error' as FileQueueStatus, error: err.message || '提交失败' } : f));
      }

      setBatchProgress({ done: i + 1, total: pendingItems.length });
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
        metadata: buildKnowledgeMetadata({ fileName: docName.trim() }),
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
  };

  const handleDeleteSingle = async (docId: string, docName: string) => {
    if (!window.confirm(`确认删除文档「${docName}」及其所有切片索引吗？\n此操作不可撤销。`)) return;
    try {
      await deleteKnowledgeDocument(docId);
      setSelectedDocIds(prev => { const n = new Set(prev); n.delete(docId); return n; });
      fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || '删除失败');
    }
  };

  const handleBatchDelete = async () => {
    const ids = Array.from(selectedDocIds);
    if (ids.length === 0) return;
    if (!window.confirm(`确认批量删除选中的 ${ids.length} 篇文档及其全部切片索引吗？\n此操作不可撤销。`)) return;
    setDeleting(true);
    try {
      await batchDeleteKnowledgeDocuments(ids);
      setSelectedDocIds(new Set());
      fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || '批量删除失败');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6 font-sans">
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
          <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-indigo-500" />
            企业网络知识库中心 (RAG Data Engine)
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            支持目录分类、多文件批量上传 (Markdown / HTML / PDF / DOCX / TXT / ZIP 压缩包) 与 Standard Markdown 解析。
          </p>
        </div>
      </div>

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

      {/* Two-Column Layout: Left Directory Tree Sidebar + Right Documents Table */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 items-start">
        {/* Directory management lives in the main sidebar; source types remain document metadata. */}
        <div className="bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-700/80 rounded-2xl p-4 shadow-xs space-y-3">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-700/60 pb-2">
            <h3 className="text-xs font-bold text-gray-900 dark:text-white flex items-center gap-1.5">
              <Folder className="w-4 h-4 text-indigo-500" />
              知识库目录
            </h3>
            <span className="text-[10px] text-gray-400 font-mono">{directoryTree.length} 个根目录</span>
          </div>
          <button
            type="button"
            onClick={() => {
              setSelectedDirectoryPath('');
              setSelectedFolder('all');
              setCurrentPage(1);
              setSelectedDocIds(new Set());
            }}
            className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left text-xs transition ${
              !selectedDirectoryPath
                ? 'bg-indigo-50 font-semibold text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300'
                : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700/60'
            }`}
          >
            <FolderOpen className="h-4 w-4 text-amber-500" />
            <span>全部知识文档</span>
          </button>
          {directUploadStatus && (
            <div className={`rounded-xl px-2.5 py-2 text-[10px] leading-4 ${
              directUploadStatus.phase === 'error'
                ? 'bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-300'
                : directUploadStatus.phase === 'success'
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                : 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300'
            }`}>
              <div className="flex items-start gap-1.5">
                {directUploadStatus.phase === 'uploading' || directUploadStatus.phase === 'processing'
                  ? <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin" />
                  : directUploadStatus.phase === 'success'
                  ? <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" />
                  : directUploadStatus.phase === 'error'
                  ? <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  : null}
                <span>{directUploadStatus.message}</span>
              </div>
              {directUploadStatus.phase === 'uploading' && directUploadStatus.total > 0 && (
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-indigo-200 dark:bg-indigo-900">
                  <div
                    className="h-full rounded-full bg-indigo-600 transition-all"
                    style={{ width: `${(directUploadStatus.completed / directUploadStatus.total) * 100}%` }}
                  />
                </div>
              )}
            </div>
          )}
          <DirectoryTreePicker
            inline
            nodes={directoryTree}
            selectedPath={selectedDirectoryPath}
            loading={directoryTreeLoading}
            error={directoryTreeError}
            disabled={directUploading}
            onSelect={(node) => {
              setSelectedDirectoryPath(node.path);
              setKnowledgeDirectory(node.path);
              setSelectedFolder('all');
              setCurrentPage(1);
              setSelectedDocIds(new Set());
            }}
            onCreate={handleCreateDirectory}
            onRename={handleRenameDirectory}
            onDelete={handleDeleteDirectory}
            onUpload={handleDirectoryUpload}
          />
        </div>
        {/* Right Content Area: Document Management Table */}
        <div className="lg:col-span-3 space-y-4">
          {/* Action Bar & Search */}
          <div className="flex items-center justify-between gap-4 bg-white dark:bg-gray-800 p-3 rounded-2xl border border-gray-200/80 dark:border-gray-700/80 shadow-xs">
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-400" />
              <input
                type="text"
                placeholder="在当前目录中搜索文档名称、厂商或平台..."
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl focus:outline-none focus:border-indigo-500 dark:text-white"
              />
            </div>

            <div className="flex items-center gap-3">
              {selectedDocIds.size > 0 && (
                <button
                  onClick={handleBatchDelete}
                  disabled={deleting}
                  className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-xs transition cursor-pointer disabled:opacity-50"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  {deleting ? '删除中...' : `批量删除 (${selectedDocIds.size})`}
                </button>
              )}
              <div className="text-xs text-gray-500 dark:text-gray-400">
                当前目录: <strong className="text-gray-800 dark:text-gray-200 font-semibold">{selectedDirectoryPath ? `kb_import/${selectedDirectoryPath}` : '全部知识文档'}</strong> ({totalDocuments} 篇)
              </div>
            </div>
          </div>

          {/* Table Container */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-700/80 rounded-2xl overflow-hidden shadow-xs">
            {loading ? (
              <div className="p-8 text-center text-xs text-gray-400">数据加载中...</div>
            ) : documents.length === 0 ? (
              <div className="p-12 text-center space-y-3">
                <BookOpen className="w-8 h-8 text-gray-300 mx-auto" />
                <div className="text-sm font-semibold text-gray-700 dark:text-gray-300">当前目录暂无符合条件的知识文档</div>
                <p className="text-xs text-gray-400">点击上方“上传本地知识文件”导入属于您的企业文档。</p>
              </div>
            ) : (
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-xs text-left">
                <thead className="bg-gray-50 dark:bg-gray-900/60 text-gray-500 dark:text-gray-400 font-semibold">
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
                            <span className="truncate underline-offset-4 group-hover:underline">{doc.name}</span>
                            <Eye className="h-3.5 w-3.5 flex-shrink-0 text-slate-300 opacity-0 transition group-hover:text-indigo-400 group-hover:opacity-100" />
                          </button>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded-full font-medium text-[11px] ${badge.bg} ${badge.color}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-600 dark:text-gray-300">
                          {getVendorDisplayLabel(doc.vendor)} / {getPlatformDisplayLabel(doc.vendor, doc.platform)}
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-700 dark:text-gray-200">
                          {doc.chunk_count || 1} 切片
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-medium">
                            <CheckCircle2 className="w-3.5 h-3.5" /> Ready (就绪)
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-400 font-mono text-[11px]">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3 text-center">
                          <button
                            onClick={() => handleDeleteSingle(doc.id, doc.name)}
                            className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 rounded-lg transition cursor-pointer"
                            title="删除此文档"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
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
                <div className="rounded-2xl border border-dashed border-slate-300 px-5 py-12 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">当前文档没有可展示的内容切片。</div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 rounded-2xl border border-indigo-100 bg-indigo-50/60 px-4 py-3 text-xs leading-5 text-indigo-900/70 dark:border-indigo-900/60 dark:bg-indigo-950/20 dark:text-indigo-200/70"><Info className="h-4 w-4 shrink-0 text-indigo-500" />文档已按 Heading / CLI 结构拆分为切片，以下内容按原始顺序展示。</div>
                  {selectedDocument.chunks.map((chunk, index) => (
                    <section key={chunk.id} className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950/40">
                      <div className="flex items-start gap-3 border-b border-slate-100 bg-slate-50/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/70">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-[11px] font-bold text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">{String(chunk.page || index + 1).padStart(2, '0')}</span>
                        <div className="min-w-0"><h3 className="truncate text-sm font-bold text-slate-800 dark:text-slate-100">{chunk.section || 'General Overview'}</h3><p className="mt-0.5 text-[10px] uppercase tracking-[0.12em] text-slate-400">Chunk {index + 1}</p></div>
                        <ChevronRight className="ml-auto mt-1 h-4 w-4 shrink-0 text-slate-300" />
                      </div>
                      <pre className="whitespace-pre-wrap break-words px-4 py-4 font-mono text-xs leading-6 text-slate-700 dark:text-slate-300">{chunk.content}</pre>
                    </section>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 text-xs text-slate-400 dark:border-slate-800 sm:px-7"><span className="inline-flex items-center gap-1.5"><CalendarDays className="h-3.5 w-3.5" />入库于 {new Date(selectedDocument.created_at).toLocaleString()}</span><button type="button" onClick={closeDocument} className="rounded-xl bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700">关闭</button></div>
          </aside>
        </div>
      )}

      {/* Upload File & Create Document Modal */}
      {false && showModal && (
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
                        文本格式：<strong>.md / .html / .txt / .json / .yaml / .csv / .xml / .conf</strong>
                      </div>
                      <div>
                        压缩包：<strong className="text-amber-500">.zip</strong> (自动解压提取全部文本文件)
                      </div>
                      <div>
                        二进制：<strong>.docx / .pdf</strong> (预留)
                      </div>
                    </div>
                  </div>
                </div>

                {/* Metadata selectors (shared for all files in batch) */}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标知识目录</label>
                    <div className="flex min-h-[38px] items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50/60 px-3 py-2 text-xs text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-300">
                      <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate font-mono">{getDirectoryImportPath(knowledgeDirectory, vendor)}</span>
                    </div>
                    <p className="mt-1 text-[10px] text-gray-400">目标来自左侧目录节点的导入按钮。</p>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">资料来源 (文档元数据)</label>
                    <select
                      value={sourceType}
                      onChange={(e) => setSourceType(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="internal_sop">📘 企业内部 SOP 目录</option>
                      <option value="official_vendor">🏢 厂商官方手册库</option>
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

                    <div className="max-h-48 overflow-y-auto space-y-1 pr-1">
                      {fileQueue.map((item) => (
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
                      ))}
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
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标知识目录</label>
                    <div className="flex min-h-[38px] items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50/60 px-3 py-2 text-xs text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/30 dark:text-indigo-300">
                      <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                      <span className="truncate font-mono">{getDirectoryImportPath(knowledgeDirectory, vendor)}</span>
                    </div>
                    <p className="mt-1 text-[10px] text-gray-400">目标来自左侧目录节点的导入按钮。</p>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">资料来源 (文档元数据)</label>
                    <select
                      value={sourceType}
                      onChange={(e) => setSourceType(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="internal_sop">📘 企业内部 SOP 目录</option>
                      <option value="official_vendor">🏢 厂商官方手册库</option>
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
    </div>
  );
};

export default KnowledgeManagementTab;

