import { DataTable } from '../../../components/DataTable';
import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import JSZip from 'jszip';
import {
  BookOpen,
  ChevronDown,
  MoreHorizontal,
  Database,
  Layers,
  Plus,
  Trash2,
  CheckCircle2,
  Upload,
  FileText,
  HelpCircle,
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
import { getKnowledgeStats, getKnowledgeDocuments, exportKnowledgeDocuments, importKnowledgeBundle, getKnowledgeDocument, getKnowledgeDocumentFacets, getKnowledgeAssetOptions, getKnowledgeDirectories, createKnowledgeDirectory, renameKnowledgeDirectory, deleteKnowledgeDirectory, addKnowledgeDocument, importKnowledgeEnterpriseSop, importKnowledgeEnterpriseSopBatch, previewKnowledgeDocumentMetadata, clearSampleKnowledge, getKnowledgeDocumentActionImpact, deleteKnowledgeDocument, disableKnowledgeDocument, enableKnowledgeDocument, reparseKnowledgeDocument, rechunkKnowledgeDocument, reindexKnowledgeDocument, batchDeleteKnowledgeDocuments, compareKnowledgeDocumentVersions, publishKnowledgeDocumentVersion, supersedeKnowledgeDocumentVersion, rollbackKnowledgeDocumentVersion, getSemanticEmbeddingStatus, startKnowledgeReindex, type KnowledgeAssetOptionsResponse, type KnowledgeDirectoryNode, type KnowledgeDocument, type KnowledgeDocumentDetail, type KnowledgeDocumentFacets, type KnowledgeDocumentAction, type KnowledgeDocumentActionImpact, type KnowledgeDocumentVersionComparison, type KnowledgeMetadataPreview, type SemanticEmbeddingStatusResponse } from '../../../api/ai';
import Pagination from '../../../components/Pagination';
import type { TableExportData } from '../../../components/ui/TableExportMenu';
import { VENDOR_PLATFORMS } from '../../AssetManagement/constants';
import SourceRegistryPanel from './SourceRegistryPanel';
import RagEvaluationPanel from './RagEvaluationPanel';
import RetrievalTracePanel from './RetrievalTracePanel';
import UATSignoffPanel from './UATSignoffPanel';
import IngestionJobsPanel from './IngestionJobsPanel';
import OfficialSeedPanel from './OfficialSeedPanel';
import KnowledgeAdminNavigation, { type KnowledgeAdminView } from './KnowledgeAdminNavigation';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../../../components/ui/ActionIconButton';
import { useCoreApp } from '../../../contexts/AppDomainContext';
import { aiAdminText, type AIAdminLanguage } from '../../../i18n/aiAdmin';
import { useEscapeClose } from '../../../hooks/useEscapeClose';
import { useFocusTrap } from '../../../hooks/useFocusTrap';

import { TableActionCell, TableActionHeader } from '../../../components/ui/TableActionColumn';
import { PageHeader } from '../../../components/ui/PageHeader';
import { SummaryBar } from '../../../components/ui/SummaryBar';
import { Panel } from '../../../components/ui/Panel';
import { EmptyState } from '../../../components/ui/EmptyState';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';
import { knowledgePageCopy } from './KnowledgeManagementTab.copy';
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
  { id: '01_product', labelKey: 'ai.knowledge.directory.product.label', descriptionKey: 'ai.knowledge.directory.product.description' },
  { id: '02_commands', labelKey: 'ai.knowledge.directory.commands.label', descriptionKey: 'ai.knowledge.directory.commands.description' },
  { id: '03_configuration', labelKey: 'ai.knowledge.directory.configuration.label', descriptionKey: 'ai.knowledge.directory.configuration.description' },
  { id: '04_cli_outputs', labelKey: 'ai.knowledge.directory.cliOutputs.label', descriptionKey: 'ai.knowledge.directory.cliOutputs.description' },
  { id: '05_troubleshooting', labelKey: 'ai.knowledge.directory.troubleshooting.label', descriptionKey: 'ai.knowledge.directory.troubleshooting.description' },
  { id: '06_examples', labelKey: 'ai.knowledge.directory.examples.label', descriptionKey: 'ai.knowledge.directory.examples.description' },
] as const;

const KNOWLEDGE_DIRECTORY_IDS: Set<string> = new Set(KNOWLEDGE_DIRECTORY_OPTIONS.map((item) => item.id));
const KNOWLEDGE_DIRECTORY_DISPLAY_LABELS: Record<string, string> = {
  '01_product': 'ai.knowledge.directory.product.label',
  '02_commands': 'ai.knowledge.directory.commands.label',
  '03_configuration': 'ai.knowledge.directory.configuration.label',
  '04_cli_outputs': 'ai.knowledge.directory.cliOutputs.label',
  '05_troubleshooting': 'ai.knowledge.directory.troubleshooting.label',
  '06_examples': 'ai.knowledge.directory.examples.label',
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

function getKnowledgeDirectoryDisplayName(node: KnowledgeDirectoryNode, language: AIAdminLanguage = 'zh'): string {
  if (KNOWLEDGE_DIRECTORY_DISPLAY_LABELS[node.name]) return aiAdminText(KNOWLEDGE_DIRECTORY_DISPLAY_LABELS[node.name], language);
  if (getKnowledgeDirectoryVendor(node.name)) return getVendorDisplayLabel(node.name, language);
  return node.name;
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
  Cisco: 'ai.knowledge.vendor.cisco',
  Huawei: 'ai.knowledge.vendor.huawei',
  H3C: 'ai.knowledge.vendor.h3c',
  Ruijie: 'ai.knowledge.vendor.ruijie',
  ZTE: 'ai.knowledge.vendor.zte',
  cisco: 'ai.knowledge.vendor.cisco',
  huawei: 'ai.knowledge.vendor.huawei',
  h3c: 'ai.knowledge.vendor.h3c',
  ruijie: 'ai.knowledge.vendor.ruijie',
};

function getVendorDisplayLabel(vendor: string, language: AIAdminLanguage = 'zh'): string {
  const key = VENDOR_DISPLAY_LABELS[vendor];
  return key ? aiAdminText(key, language) : vendor;
}

function getPlatformDisplayLabel(vendor: string, platform?: string | null, language: AIAdminLanguage = 'zh'): string {
  if (!platform || platform.toLowerCase() === 'all') return aiAdminText('ai.knowledge.platform.generic', language);
  return VENDOR_PLATFORMS[vendor]?.find((item) => item.value === platform)?.label || platform;
}

interface DirectoryTreePickerProps {
  nodes: KnowledgeDirectoryNode[];
  selectedPath: string;
  loading: boolean;
  error?: string;
  disabled?: boolean;
  canManage?: boolean;
  inline?: boolean;
  title?: string;
  onUpload?: (node: KnowledgeDirectoryNode) => void;
  onSelect: (node: KnowledgeDirectoryNode) => void;
  onCreate: (name: string, parentId: string | null) => Promise<void>;
  onRename: (node: KnowledgeDirectoryNode, name: string) => Promise<void>;
  onDelete: (node: KnowledgeDirectoryNode) => Promise<void>;
}

export const DirectoryTreePicker: React.FC<DirectoryTreePickerProps> = ({
  nodes,
  selectedPath,
  loading,
  error,
  disabled,
  canManage = false,
  inline = false,
  title,
  onUpload,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}) => {
  const { language } = useCoreApp();
  const tx = (key: string, variables: Record<string, string | number> = {}) => aiAdminText(key, language, variables);
  const [open, setOpen] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [creatingParentId, setCreatingParentId] = useState<string | null | undefined>(undefined);
  const [draftName, setDraftName] = useState('');
  const [editingNodeId, setEditingNodeId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [actionMenuNodeId, setActionMenuNodeId] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');

  useEffect(() => {
    setExpandedIds((previous) => {
      const next = new Set(previous);
      if (previous.size === 0 && selectedPath) {
        flattenDirectoryNodes(nodes).forEach((node) => {
          if (selectedPath === node.path || selectedPath.startsWith(`${node.path}/`)) next.add(node.id);
        });
      }
      return next;
    });
  }, [nodes, selectedPath]);

  const beginCreate = (parentId: string | null) => {
    if (!canManage) return;
    setOpen(true);
    setCreatingParentId(parentId);
    setDraftName('');
    setActionError('');
    setEditingNodeId(null);
  };

  const submitCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canManage) return;
    const name = draftName.trim();
    if (!name || creatingParentId === undefined) return;
    setBusyAction('create');
    setActionError('');
    try {
      await onCreate(name, creatingParentId);
      setCreatingParentId(undefined);
      setDraftName('');
    } catch (err: any) {
      setActionError(err?.message || tx('ai.knowledge.directory.createFailed'));
    } finally {
      setBusyAction(null);
    }
  };

  const beginRename = (node: KnowledgeDirectoryNode) => {
    if (!canManage) return;
    setOpen(true);
    setCreatingParentId(undefined);
    setEditingNodeId(node.id);
    setEditingName(node.name);
    setActionError('');
  };

  const submitRename = async (event: React.FormEvent, node: KnowledgeDirectoryNode) => {
    event.preventDefault();
    if (!canManage) return;
    const name = editingName.trim();
    if (!name) return;
    setBusyAction(`rename:${node.id}`);
    setActionError('');
    try {
      await onRename(node, name);
      setEditingNodeId(null);
    } catch (err: any) {
      setActionError(err?.message || tx('ai.knowledge.directory.renameFailed'));
    } finally {
      setBusyAction(null);
    }
  };

  const handleDelete = async (node: KnowledgeDirectoryNode) => {
    if (!canManage) return;
    const hasChildren = node.children.length > 0;
    const message = hasChildren
      ? tx('ai.knowledge.directory.deleteWithChildrenConfirm', { name: node.name, count: countDirectoryNodes(node) })
      : tx('ai.knowledge.directory.deleteConfirm', { name: node.name });
    if (!window.confirm(message)) return;
    setBusyAction(`delete:${node.id}`);
    setActionError('');
    try {
      await onDelete(node);
    } catch (err: any) {
      setActionError(err?.message || tx('ai.knowledge.directory.deleteFailed'));
    } finally {
      setBusyAction(null);
    }
  };

  const renderNode = (node: KnowledgeDirectoryNode): React.ReactNode => {
    const expanded = expandedIds.has(node.id);
    const selected = selectedPath === node.path;
    const editing = canManage && editingNodeId === node.id;
    const rowBusy = Boolean(busyAction && (busyAction === 'create' || busyAction.endsWith(`:${node.id}`)));
    return (
      <React.Fragment key={node.id}>
        <div className="group relative flex items-center gap-1 py-0.5" style={{ paddingLeft: `${Math.min(node.depth, 8) * 14}px` }}>
          <button
            type="button"
            onClick={() => setExpandedIds((previous) => {
              const next = new Set(previous);
              if (next.has(node.id)) next.delete(node.id); else next.add(node.id);
              return next;
            })}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-fg-subtle hover:bg-surface-muted "
            aria-label={expanded ? tx('ai.knowledge.directory.collapse') : tx('ai.knowledge.directory.expand')}
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
                className="min-w-0 flex-1 rounded-lg border border-accent/30 bg-surface px-2 py-1 text-xs "
              />
              <button type="submit" disabled={rowBusy || !editingName.trim()} className="rounded-lg p-1 text-success hover:bg-success-subtle disabled:opacity-50 " title={tx('ai.knowledge.directory.saveRename')}><CheckCircle2 className="h-3.5 w-3.5" /></button>
              <button type="button" onClick={() => setEditingNodeId(null)} disabled={rowBusy} className="rounded-lg p-1 text-fg-subtle hover:bg-surface-muted " title={tx('ai.knowledge.common.cancel')}><X className="h-3.5 w-3.5" /></button>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => { onSelect(node); setOpen(false); }}
              disabled={disabled}
              className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition ${selected ? 'bg-accent-subtle font-semibold text-accent ' : 'text-fg hover:bg-surface-muted '}`}
              title={tx('ai.knowledge.directory.generic', { path: node.path })}
            >
              {expanded ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-accent" /> : <Folder className="h-3.5 w-3.5 shrink-0 text-accent" />}
              <span className="truncate">{getKnowledgeDirectoryDisplayName(node, language)}</span>
            </button>
          )}
          {!editing && canManage && (
            <div className="relative shrink-0">
              <button
                type="button"
                aria-label={tx('ai.knowledge.directory.actions')}
                aria-expanded={actionMenuNodeId === node.id}
                onClick={(event) => {
                  event.stopPropagation();
                  setActionMenuNodeId((prev) => (prev === node.id ? null : node.id));
                }}
                disabled={disabled || Boolean(busyAction)}
                className={`flex h-6 w-6 items-center justify-center rounded-md text-fg-subtle transition hover:bg-surface-muted hover:text-fg ${
                  actionMenuNodeId === node.id ? 'opacity-100 bg-surface-muted text-fg' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'
                }`}
              >
                <MoreHorizontal className="h-3.5 w-3.5" />
              </button>
              {actionMenuNodeId === node.id && (
                <div
                  role="menu"
                  className="absolute right-0 top-7 z-30 min-w-[136px] rounded-xl border border-line bg-surface p-1 shadow-lg"
                  onMouseLeave={() => setActionMenuNodeId(null)}
                >
                  {onUpload && (
                    <button
                      type="button"
                      onClick={() => { setActionMenuNodeId(null); onUpload(node); }}
                      disabled={disabled || Boolean(busyAction)}
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-fg hover:bg-surface-muted"
                    >
                      <UploadCloud className="h-3.5 w-3.5 text-success" />
                      <span>{tx('ai.knowledge.directory.uploadHere')}</span>
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => { setActionMenuNodeId(null); beginCreate(node.id); }}
                    disabled={disabled || Boolean(busyAction)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-fg hover:bg-surface-muted"
                  >
                    <Plus className="h-3.5 w-3.5 text-accent" />
                    <span>{tx('ai.knowledge.directory.createChild')}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => { setActionMenuNodeId(null); beginRename(node); }}
                    disabled={disabled || Boolean(busyAction)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-fg hover:bg-surface-muted"
                  >
                    <Pencil className="h-3.5 w-3.5 text-fg-muted" />
                    <span>{tx('ai.knowledge.directory.rename')}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => { setActionMenuNodeId(null); void handleDelete(node); }}
                    disabled={disabled || Boolean(busyAction)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-danger hover:bg-danger-subtle"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span>{tx('ai.knowledge.directory.delete')}</span>
                  </button>
                </div>
              )}
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
          className="flex w-full items-center justify-between gap-2 rounded-xl border border-line-strong bg-surface px-3 py-2 text-left text-xs text-fg shadow-sm transition hover:border-accent disabled:cursor-not-allowed disabled:opacity-60 "
        >
          <span className="flex min-w-0 items-center gap-2"><FolderOpen className="h-3.5 w-3.5 shrink-0 text-accent" /><span className="truncate">{selectedPath ? tx('ai.knowledge.directory.generic', { path: selectedPath }) : tx('ai.knowledge.directory.select')}</span></span>
          <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-fg-subtle transition-transform ${open ? 'rotate-90' : ''}`} />
        </button>
      )}
      {showTree && (
        <div className={inline ? 'overflow-hidden rounded-xl border border-line bg-surface p-2 ' : 'absolute left-0 right-0 z-40 mt-1 overflow-hidden rounded-xl border border-line bg-surface p-2 shadow-xl '}>
          <div className="flex items-center justify-between gap-2 border-b border-line pb-2">
            <span className="min-w-0 truncate text-xs font-semibold text-fg" title={title || tx('ai.knowledge.directory.pickerTitle')}>{title || tx('ai.knowledge.directory.pickerTitle')}</span>
            {canManage && <button type="button" onClick={() => beginCreate(null)} disabled={disabled || Boolean(busyAction)} className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-lg bg-accent-subtle px-2 py-1 text-xs font-semibold text-accent hover:bg-accent-subtle disabled:opacity-40" title={tx('ai.knowledge.directory.createRoot')}><Plus className="h-3 w-3 shrink-0" />{tx('ai.knowledge.directory.create')}</button>}
          </div>
          {canManage && creatingParentId !== undefined && (
            <form onSubmit={(event) => void submitCreate(event)} className="mt-2 rounded-lg border border-accent/30 bg-accent-subtle p-2 ">
              <div className="mb-1 text-xs text-accent ">{tx('ai.knowledge.directory.createUnder', { scope: creatingParentId ? tx('ai.knowledge.directory.selectedChild') : tx('ai.knowledge.directory.root') })}</div>
              <div className="flex items-center gap-1">
                <input autoFocus value={draftName} onChange={(event) => setDraftName(event.target.value)} placeholder={tx('ai.knowledge.directory.namePlaceholder')} disabled={busyAction === 'create'} className="min-w-0 flex-1 rounded-lg border border-accent/30 bg-surface px-2 py-1.5 text-xs " />
                <button type="submit" disabled={busyAction === 'create' || !draftName.trim()} className="rounded-lg bg-accent px-2 py-1.5 text-xs font-semibold text-white disabled:opacity-50">{busyAction === 'create' ? <Loader2 className="h-3 w-3 animate-spin" /> : tx('ai.knowledge.directory.create')}</button>
                <button type="button" onClick={() => setCreatingParentId(undefined)} disabled={busyAction === 'create'} className="rounded-lg p-1.5 text-fg-subtle hover:bg-surface " title={tx('ai.knowledge.common.cancel')}><X className="h-3.5 w-3.5" /></button>
              </div>
            </form>
          )}
          {(error || actionError) && <div className="mt-2 rounded-lg bg-danger-subtle px-2 py-1.5 text-xs text-danger ">{actionError || error}</div>}
           <div className={`mt-2 overflow-y-auto pr-1 ${inline ? 'max-h-[480px]' : 'max-h-72'}`}>
            {loading ? <div className="flex items-center gap-2 px-2 py-5 text-xs text-fg-subtle"><Loader2 className="h-4 w-4 animate-spin" />{tx('ai.knowledge.directory.loading')}</div> : nodes.length === 0 ? <div className="px-2 py-5 text-center text-xs text-fg-subtle">{tx('ai.knowledge.directory.empty')}</div> : nodes.map(renderNode)}
          </div>
        </div>
      )}
    </div>
  );
};

interface SearchableFacetSelectProps {
  label: string;
  placeholder: string;
  disabledPlaceholder: string;
  searchPlaceholder: string;
  allLabel: string;
  emptyLabel: string;
  value: string;
  options: Array<{ value: string; count: number }>;
  disabled?: boolean;
  onChange: (value: string) => void;
}

const SearchableFacetSelect: React.FC<SearchableFacetSelectProps> = ({
  label,
  placeholder,
  disabledPlaceholder,
  searchPlaceholder,
  allLabel,
  emptyLabel,
  value,
  options,
  disabled = false,
  onChange,
}) => {
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  const knownOptions = useMemo(
    () => options.filter((item) => item.value.trim() && item.value.trim().toUpperCase() !== 'UNKNOWN'),
    [options],
  );
  const filteredOptions = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return knownOptions;
    return knownOptions.filter((item) => item.value.toLowerCase().includes(q));
  }, [knownOptions, keyword]);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  useEffect(() => {
    if (disabled && open) setOpen(false);
  }, [disabled, open]);

  return (
    <div ref={containerRef} className="relative min-w-0">
      <button
        type="button"
        disabled={disabled}
        aria-label={label}
        aria-expanded={open}
        onClick={() => {
          if (disabled) return;
          setOpen((prev) => !prev);
          setKeyword('');
        }}
        className={`flex w-full items-center justify-between gap-1.5 rounded-xl border px-2.5 py-2 text-left text-xs transition ${
          disabled
            ? 'cursor-not-allowed border-line bg-surface-muted/60 text-fg-subtle opacity-65'
            : value
              ? 'border-accent bg-accent/5 font-medium text-accent'
              : 'border-line bg-surface-muted text-fg hover:border-accent/60'
        }`}
      >
        <span className="min-w-0 flex-1 truncate">
          {disabled ? disabledPlaceholder : value || placeholder}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {value && !disabled && (
            <span
              role="button"
              tabIndex={-1}
              aria-label={`清除${label}`}
              onClick={(event) => {
                event.stopPropagation();
                onChange('');
                setOpen(false);
              }}
              className="rounded p-0.5 text-fg-subtle hover:bg-surface hover:text-fg"
            >
              ×
            </span>
          )}
          <ChevronDown className={`h-3.5 w-3.5 text-fg-subtle transition-transform ${open ? 'rotate-180' : ''}`} />
        </span>
      </button>

      {open && !disabled && (
        <div className="absolute left-0 right-0 z-30 mt-1 rounded-xl border border-line bg-surface p-2 shadow-lg">
          <div className="relative mb-1.5">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-subtle" />
            <input
              type="search"
              autoFocus
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder={searchPlaceholder}
              className="w-full rounded-lg border border-line bg-surface-muted py-1.5 pl-7 pr-2 text-xs text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none"
            />
          </div>
          <div className="max-h-56 overflow-y-auto space-y-0.5">
            {!keyword.trim() && (
              <button
                type="button"
                onClick={() => {
                  onChange('');
                  setOpen(false);
                }}
                className={`flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs transition ${
                  !value ? 'bg-accent/10 font-semibold text-accent' : 'text-fg-muted hover:bg-surface-muted'
                }`}
              >
                <span>{allLabel}</span>
              </button>
            )}
            {filteredOptions.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => {
                  onChange(item.value);
                  setOpen(false);
                }}
                className={`flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition ${
                  value === item.value
                    ? 'bg-accent text-white font-semibold'
                    : 'text-fg hover:bg-surface-muted'
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{item.value}</span>
                <span className={`shrink-0 text-[11px] ${value === item.value ? 'text-white/80' : 'text-fg-subtle'}`}>
                  {item.count}
                </span>
              </button>
            ))}
            {filteredOptions.length === 0 && (
              <div className="px-2 py-3 text-center text-xs text-fg-subtle">{emptyLabel}</div>
            )}
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

function getDirectoryImportPath(directoryPath: string, vendor: string, language: AIAdminLanguage = 'zh'): string {
  const selectedPath = String(directoryPath || '').replace(/^\/+|\/+$/g, '');
  if (!selectedPath) return aiAdminText('ai.knowledge.directory.all', language);
  const hasVendorSegment = selectedPath.split('/').some((segment) => Boolean(getKnowledgeDirectoryVendor(segment)));
  const vendorSlug = getKnowledgeDirectoryVendor(vendor);
  const targetPath = !hasVendorSegment && vendorSlug ? `${selectedPath}/${vendorSlug}` : selectedPath;
  return targetPath.split('/').filter(Boolean).join(' / ');
}

export const KnowledgeManagementTab: React.FC = () => {
  const { currentUser, language } = useCoreApp();
  const tx = (key: string, variables: Record<string, string | number> = {}) => aiAdminText(key, language, variables);
  const copy = language === 'zh' ? knowledgePageCopy.zh : knowledgePageCopy.en;
  const canManageDirectories = currentUser.role === 'Administrator';

  function getKnowledgeLifecycleStatusLabel(status?: string | null): string {
    const statusKey: Record<string, string> = {
      active: 'ai.knowledge.status.active',
      published: 'ai.knowledge.status.published',
      draft: 'ai.knowledge.status.draft',
      quarantined: 'ai.knowledge.status.quarantined',
      disabled: 'ai.knowledge.status.disabled',
    };
    return status && statusKey[status] ? tx(statusKey[status]) : status || tx('ai.knowledge.status.pending');
  }

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
  const [expandedFacetGroups, setExpandedFacetGroups] = useState<Record<string, boolean>>({});
  const [totalDocuments, setTotalDocuments] = useState(0);
  const [allDirectoryDocuments, setAllDirectoryDocuments] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(10);
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
    metadataGovernanceStatus: '',
  });

  // Modal & File Upload State
  const [showModal, setShowModal] = useState(false);
  const [ingestionMode, setIngestionMode] = useState<'enterprise_sop' | null>(null);
  const [ingestionSubmitting, setIngestionSubmitting] = useState(false);
  const [ingestionError, setIngestionError] = useState('');
  const [ingestionMessage, setIngestionMessage] = useState('');
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
  const [embeddingStatus, setEmbeddingStatus] = useState<SemanticEmbeddingStatusResponse | null>(null);
  const [rebuildingEmbeddings, setRebuildingEmbeddings] = useState(false);

  const loadEmbeddingStatus = useCallback(async () => {
    try {
      const data = await getSemanticEmbeddingStatus();
      setEmbeddingStatus(data || null);
    } catch {
      // Optional status bar: keep silent if unavailable
    }
  }, []);

  useEffect(() => {
    void loadEmbeddingStatus();
  }, [loadEmbeddingStatus]);

  const handleRebuildEmbeddings = async () => {
    if (rebuildingEmbeddings) return;
    setRebuildingEmbeddings(true);
    try {
      const res = await startKnowledgeReindex({});
      const jobId = res?.job_id || res?.id || '';
      setDocumentActionNotice(
        language === 'zh'
          ? `已启动全量向量重建任务${jobId ? `（${jobId}）` : ''}，完成后请刷新查看覆盖率。`
          : `Full embedding reindex started${jobId ? ` (${jobId})` : ''}.`,
      );
      void loadEmbeddingStatus();
      void fetchStatsAndDocs();
    } catch (err: any) {
      setDocumentActionNotice(err?.message || (language === 'zh' ? '启动全量向量重建失败' : 'Failed to start reindex'));
    } finally {
      setRebuildingEmbeddings(false);
    }
  };
  const [operationsOpen, setOperationsOpen] = useState(false);
  const [advancedFiltersOpen, setAdvancedFiltersOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const quickUploadInputRef = useRef<HTMLInputElement>(null);
  const documentViewerDialogRef = useRef<HTMLDivElement>(null);
  const documentActionDialogRef = useRef<HTMLDivElement>(null);
  const uploadDialogRef = useRef<HTMLDivElement>(null);
  const directUploadTargetRef = useRef<KnowledgeDirectoryNode | null>(null);
  const documentsRequestIdRef = useRef(0);
  const documentDetailRequestIdRef = useRef(0);
  const documentsAbortRef = useRef<AbortController | null>(null);
  const documentTableRef = useRef<HTMLDivElement>(null);
  const filtersSectionRef = useRef<HTMLDivElement>(null);

  const folders: FolderCategory[] = [
    { id: 'all', name: tx('ai.knowledge.scope.all.label'), icon: '📂', description: tx('ai.knowledge.scope.all.description') },
    { id: 'internal_sop', name: tx('ai.knowledge.scope.internalSop.label'), icon: '📘', description: tx('ai.knowledge.scope.internalSop.description') },
    { id: 'official_vendor', name: tx('ai.knowledge.scope.official.label'), icon: '🏢', description: tx('ai.knowledge.scope.official.description') },
    { id: 'internal_standard', name: tx('ai.knowledge.scope.standard.label'), icon: '📜', description: tx('ai.knowledge.scope.standard.description') },
    { id: 'case', name: tx('ai.knowledge.scope.case.label'), icon: '🚨', description: tx('ai.knowledge.scope.case.description') },
    { id: 'sample', name: tx('ai.knowledge.scope.sample.label'), icon: '🧪', description: tx('ai.knowledge.scope.sample.description') },
  ];

  const directoryVendorOptions = useMemo(
    () => assetOptions.vendors.filter((item) => Boolean(getKnowledgeDirectoryVendor(item.value))),
    [assetOptions.vendors],
  );

  const knowledgeVendorOptions = useMemo(
    () => (documentFacets?.vendors || []).filter((item) => item.value && item.value !== 'UNKNOWN'),
    [documentFacets?.vendors],
  );

  const unknownFacetCount = documentFacets.unknown_count ?? Math.max(
    ...[documentFacets.vendors, documentFacets.families, documentFacets.series].map((items) => (
      items.find((item) => item.value.trim().toUpperCase() === 'UNKNOWN')?.count || 0
    )),
    0,
  );
  const selectedClassification = [semanticFilters.vendor, semanticFilters.productFamily, semanticFilters.productSeries]
    .filter(Boolean)
    .join(' / ');
  const activeFilterChips = [
    knowledgeScope !== 'all'
      ? tx(knowledgeScope === 'official' ? 'ai.knowledge.filter.scopeOfficial' : 'ai.knowledge.filter.scopeEnterprise')
      : '',
    selectedFolder !== 'all'
      ? `${tx('ai.knowledge.filter.sourceLabel')}: ${folders.find((folder) => folder.id === selectedFolder)?.name || selectedFolder}`
      : '',
    searchQuery ? `${tx('ai.knowledge.search.label')}: ${searchQuery}` : '',
    selectedClassification ? `${tx('ai.knowledge.product.title')}: ${selectedClassification}` : '',
    semanticFilters.productModel ? `${tx('ai.knowledge.filter.modelPlaceholder')}: ${semanticFilters.productModel}` : '',
    semanticFilters.osFamily ? `${tx('ai.knowledge.filter.osPlaceholder')}: ${semanticFilters.osFamily}` : '',
    semanticFilters.softwareRelease ? `${tx('ai.knowledge.filter.versionPlaceholder')}: ${semanticFilters.softwareRelease}` : '',
    semanticFilters.featureDomain ? `${tx('ai.knowledge.filter.featurePlaceholder')}: ${semanticFilters.featureDomain}` : '',
    semanticFilters.documentCategory
      ? `${tx('ai.knowledge.filter.typeLabel')}: ${KNOWLEDGE_DIRECTORY_DISPLAY_LABELS[semanticFilters.documentCategory] ? tx(KNOWLEDGE_DIRECTORY_DISPLAY_LABELS[semanticFilters.documentCategory]) : semanticFilters.documentCategory}`
      : '',
    semanticFilters.status !== 'active'
      ? `${tx('ai.knowledge.filter.lifecycleLabel')}: ${getKnowledgeLifecycleStatusLabel(semanticFilters.status)}`
      : '',
    semanticFilters.metadataGovernanceStatus
      ? `${tx('ai.knowledge.governance.filterLabel')}: ${semanticFilters.metadataGovernanceStatus === 'pending_review' ? tx('ai.knowledge.governance.pending') : tx('ai.knowledge.governance.ready')}`
      : '',
  ].filter(Boolean);

  const fetchStatsAndDocs = useCallback(async () => {
    const requestId = ++documentsRequestIdRef.current;
    documentsAbortRef.current?.abort();
    const controller = new AbortController();
    documentsAbortRef.current = controller;
    setLoading(true);
    setLoadError('');
    setPermissionDenied(false);
    setAllDirectoryDocuments(0);
    try {
      const allDirectoryPageRequest = selectedDirectoryPath
        ? getKnowledgeDocuments({
          sourceType: selectedFolder === 'all' ? undefined : selectedFolder,
          knowledgeScope,
          search: searchQuery,
          ...semanticFilters,
          page: 1,
          pageSize: 1,
          signal: controller.signal,
        })
        : Promise.resolve(null);
      const [s, docsPage, facets, allDirectoryPage] = await Promise.all([
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
          vendor: semanticFilters.vendor,
          productFamily: semanticFilters.productFamily,
          productSeries: semanticFilters.productSeries,
          metadataGovernanceStatus: semanticFilters.metadataGovernanceStatus,
          signal: controller.signal,
        }),
        allDirectoryPageRequest,
      ]);
      if (requestId !== documentsRequestIdRef.current) return;
      setStats(s);
      setDocuments(docsPage.items);
      setTotalDocuments(docsPage.total);
      setAllDirectoryDocuments(allDirectoryPage?.total ?? docsPage.total);
      setDocumentFacets(facets);
      setCurrentPage((page) => page === docsPage.page ? page : docsPage.page);
    } catch (e: any) {
      if (requestId !== documentsRequestIdRef.current) return;
      if (e?.name === 'AbortError') return;
      const denied = Number(e?.status) === 403;
      setPermissionDenied(denied);
      setLoadError(denied ? tx('ai.knowledge.error.permission') : (e?.message || tx('ai.knowledge.error.load')));
      console.error('Failed to load knowledge metrics:', e);
    } finally {
      if (requestId === documentsRequestIdRef.current) setLoading(false);
    }
  }, [currentPage, itemsPerPage, knowledgeScope, language, searchQuery, selectedDirectoryPath, selectedFolder, semanticFilters]);

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
        metadataGovernanceStatus: semanticFilters.metadataGovernanceStatus,
      });
      const url = URL.createObjectURL(exported.blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = exported.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setDocumentActionNotice(tx('ai.knowledge.message.exported', { count: exported.documentCount, size: formatFileSize(exported.contentBytes) }));
    } catch (error: any) {
      setDocumentActionNotice(error?.message || tx('ai.knowledge.error.export'));
    } finally {
      setExporting(false);
    }
  }, [exporting, knowledgeScope, language, searchQuery, selectedDirectoryPath, selectedFolder, semanticFilters]);

  const exportKnowledgeTable = useCallback(async (): Promise<TableExportData> => {
    const allDocuments: KnowledgeDocument[] = [];
    let page = 1;
    let total = Number.POSITIVE_INFINITY;
    while (allDocuments.length < total) {
      const result = await getKnowledgeDocuments({
        sourceType: selectedFolder === 'all' ? undefined : selectedFolder,
        knowledgeScope,
        directoryPath: selectedDirectoryPath || undefined,
        search: searchQuery,
        ...semanticFilters,
        page,
        pageSize: 100,
      });
      allDocuments.push(...result.items);
      total = result.total;
      if (!result.items.length && allDocuments.length < total) {
        throw new Error(`知识文档导出不完整：已读取 ${allDocuments.length} / ${total} 条。`);
      }
      page += 1;
    }

    const headers = [
      tx('ai.knowledge.table.name'),
      tx('ai.knowledge.table.source'),
      tx('ai.knowledge.table.category'),
      tx('ai.knowledge.table.family'),
      tx('ai.knowledge.table.model'),
      tx('ai.knowledge.table.vendor'),
      tx('ai.knowledge.table.platform'),
      tx('ai.knowledge.table.osFamily'),
      tx('ai.knowledge.table.release'),
      tx('ai.knowledge.table.chunks'),
      tx('ai.knowledge.table.index'),
      tx('ai.knowledge.table.created'),
    ];
    const rows = allDocuments.map((doc) => {
      const badge = sourceBadges[doc.knowledge_source_type] || sourceBadges.user_document;
      return [
        doc.name,
        badge.label,
        doc.document_category || '',
        doc.product_family || '',
        doc.product_model || '',
        doc.vendor ? getVendorDisplayLabel(doc.vendor, language) : '',
        getPlatformDisplayLabel(doc.vendor, doc.platform, language),
        doc.os_family || '',
        doc.software_release || '',
        tx('ai.knowledge.table.chunkCount', { count: doc.chunk_count || 1 }),
        getDocumentStatusLabel(doc),
        new Date(doc.created_at).toLocaleDateString(),
      ];
    });
    return { headers, rows };
  }, [knowledgeScope, language, searchQuery, selectedDirectoryPath, selectedFolder, semanticFilters]);

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
      setAssetOptionsError(error?.message || tx('ai.knowledge.error.assetSync'));
    } finally {
      setAssetOptionsLoading(false);
    }
  }, [language]);

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
      setDirectoryTreeError(error?.message || tx('ai.knowledge.error.directoryLoad'));
      return [];
    } finally {
      setDirectoryTreeLoading(false);
    }
  }, [language]);

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
      reader.onerror = () => reject(new Error(tx('ai.knowledge.error.fileRead')));
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
        throw new Error(tx('ai.knowledge.error.manifestParse'));
      }
      if (String(manifest?.schema_version || '').startsWith('knowledge-export-')) {
        if (manifest?.embeddings_exported === true || manifest?.reindex_required_on_import !== true) {
          throw new Error(tx('ai.knowledge.error.manifestReindex'));
        }
        if (!Array.isArray(manifest?.documents)) {
          throw new Error(tx('ai.knowledge.error.manifestDocuments'));
        }
      }
    }

    for (const [relativePath, zipEntry] of Object.entries(zip.files)) {
      if (zipEntry.dir) continue;
      // skip hidden/system files
      const segments = relativePath.split('/');
      if (segments.some(s => s === '..') || relativePath.startsWith('/')) {
        throw new Error(tx('ai.knowledge.error.unsafeZipPath'));
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
        throw new Error(tx('ai.knowledge.error.manifestCount', { expected, actual: items.length }));
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
              error: tx('ai.knowledge.error.zipNoText'),
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
            error: error?.message || tx('ai.knowledge.error.zipExtract'),
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
            error: tx('ai.knowledge.error.fileRead'),
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
          error: tx('ai.knowledge.error.unsupportedFormat', { extension: ext || tx('ai.knowledge.status.noExtension') }),
        });
      }
    }

    setFileQueue(prev => [...prev, ...newItems]);
    return newItems;
  }, [language]);

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
      message: tx('ai.knowledge.message.readingFiles', { count: files.length }),
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
          message: error?.message || tx('ai.knowledge.error.fileReadRetry'),
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

  const handleEnterpriseSopImport = async (event: React.FormEvent) => {
    event.preventDefault();
    setIngestionError('');
    setIngestionMessage('');
    if (!enterpriseSopFile) {
      setIngestionError(tx('ai.knowledge.ingestion.fileRequired'));
      return;
    }
    if (!enterpriseTitle.trim() || !enterpriseOwner.trim() || !enterpriseDepartment.trim()) {
      setIngestionError(tx('ai.knowledge.ingestion.fieldsRequired'));
      return;
    }
    if (enterpriseSopFile.size > 20_000_000) {
      setIngestionError(tx('ai.knowledge.ingestion.fileTooLarge'));
      return;
    }
    setIngestionSubmitting(true);
    try {
      await importKnowledgeEnterpriseSop(enterpriseSopFile, {
        title: enterpriseTitle.trim(),
        owner: enterpriseOwner.trim(),
        department: enterpriseDepartment.trim(),
      });
      setIngestionMessage(tx('ai.knowledge.message.enterpriseSubmitted'));
      setEnterpriseSopFile(null);
      setEnterpriseTitle('');
      setEnterpriseOwner('');
      setEnterpriseDepartment('');
      await fetchStatsAndDocs();
    } catch (error: any) {
      setIngestionError(error?.message || tx('ai.knowledge.ingestion.enterpriseFailed'));
    } finally {
      setIngestionSubmitting(false);
    }
  };

  const selectedVendorOption = directoryVendorOptions.find((item) => item.value === vendor);

  const getQueueMetadataPreview = (item: FileQueueItem): QueueMetadataPreview => {
    const directoryPath = item.metadata?.directoryPath || item.directoryPath || knowledgeDirectory || tx('ai.knowledge.status.notSpecified');
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
      issue = tx('ai.knowledge.metadata.vendorNotSynced', { vendor: inferredSlug });
    } else if (inferredSlug && getKnowledgeDirectoryVendor(selectedVendor) !== inferredSlug) {
      validation = 'error';
      issue = tx('ai.knowledge.metadata.vendorMismatch', { directoryVendor: inferredSlug, selectedVendor: selectedVendor || tx('ai.knowledge.status.notSelected') });
    } else if (!selectedVendor || !selectedPlatform) {
      validation = 'error';
      issue = tx('ai.knowledge.metadata.vendorPlatformRequired');
    } else if (!inferredSlug) {
      validation = 'warning';
      issue = tx('ai.knowledge.metadata.vendorInferredFallback');
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
        message: tx('ai.knowledge.error.noImportableFiles'),
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
      message: tx('ai.knowledge.message.importStarted', { path: node.path }),
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
        if (!metadataPreview) throw new Error(tx('ai.knowledge.error.metadataExpired'));
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
        failures.push(`${item.fileName}: ${error?.message || tx('ai.knowledge.error.indexFailed')}`);
      }
      setDirectUploadStatus({
        directoryPath: node.path,
        phase: 'uploading',
        completed,
        total: pendingItems.length,
        message: tx('ai.knowledge.message.importProgress', { path: node.path, completed, total: pendingItems.length }),
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
        message: tx('ai.knowledge.message.importFailures', { completed, total: pendingItems.length, failures: failures.join(language === 'zh' ? '；' : '; ') }),
      });
      return;
    }
    setDirectUploadStatus({
      directoryPath: node.path,
      phase: 'success',
      completed,
      total: pendingItems.length,
      message: tx('ai.knowledge.message.imported', { count: completed, path: node.path }),
    });
  };

  const ensureAssetMetadataSelection = () => {
    if (knowledgeDirectory && vendor && platform) return true;
    window.alert(assetOptionsError || tx('ai.knowledge.error.assetsRequired'));
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
        const message = error?.message || tx('ai.knowledge.error.metadataPreview');
        onPreviewError?.(candidate.key, message);
        return null;
      }
    }
    if (previews.length === 0) return null;
    const visibleRows = previews.slice(0, 8).map(({ candidate, preview }) => {
      const normalized = preview.normalized;
      const warning = preview.warnings.length > 0 ? tx('ai.knowledge.metadata.warning', { count: preview.warnings.length }) : '';
      return `${candidate.label}: format=${normalized.format || 'markdown'} / Parser=${normalized.parser_name || 'legacy'} / Vendor=${normalized.vendor || 'UNKNOWN'} / Platform=${normalized.platform || 'UNKNOWN'} / ${tx('ai.knowledge.metadata.status')}=${normalized.metadata_parse_status}${warning}`;
    });
    const remainder = previews.length > visibleRows.length ? `\n${tx('ai.knowledge.metadata.remainder', { count: previews.length - visibleRows.length })}` : '';
    const confirmed = window.confirm(
      `${tx('ai.knowledge.message.previewReady', { count: previews.length })}\n\n${visibleRows.join('\n')}${remainder}\n\n${tx('ai.knowledge.metadata.confirm')}`,
    );
    if (!confirmed) return null;
    return new Map(previews.map(({ candidate, preview }) => [candidate.key, preview]));
  };

  /* ── Batch submit all pending files ── */
  const handleBatchSubmit = async () => {
    if (bundleFiles.length > 0) {
      if (bundleFiles.length !== 1) {
        window.alert(tx('ai.knowledge.error.singleBundle'));
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
        setDocumentActionNotice(tx('ai.knowledge.message.atomicImported', { count: imported }));
        setBundleFiles([]);
        await fetchStatsAndDocs();
      } catch (error: any) {
        setFileQueue((items) => items.map((item) => (
          item.fromZip === bundle.name ? { ...item, status: 'error' as FileQueueStatus, error: error?.message || tx('ai.knowledge.error.atomicImport') } : item
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
        window.alert(tx('ai.knowledge.error.binarySeparate'));
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
          if (!outcome) return { ...item, status: 'error', error: tx('ai.knowledge.error.noTask') };
          return outcome.success
            ? { ...item, status: 'done', error: outcome.status === 'queued' ? tx('ai.knowledge.message.pendingTask') : undefined }
            : { ...item, status: 'error', error: outcome.error?.message || tx('ai.knowledge.error.parseTask') };
        }));
        setBatchProgress({ done: result.data.total, total: result.data.total });
        setDocumentActionNotice(tx('ai.knowledge.message.importBatch', { accepted: result.data.accepted, total: result.data.total }));
      } catch (error: any) {
        setFileQueue((items) => items.map((item) => item.binaryFile && item.status === 'indexing' ? { ...item, status: 'error', error: error?.message || tx('ai.knowledge.error.batchParse') } : item));
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
        return invalid ? { ...item, error: invalid.metadata.issue || tx('ai.knowledge.error.metadataValidation') } : item;
      }));
      window.alert(tx('ai.knowledge.error.metadataMismatch', { count: invalidItems.length }));
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
        if (!metadataPreview) throw new Error(tx('ai.knowledge.error.metadataExpired'));
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
        setFileQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: 'error' as FileQueueStatus, error: err.message || tx('ai.knowledge.error.submit') } : f));
      }

      setBatchProgress({ done: i + 1, total: preparedItems.length });
    }

    setBatchSubmitting(false);
    fetchStatsAndDocs();
  };

  const handleClearSample = async () => {
    if (!window.confirm(tx('ai.knowledge.confirm.clearSample'))) return;
    try {
      await clearSampleKnowledge();
      fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || tx('ai.knowledge.error.clear'));
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
    setIndexingStep(2);

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
      alert(err.message || tx('ai.knowledge.error.createDocument'));
    } finally {
      setSubmitting(false);
    }
  };

  const sourceBadges: Record<string, { label: string; bg: string; color: string; tone: StatusTone }> = {
    official_vendor: { label: tx('ai.knowledge.scope.official.label'), bg: 'bg-accent-subtle ', color: 'text-accent ', tone: 'accent' },
    official_url: { label: tx('ai.knowledge.source.officialUrl'), bg: 'bg-accent-subtle ', color: 'text-accent ', tone: 'accent' },
    official_local: { label: tx('ai.knowledge.source.officialLocal'), bg: 'bg-accent-subtle ', color: 'text-accent ', tone: 'accent' },
    official_template: { label: tx('ai.knowledge.source.officialTemplate'), bg: 'bg-accent-subtle ', color: 'text-accent ', tone: 'accent' },
    internal_sop: { label: tx('ai.knowledge.scope.internalSop.label'), bg: 'bg-success-subtle ', color: 'text-success ', tone: 'success' },
    internal_standard: { label: tx('ai.knowledge.scope.standard.label'), bg: 'bg-accent-subtle ', color: 'text-accent ', tone: 'accent' },
    case: { label: tx('ai.knowledge.source.case'), bg: 'bg-warning-subtle ', color: 'text-warning ', tone: 'warning' },
    user_document: { label: tx('ai.knowledge.source.userDocument'), bg: 'bg-accent-subtle ', color: 'text-accent ', tone: 'accent' },
    sample: { label: tx('ai.knowledge.scope.sample.label'), bg: 'bg-surface-muted ', color: 'text-fg-muted ', tone: 'neutral' },
  };

  const pipelineSteps = [
    tx('ai.knowledge.pipeline.extract'),
    tx('ai.knowledge.pipeline.normalize'),
    tx('ai.knowledge.pipeline.structure'),
    tx('ai.knowledge.pipeline.metadata'),
    tx('ai.knowledge.upload.pipeline.heading'),
    tx('ai.knowledge.pipeline.embedding'),
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
    setSemanticFilters((current) => {
      if (key === 'vendor') {
        return { ...current, vendor: value, productFamily: '', productSeries: '', productModel: '' };
      }
      if (key === 'productFamily') {
        return { ...current, productFamily: value, productSeries: '', productModel: '' };
      }
      if (key === 'productSeries') {
        return { ...current, productSeries: value, productModel: '' };
      }
      return { ...current, [key]: value };
    });
    setCurrentPage(1);
    setSelectedDocIds(new Set());
  };

  const handleDirectorySelect = (node: KnowledgeDirectoryNode) => {
    setKnowledgeDirectory(node.path);
    setSelectedDirectoryPath(node.path);
    setCurrentPage(1);
    setSelectedDocIds(new Set());
  };

  const clearDirectorySelection = () => {
    setSelectedDirectoryPath('');
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
      metadataGovernanceStatus: '',
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
      if (requestId === documentDetailRequestIdRef.current) setDocumentDetailError(err?.message || tx('ai.knowledge.error.documentLoad'));
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
  useEscapeClose(showModal, closeModal);
  useEscapeClose(Boolean(selectedDocument), closeDocument);
  useEscapeClose(Boolean(pendingDocumentAction) && !documentActionBusy, () => setPendingDocumentAction(null));
  useFocusTrap(documentViewerDialogRef, Boolean(selectedDocument), '[data-knowledge-document-close]');
  useFocusTrap(documentActionDialogRef, Boolean(pendingDocumentAction), '[data-knowledge-action-cancel]');
  useFocusTrap(uploadDialogRef, showModal, '[data-knowledge-upload-close]');

  const refreshSelectedDocument = async () => {
    if (!selectedDocument) return;
    await openDocument(selectedDocument);
  };

  const compareSelectedVersions = async (versionId: string) => {
    const targetDocId = selectedDocument?.id || selectedDocument?.document_id;
    if (!targetDocId) return;
    const history = selectedDocument.source_version_history || [];
    const latest = history[0];
    if (!latest || latest.id === versionId) return;
    setVersionAdminBusy(`compare:${versionId}`);
    setVersionAdminNotice('');
    try {
      const comparison = await compareKnowledgeDocumentVersions(targetDocId, versionId, latest.id);
      setVersionCompareResult(comparison);
    } catch (err: any) {
      setVersionAdminNotice(err?.message || tx('ai.knowledge.error.versionCompare'));
    } finally {
      setVersionAdminBusy(null);
    }
  };

  const runVersionAdminAction = async (action: 'publish' | 'supersede' | 'rollback', versionId: string, replacementVersionId?: string) => {
    const targetDocId = selectedDocument?.id || selectedDocument?.document_id;
    if (!targetDocId) return;
    const history = selectedDocument.source_version_history || [];
    const version = history.find((item) => item.id === versionId);
    const label = action === 'publish' ? tx('ai.knowledge.action.publish') : action === 'supersede' ? tx('ai.knowledge.action.supersede') : tx('ai.knowledge.action.rollback');
    if (!version) return;
    if (action === 'supersede' && !replacementVersionId) return;
    const warning = action === 'rollback'
      ? tx('ai.knowledge.version.rollbackConfirm', { version: version.version_no })
      : action === 'supersede'
        ? tx('ai.knowledge.version.supersedeConfirm', { version: version.version_no })
        : tx('ai.knowledge.version.publishConfirm', { version: version.version_no });
    if (!window.confirm(warning)) return;
    setVersionAdminBusy(`${action}:${versionId}`);
    setVersionAdminNotice('');
    try {
      if (action === 'publish') await publishKnowledgeDocumentVersion(targetDocId, versionId);
      if (action === 'supersede') await supersedeKnowledgeDocumentVersion(targetDocId, versionId, replacementVersionId || '');
      if (action === 'rollback') await rollbackKnowledgeDocumentVersion(targetDocId, versionId);
      setVersionAdminNotice(tx('ai.knowledge.version.actionDone', { label }));
      setVersionCompareResult(null);
      await refreshSelectedDocument();
      void fetchStatsAndDocs();
    } catch (err: any) {
      setVersionAdminNotice(err?.message || tx('ai.knowledge.error.action', { label }));
    } finally {
      setVersionAdminBusy(null);
    }
  };

  const versionManagementPanel = selectedDocument?.document_id && (selectedDocument.source_version_history?.length || 0) > 0 ? (() => {
    const history = selectedDocument.source_version_history || [];
    const latest = history[0];
    return (
      <Panel className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-xs font-semibold text-fg ">{tx('ai.knowledge.version.title')}</div>
            <div className="mt-1 text-xs text-fg-muted ">{tx('ai.knowledge.version.body')}</div>
          </div>
          {versionAdminBusy && <Loader2 className="h-4 w-4 animate-spin text-accent" />}
        </div>
        <div className="mt-3 space-y-2">
          {history.map((version) => {
            const status = version.lifecycle_status || version.status || 'draft';
            const isLatest = version.id === latest?.id;
            return (
              <div key={version.id} className="flex flex-wrap items-center gap-2 rounded-xl bg-surface px-3 py-2 text-xs ">
                <span className="font-semibold text-fg ">v{version.version_no}</span>
                <StatusBadge dot tone={status === 'active' || status === 'published' ? 'success' : status === 'quarantined' || status === 'disabled' ? 'danger' : status === 'superseded' ? 'neutral' : 'warning'}>{getKnowledgeLifecycleStatusLabel(status)}</StatusBadge>
                <span className="font-mono text-fg-muted">{version.content_hash ? `${version.content_hash.slice(0, 10)}…` : tx('ai.knowledge.version.hashMissing')}</span>
                <div className="ml-auto flex flex-wrap gap-1">
                  {!isLatest && <button type="button" onClick={() => void compareSelectedVersions(version.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-accent/30 px-2 py-1 font-semibold text-accent hover:bg-accent-subtle disabled:opacity-50 ">{tx('ai.knowledge.action.compareLatest')}</button>}
                  {status !== 'active' && status !== 'published' && <button type="button" onClick={() => void runVersionAdminAction('publish', version.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-success/30 px-2 py-1 font-semibold text-success hover:bg-success-subtle disabled:opacity-50 ">{tx('ai.knowledge.action.publish')}</button>}
                  {!isLatest && (latest?.lifecycle_status === 'published' || latest?.status === 'active') && status !== 'superseded' && <button type="button" onClick={() => void runVersionAdminAction('supersede', version.id, latest.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-warning/30 px-2 py-1 font-semibold text-warning hover:bg-warning-subtle disabled:opacity-50 ">{tx('ai.knowledge.action.supersede')}</button>}
                  {!isLatest && status !== 'quarantined' && status !== 'disabled' && <button type="button" onClick={() => void runVersionAdminAction('rollback', version.id)} disabled={Boolean(versionAdminBusy)} className="rounded-lg border border-danger/30 px-2 py-1 font-semibold text-danger hover:bg-danger-subtle disabled:opacity-50 ">{tx('ai.knowledge.action.rollback')}</button>}
                </div>
              </div>
            );
          })}
        </div>
        {versionAdminNotice && <div className="mt-2 rounded-lg bg-surface px-3 py-2 text-xs text-accent ">{versionAdminNotice}</div>}
        {versionCompareResult && (
          <div className="mt-3 rounded-xl border border-accent/30 bg-surface p-3 text-xs text-fg ">
            <div className="flex items-center justify-between gap-2 font-semibold"><span>v{versionCompareResult.left.version_no} → v{versionCompareResult.right.version_no}</span><button type="button" onClick={() => setVersionCompareResult(null)} className="text-fg-subtle hover:text-fg" aria-label={tx('ai.knowledge.action.closeComparison')}>×</button></div>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4"><span>{tx('ai.knowledge.version.content')}{versionCompareResult.content_changed ? tx('ai.knowledge.version.changed') : tx('ai.knowledge.version.unchanged')}</span><span>Metadata: {versionCompareResult.metadata_changed ? tx('ai.knowledge.version.changed') : tx('ai.knowledge.version.unchanged')}</span><span>{tx('ai.knowledge.version.addedLines')}{versionCompareResult.line_diff.added_lines}</span><span>{tx('ai.knowledge.version.removedLines')}{versionCompareResult.line_diff.removed_lines}</span></div>
            <div className="mt-2 text-fg-muted ">{tx('ai.knowledge.version.changedFields')}{versionCompareResult.changed_fields.join(language === 'zh' ? '、' : ', ') || tx('ai.knowledge.version.none')}</div>
          </div>
        )}
      </Panel>
    );
  })() : null;

  const documentActionLabels: Record<KnowledgeDocumentAction, string> = {
    delete: tx('ai.knowledge.action.delete'),
    disable: tx('ai.knowledge.action.disable'),
    enable: tx('ai.knowledge.action.enable'),
    reparse: tx('ai.knowledge.action.reparse'),
    rechunk: tx('ai.knowledge.action.rechunk'),
    reindex: tx('ai.knowledge.action.reindex'),
  };

  const requestDocumentAction = async (doc: KnowledgeDocument, action: KnowledgeDocumentAction) => {
    setDocumentActionBusy(`${doc.id}:${action}:preview`);
    setDocumentActionNotice('');
    try {
      const preview = await getKnowledgeDocumentActionImpact(doc.id);
      if (!preview.safe_to_confirm) throw new Error(tx('ai.knowledge.error.unsafeDocumentAction'));
      setPendingDocumentAction({ doc, action, preview });
    } catch (err: any) {
      alert(err.message || tx('ai.knowledge.error.impactPreview'));
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
      const suffix = result.job_id ? tx('ai.knowledge.danger.jobQueued', { job: result.job_id }) : '';
      setSelectedDocIds(prev => { const next = new Set(prev); if (action === 'delete') next.delete(doc.id); return next; });
      setDocumentActionNotice(tx('ai.knowledge.danger.submitted', { label, suffix, documents: preview.impact.documents, chunks: preview.impact.chunks, indexes: preview.impact.indexes, references: preview.impact.references }));
      void fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || tx('ai.knowledge.error.action', { label }));
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
      if (!window.confirm(tx('ai.knowledge.danger.batchDeleteConfirm', { documents: impact.documents, chunks: impact.chunks, indexes: impact.indexes, references: impact.references }))) return;
      await batchDeleteKnowledgeDocuments(ids, 'knowledge admin confirmed batch delete');
      setSelectedDocIds(new Set());
      void fetchStatsAndDocs();
    } catch (err: any) {
      alert(err.message || tx('ai.knowledge.error.batchDelete'));
    } finally {
      setDeleting(false);
    }
  };

  const getDocumentStatusLabel = (document: KnowledgeDocument): string => {
    if (document.metadata_governance_status === 'pending_review') {
      return `${tx('ai.knowledge.governance.pending')}${tx('ai.knowledge.table.excludedRag')}`;
    }
    if (document.status === 'active' && !document.exclude_from_rag) return tx('ai.knowledge.status.ready');
    const translatedStatus = getKnowledgeLifecycleStatusLabel(document.status);
    return `${translatedStatus}${document.exclude_from_rag ? tx('ai.knowledge.table.excludedRag') : ''}`;
  };

  return (
    <div className="w-full space-y-3 pb-8 font-sans">
      <KnowledgeAdminNavigation activeView={knowledgeAdminView} onChange={setKnowledgeAdminView} />
      {knowledgeAdminView === 'sources' ? <SourceRegistryPanel /> : knowledgeAdminView === 'uat' ? <UATSignoffPanel /> : knowledgeAdminView === 'evaluation' ? <RagEvaluationPanel /> : knowledgeAdminView === 'traces' ? <RetrievalTracePanel /> : <React.Fragment>
      <input
        ref={quickUploadInputRef}
        type="file"
        multiple
        accept={ALL_SUPPORTED_EXTENSIONS.join(',')}
        onChange={handleQuickUploadInputChange}
        className="hidden"
        aria-hidden="true"
      />
      {/* Header: title, one line, template downloads and the primary upload action */}
      <PageHeader
        title={<span className="inline-flex items-center gap-2"><BookOpen className="h-5 w-5 text-accent" aria-hidden="true" />{tx('ai.knowledge.header.title')}</span>}
        description={tx('ai.knowledge.header.description')}
        info={tx('ai.knowledge.header.tip')}
        infoLabel={tx('ai.knowledge.header.title')}
        actions={(
          <>
            <a href="/downloads/nexora-knowledge-document-template.md" download="nexora-knowledge-document-template.md" className="inline-flex items-center gap-1 rounded-lg border border-accent/30 bg-accent-subtle px-2 py-1 font-semibold text-accent hover:bg-accent-subtle "><FileText className="h-3 w-3" />{tx('ai.knowledge.header.markdownTemplate')}</a>
            <a href="/downloads/nexora-knowledge-document-template.json" download="nexora-knowledge-document-template.json" className="inline-flex items-center gap-1 rounded-lg border border-accent/30 bg-accent-subtle px-2 py-1 font-semibold text-accent hover:bg-accent-subtle "><FileCode className="h-3 w-3" />{tx('ai.knowledge.header.jsonTemplate')}</a>
            <a href="/downloads/nexora-knowledge-import-format.md" download="nexora-knowledge-import-format.md" className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2 py-1 font-semibold text-fg-muted hover:bg-surface-muted "><HelpCircle className="h-3 w-3" />{tx('ai.knowledge.header.formatGuide')}</a>
          <button type="button" onClick={() => { setShowModal(true); setInputMode('upload'); setIngestionError(''); }} className="hidden items-center gap-2 rounded-xl bg-accent px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-accent-hover sm:inline-flex">
            <UploadCloud className="h-3.5 w-3.5" />{tx('ai.knowledge.header.upload')}
          </button>
          </>
        )}
      />

      <details
        className="rounded-xl border border-line bg-surface px-3 py-2 shadow-xs "
        open={operationsOpen}
        onToggle={(event) => setOperationsOpen(event.currentTarget.open)}
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg py-1 [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-center gap-2">
            <UploadCloud className="h-4 w-4 shrink-0 text-accent" />
            <span className="min-w-0">
              <span className="block text-xs font-bold text-fg ">{tx('ai.knowledge.ingestion.groupTitle')}</span>
              <span className="mt-0.5 block truncate text-xs text-fg-muted ">{tx('ai.knowledge.ingestion.groupBody')}</span>
            </span>
          </span>
          <span className="shrink-0 text-xs font-semibold text-accent ">{operationsOpen ? tx('ai.knowledge.ingestion.groupCollapse') : tx('ai.knowledge.ingestion.groupExpand')}</span>
        </summary>
        <div className="mt-3 space-y-3 border-t border-line pt-3 ">
          <section className="rounded-xl border border-line bg-surface-muted p-3 " aria-label={tx('ai.knowledge.ingestion.aria')}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-fg ">{tx('ai.knowledge.ingestion.title')}</h3>
                <p className="mt-1 text-xs text-fg-muted ">{tx('ai.knowledge.ingestion.body')}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => { setIngestionMode('enterprise_sop'); setIngestionError(''); setIngestionMessage(''); }} className={`rounded-xl px-3 py-2 text-xs font-semibold transition ${ingestionMode === 'enterprise_sop' ? 'bg-success text-white' : 'border border-success/30 bg-success-subtle text-success hover:bg-success-subtle '}`}>
                  <span className="mr-1.5">📄</span>{tx('ai.knowledge.ingestion.enterprise')}
                </button>
                {ingestionMode && <button type="button" onClick={closeIngestionPanel} disabled={ingestionSubmitting} className="rounded-xl px-2.5 py-2 text-xs text-fg-subtle hover:bg-surface-muted " aria-label={tx('ai.knowledge.ingestion.close')}><X className="h-3.5 w-3.5" /></button>}
              </div>
            </div>
            {ingestionMode === 'enterprise_sop' && (
              <form onSubmit={handleEnterpriseSopImport} className="mt-4 grid gap-3 border-t border-success/30 pt-4 md:grid-cols-2 xl:grid-cols-4">
                <label className="text-[11px] text-fg-muted md:col-span-2">{tx('ai.knowledge.ingestion.file')}<input type="file" accept=".md,.markdown,.txt,.log,.html,.htm,.docx,.pdf,.json,.yaml,.yml,.csv,.xml,.conf,.cfg,.ini" onChange={(event) => setEnterpriseSopFile(event.target.files?.[0] || null)} className="mt-1 block w-full rounded-xl border border-line bg-surface px-3 py-2 text-xs " required /></label>
                <label className="text-[11px] text-fg-muted ">{tx('ai.knowledge.ingestion.titleField')}<input value={enterpriseTitle} onChange={(event) => setEnterpriseTitle(event.target.value)} placeholder={tx('ai.knowledge.ingestion.titlePlaceholder')} className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2 text-xs " required /></label>
                <label className="text-[11px] text-fg-muted ">{tx('ai.knowledge.ingestion.owner')}<input value={enterpriseOwner} onChange={(event) => setEnterpriseOwner(event.target.value)} placeholder={tx('ai.knowledge.ingestion.ownerPlaceholder')} className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2 text-xs " required /></label>
                <label className="text-[11px] text-fg-muted ">{tx('ai.knowledge.ingestion.department')}<input value={enterpriseDepartment} onChange={(event) => setEnterpriseDepartment(event.target.value)} placeholder={tx('ai.knowledge.ingestion.departmentPlaceholder')} className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2 text-xs " required /></label>
                <div className="flex items-end gap-2"><span className="flex-1 rounded-xl bg-success-subtle px-3 py-2 text-xs text-success ">{tx('ai.knowledge.ingestion.internalFixed')}</span><button type="submit" disabled={ingestionSubmitting} className="rounded-xl bg-success px-3 py-2 text-xs font-semibold text-white hover:bg-success disabled:opacity-50">{ingestionSubmitting ? tx('ai.knowledge.ingestion.submitting') : tx('ai.knowledge.ingestion.submitEnterprise')}</button></div>
              </form>
            )}
            {(ingestionError || ingestionMessage) && <div className={`mt-3 rounded-xl px-3 py-2 text-[11px] ${ingestionError ? 'bg-danger-subtle text-danger ' : 'bg-success-subtle text-success '}`}>{ingestionError || ingestionMessage}</div>}
          </section>
          {operationsOpen && <OfficialSeedPanel language={language} onCompleted={() => void fetchStatsAndDocs()} />}
          {operationsOpen && <IngestionJobsPanel />}
        </div>
      </details>

      <SummaryBar
        label={tx('ai.knowledge.header.title')}
        items={[
          { key: 'documents', value: stats.total_documents, label: <span title={tx('ai.knowledge.stat.documentsHelp')}>{tx('ai.knowledge.stat.documents')}</span> },
          { key: 'chunks', value: stats.total_chunks, label: <span title={tx('ai.knowledge.stat.chunksHelp')}>{tx('ai.knowledge.stat.chunks')}</span> },
          { key: 'vendors', value: stats.total_vendors || 0, label: <span title="Cisco / Huawei / H3C / Ruijie / Juniper / Fortinet / Aruba">{tx('ai.knowledge.stat.vendors')}</span> },
          { key: 'indexes', value: stats.ready_indexes, tone: stats.ready_indexes ? 'success' : 'warning', label: <span title={tx('ai.knowledge.stat.indexHelp')}>{tx('ai.knowledge.stat.index')}</span> },
        ]}
      />

      {/* Semantic Embedding Engine Status & Reindex Bar */}
      {(() => {
        const activeModel = embeddingStatus?.configured_embedding_models?.find((item) => item.enabled);
        const semanticReady = Boolean(embeddingStatus?.available || activeModel);
        const semanticChunks = embeddingStatus?.chunk_stats?.semantic_v2_chunks ?? 0;
        const totalChunks = embeddingStatus?.chunk_stats?.total_chunks ?? stats.total_chunks ?? 0;
        return (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface px-3.5 py-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-accent" />
              <span className="font-semibold text-fg">{language === 'zh' ? '语义向量引擎 (Embedding)' : 'Semantic Embedding Engine'}</span>
              <StatusBadge tone={semanticReady ? 'success' : 'warning'}>
                {semanticReady
                  ? (activeModel ? `${activeModel.provider_name} · ${activeModel.model_code}` : (embeddingStatus?.model || 'bge-m3'))
                  : (language === 'zh' ? '本地特征向量（待配置语义模型）' : 'Local fallback (no semantic model)')}
              </StatusBadge>
              <span className="text-[11px] text-fg-subtle">
                {language === 'zh'
                  ? `语义向量切片：${semanticChunks} / ${totalChunks}`
                  : `Semantic chunks: ${semanticChunks} / ${totalChunks}`}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <a
                href="/ai/models"
                className="rounded-lg border border-line bg-surface-muted px-2.5 py-1 text-xs font-medium text-fg transition hover:border-accent hover:text-accent"
              >
                {language === 'zh' ? '配置 Embedding 模型' : 'Configure Embedding'}
              </a>
              {!permissionDenied && (
                <button
                  type="button"
                  disabled={rebuildingEmbeddings}
                  onClick={() => void handleRebuildEmbeddings()}
                  className="rounded-lg border border-accent/30 bg-accent-subtle px-2.5 py-1 text-xs font-semibold text-accent transition hover:bg-accent hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {rebuildingEmbeddings
                    ? (language === 'zh' ? '重建中...' : 'Rebuilding...')
                    : (language === 'zh' ? '全量重建向量索引' : 'Rebuild Embeddings')}
                </button>
              )}
            </div>
          </div>
        );
      })()}

      {/* Full-Width Document Management Section */}
      <div className="w-full space-y-3">
        <div className="flex flex-wrap items-center gap-2" aria-label={tx('ai.knowledge.filter.scopeAria')}>
          <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-fg-muted ">{tx('ai.knowledge.filter.scopeAria')}</span>
            {([
              ['all', 'ai.knowledge.filter.scopeAll', 'ai.knowledge.filter.scopeAllBody', 'bg-surface-muted border-line text-fg '],
              ['official', 'ai.knowledge.filter.scopeOfficial', 'ai.knowledge.filter.scopeOfficialBody', 'bg-accent-subtle border-accent/30 text-accent '],
              ['enterprise', 'ai.knowledge.filter.scopeEnterprise', 'ai.knowledge.filter.scopeEnterpriseBody', 'bg-success-subtle border-success/30 text-success '],
            ] as const).map(([scope, titleKey, descriptionKey, tone]) => (
              <button
                key={scope}
                type="button"
                onClick={() => handleKnowledgeScopeChange(scope)}
                className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition hover:border-accent/30 hover:shadow-sm ${tone} ${knowledgeScope === scope ? 'ring-2 ring-accent ring-offset-1 dark:ring-offset-gray-900' : ''}`}
                aria-pressed={knowledgeScope === scope}
                title={tx(descriptionKey)}
              >
                <span>{tx(titleKey)}</span>
                {knowledgeScope === scope && <CheckCircle2 className="h-3.5 w-3.5 text-accent" />}
              </button>
            ))}
        </div>
        <div className="grid items-start gap-4 lg:grid-cols-[272px_minmax(0,1fr)]" aria-label={tx('ai.knowledge.directory.sectionAria')}>
          <Panel className="min-w-0 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-xs font-bold uppercase tracking-wide text-fg-muted">{tx('ai.knowledge.directory.sectionTitle')}</h3>
              <StatusBadge tone="accent">{flattenDirectoryNodes(directoryTree).length}</StatusBadge>
            </div>
            <button
              type="button"
              onClick={clearDirectorySelection}
              className={`mb-2 flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-xs transition ${!selectedDirectoryPath ? 'border-accent bg-accent font-semibold text-white shadow-sm' : 'border-accent/30 bg-surface text-accent hover:border-accent '}`}
              aria-pressed={!selectedDirectoryPath}
            >
              <Database className="h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{tx('ai.knowledge.directory.all')}</span>
              <span className="text-xs opacity-75">{allDirectoryDocuments}</span>
            </button>
            <DirectoryTreePicker
              nodes={directoryTree}
              selectedPath={selectedDirectoryPath}
              loading={directoryTreeLoading}
              error={directoryTreeError}
              disabled={permissionDenied}
              canManage={canManageDirectories}
              inline
              title={tx('ai.knowledge.directory.treeAria')}
              onUpload={handleDirectoryUpload}
              onSelect={handleDirectorySelect}
              onCreate={handleCreateDirectory}
              onRename={handleRenameDirectory}
              onDelete={handleDeleteDirectory}
            />
          </Panel>
          {/* Search, classification, and document list share one main column. */}
          <div className="min-w-0 space-y-3">
          <div ref={filtersSectionRef} className="min-w-0 scroll-mt-4">
          <Panel className="p-3" aria-label={tx('ai.knowledge.directory.manageFilters')}>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-fg">{selectedDirectoryPath || tx('ai.knowledge.directory.all')}</h3>
              <StatusBadge tone="accent">{tx('ai.knowledge.directory.documentCount', { count: totalDocuments })}</StatusBadge>
              {!selectedDirectoryPath && <span className="text-xs text-fg-muted">{tx('ai.knowledge.directory.selectHintTitle')}</span>}
              {selectedDirectoryPath && (
                <button type="button" onClick={clearDirectorySelection} className="rounded-full border border-line bg-surface px-2 py-0.5 text-[11px] font-medium text-fg-muted hover:bg-surface-muted">
                  {tx('ai.knowledge.directory.clearShortcut')}
                </button>
              )}
            </div>
            {activeFilterChips.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {activeFilterChips.slice(0, 4).map((filter, index) => (
                  <span key={`${filter}-${index}`} className="max-w-[180px] truncate rounded-full bg-accent-subtle px-2 py-0.5 text-[11px] text-accent">{filter}</span>
                ))}
              </div>
            )}
          </div>
          <div className="flex items-end justify-between gap-4">
            <div className="relative flex-1 max-w-md">
              <label htmlFor="knowledge-full-text-search" className="mb-1 block text-xs font-semibold uppercase tracking-wide text-fg-muted ">{tx('ai.knowledge.search.label')}</label>
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-fg-subtle" />
                <input
                  id="knowledge-full-text-search"
                  type="search"
                  placeholder={tx('ai.knowledge.search.placeholder')}
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 text-xs bg-surface-muted border border-line rounded-xl focus:outline-none focus:border-accent "
                />
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => void handleKnowledgeExport()}
                disabled={exporting || loading || permissionDenied || totalDocuments === 0}
                className="inline-flex items-center gap-1.5 rounded-xl border border-accent/30 bg-accent-subtle px-3 py-1.5 text-xs font-semibold text-accent shadow-xs transition hover:bg-accent-subtle disabled:cursor-not-allowed disabled:opacity-50 "
                title={tx('ai.knowledge.action.export')}
              >
                {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PackageOpen className="h-3.5 w-3.5" />}
                {exporting ? tx('ai.knowledge.action.exporting') : tx('ai.knowledge.action.export')}
              </button>
              {selectedDocIds.size > 0 && (
                <ActionButton icon={Trash2} variant="danger" size="sm" onClick={handleBatchDelete} disabled={deleting}>
                  {deleting ? tx('ai.knowledge.action.deleting') : tx('ai.knowledge.action.batchDelete', { count: selectedDocIds.size })}
                </ActionButton>
              )}
              <div className="text-xs text-fg-muted ">
                {tx('ai.knowledge.search.total', { count: totalDocuments })}
              </div>
            </div>
          </div>
          {documentActionNotice && (
            <div className="mt-3 rounded-xl border border-success/30 bg-success-subtle px-3 py-2 text-xs text-success " role="status">
              {documentActionNotice}
            </div>
          )}

          <div className="mt-2.5 border-t border-line pt-2.5" aria-label={tx('ai.knowledge.product.title')}>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-fg-muted">{tx('ai.knowledge.product.title')}</span>
                <span className="text-[11px] text-fg-subtle">
                  {language === 'zh' ? '先选厂商，再逐层下拉检索产品族、系列与型号' : 'Select vendor first, then drill down by family, series, and model'}
                </span>
                {selectedClassification && <StatusBadge tone="accent">{tx('ai.knowledge.product.selected', { value: selectedClassification })}</StatusBadge>}
              </div>
              {(selectedClassification || semanticFilters.productModel) && (
                <button
                  type="button"
                  onClick={() => setSemanticFilter('vendor', '')}
                  className="text-xs font-semibold text-accent hover:text-fg"
                >
                  {tx('ai.knowledge.product.clear')}
                </button>
              )}
            </div>
            {unknownFacetCount > 0 && (
              <div className="mb-2.5 flex items-start justify-between gap-3 rounded-xl border border-warning/30 bg-warning-subtle px-3 py-2 text-xs leading-4 text-warning " role="status">
                <div className="flex min-w-0 items-start gap-2">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{tx('ai.knowledge.product.unknown', { count: unknownFacetCount })}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setSemanticFilter('metadataGovernanceStatus', semanticFilters.metadataGovernanceStatus === 'pending_review' ? '' : 'pending_review')}
                  className="shrink-0 font-semibold text-warning underline underline-offset-2 hover:text-warning "
                >
                  {semanticFilters.metadataGovernanceStatus === 'pending_review' ? tx('ai.knowledge.governance.showAll') : tx('ai.knowledge.governance.viewPending')}
                </button>
              </div>
            )}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <SearchableFacetSelect
                label={tx('ai.knowledge.product.vendor')}
                placeholder={language === 'zh' ? '1. 选择厂商...' : '1. Select vendor...'}
                disabledPlaceholder={language === 'zh' ? '1. 选择厂商...' : '1. Select vendor...'}
                searchPlaceholder={language === 'zh' ? '搜索厂商...' : 'Search vendor...'}
                allLabel={language === 'zh' ? '全部厂商' : 'All vendors'}
                emptyLabel={tx('ai.knowledge.product.empty')}
                value={semanticFilters.vendor}
                options={documentFacets.vendors}
                onChange={(next) => setSemanticFilter('vendor', next)}
              />
              <SearchableFacetSelect
                label={tx('ai.knowledge.product.family')}
                placeholder={language === 'zh' ? '2. 选择产品族...' : '2. Select family...'}
                disabledPlaceholder={language === 'zh' ? '2. 请先选择厂商' : '2. Select vendor first'}
                searchPlaceholder={language === 'zh' ? '搜索产品族...' : 'Search family...'}
                allLabel={language === 'zh' ? '全部产品族' : 'All families'}
                emptyLabel={tx('ai.knowledge.product.empty')}
                value={semanticFilters.productFamily}
                options={documentFacets.families}
                disabled={!semanticFilters.vendor}
                onChange={(next) => setSemanticFilter('productFamily', next)}
              />
              <SearchableFacetSelect
                label={tx('ai.knowledge.product.series')}
                placeholder={language === 'zh' ? '3. 选择系列...' : '3. Select series...'}
                disabledPlaceholder={language === 'zh' ? '3. 请先选择产品族' : '3. Select family first'}
                searchPlaceholder={language === 'zh' ? '搜索系列...' : 'Search series...'}
                allLabel={language === 'zh' ? '全部系列' : 'All series'}
                emptyLabel={tx('ai.knowledge.product.empty')}
                value={semanticFilters.productSeries}
                options={documentFacets.series}
                disabled={!semanticFilters.productFamily}
                onChange={(next) => setSemanticFilter('productSeries', next)}
              />
              <input
                type="search"
                value={semanticFilters.productModel}
                onChange={(event) => setSemanticFilter('productModel', event.target.value)}
                placeholder={language === 'zh' ? '4. 搜索具体型号...' : '4. Search model...'}
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-xs text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none"
                aria-label={tx('ai.knowledge.filter.modelLabel')}
              />
            </div>
          </div>

          <details className="mt-2.5 border-t border-line pt-2.5" open={advancedFiltersOpen} onToggle={(event) => setAdvancedFiltersOpen(event.currentTarget.open)} aria-label={tx('ai.knowledge.filter.semantic')}>
            <summary className="flex cursor-pointer list-none items-start justify-between gap-2 rounded-lg [&::-webkit-details-marker]:hidden">
              <div>
                <span className="text-[11px] font-semibold text-fg-muted ">{tx('ai.knowledge.filter.semantic')}</span>
                <p className="mt-1 text-xs text-fg-muted ">{tx('ai.knowledge.filter.semanticBody')}</p>
              </div>
              <span className="shrink-0 text-xs font-semibold text-accent ">{advancedFiltersOpen ? tx('ai.knowledge.filter.collapse') : tx('ai.knowledge.filter.expand')}</span>
            </summary>
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={(event) => { event.preventDefault(); clearSemanticFilters(); }}
                disabled={!Object.entries(semanticFilters).some(([key, value]) => key === 'status' ? value !== 'active' : Boolean(value))}
                className="text-xs font-medium text-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-40 "
              >
                {tx('ai.knowledge.action.clearFilters')}
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <select
                value={selectedFolder}
                onChange={(event) => handleFolderChange(event.target.value)}
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-[11px] text-fg "
                aria-label={tx('ai.knowledge.filter.sourceLabel')}
              >
                {folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
              </select>
              <input type="search"
                value={semanticFilters.osFamily}
                onChange={(event) => setSemanticFilter('osFamily', event.target.value)}
                placeholder="OS Family"
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-[11px] text-fg placeholder:text-fg-subtle "
                aria-label={tx('ai.knowledge.filter.osLabel')}
              />
              <input type="search"
                value={semanticFilters.softwareRelease}
                onChange={(event) => setSemanticFilter('softwareRelease', event.target.value)}
                placeholder={tx('ai.knowledge.filter.versionPlaceholder')}
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-[11px] text-fg placeholder:text-fg-subtle "
                aria-label={tx('ai.knowledge.filter.versionLabel')}
              />
              <input type="search"
                value={semanticFilters.featureDomain}
                onChange={(event) => setSemanticFilter('featureDomain', event.target.value)}
                placeholder={tx('ai.knowledge.filter.featurePlaceholder')}
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-[11px] text-fg placeholder:text-fg-subtle "
                aria-label={tx('ai.knowledge.filter.featureLabel')}
              />
              <select
                value={semanticFilters.documentCategory}
                onChange={(event) => setSemanticFilter('documentCategory', event.target.value)}
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-[11px] text-fg "
                aria-label={tx('ai.knowledge.filter.typeLabel')}
              >
                <option value="">{tx('ai.knowledge.filter.allDocumentTypes')}</option>
                {KNOWLEDGE_DIRECTORY_OPTIONS.map((item) => <option key={item.id} value={item.id}>{tx(item.labelKey)}</option>)}
              </select>
              <select
                value={semanticFilters.status}
                onChange={(event) => setSemanticFilter('status', event.target.value)}
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-[11px] text-fg "
                aria-label={tx('ai.knowledge.filter.lifecycleLabel')}
              >
                <option value="active">{tx('ai.knowledge.status.active')}</option>
                <option value="all">{tx('ai.knowledge.status.all')}</option>
                <option value="published">{tx('ai.knowledge.status.published')}</option>
                <option value="draft">{tx('ai.knowledge.status.draft')}</option>
                <option value="quarantined">{tx('ai.knowledge.status.quarantined')}</option>
                <option value="disabled">{tx('ai.knowledge.status.disabled')}</option>
              </select>
              <select
                value={semanticFilters.metadataGovernanceStatus}
                onChange={(event) => setSemanticFilter('metadataGovernanceStatus', event.target.value)}
                className="rounded-xl border border-line bg-surface-muted px-2.5 py-2 text-[11px] text-fg "
                aria-label={tx('ai.knowledge.governance.filterLabel')}
              >
                <option value="">{tx('ai.knowledge.governance.filterAll')}</option>
                <option value="ready">{tx('ai.knowledge.governance.ready')}</option>
                <option value="pending_review">{tx('ai.knowledge.governance.pending')}</option>
              </select>
            </div>
          </details>

          </Panel>
          </div>

          {/* Table Container */}
          <div ref={documentTableRef}>
          <Panel as="div" className="overflow-hidden" aria-label={copy.documentsAria}>
            {loading && documents.length === 0 ? (
              <div className="p-8 text-center text-xs text-fg-subtle">{tx('ai.common.loading')}</div>
            ) : loadError ? (
              <EmptyState
                className="rounded-none border-0"
                icon={XCircle}
                title={permissionDenied ? tx('ai.knowledge.empty.permission') : tx('ai.knowledge.empty.load')}
                description={loadError}
                action={!permissionDenied ? <button type="button" onClick={() => void fetchStatsAndDocs()} className="rounded-lg bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-accent-hover">{tx('ai.common.retry')}</button> : undefined}
              />
            ) : documents.length === 0 ? (
              <EmptyState
                className="rounded-none border-0"
                icon={BookOpen}
                title={tx('ai.knowledge.empty.filtered')}
                description={tx('ai.knowledge.empty.body')}
              />
            ) : (
              <div className={`overflow-x-auto transition-opacity ${loading ? 'opacity-60 pointer-events-none' : ''}`}>
                <DataTable unstyled exportConfig={{ filename: 'knowledge-documents', language: language === 'zh' ? 'zh' : 'en', disabled: loading || permissionDenied || totalDocuments === 0, exportData: exportKnowledgeTable }} className="nx-data-table w-full text-left">
                <thead className="sticky top-0 z-10 bg-surface-muted shadow-sm text-fg-muted font-semibold">
                  <tr>
                    <th className="px-2.5 py-2.5 w-9">
                      <input
                        type="checkbox"
                        checked={documents.length > 0 && documents.every((doc) => selectedDocIds.has(doc.id))}
                        onChange={toggleSelectAll}
                        className="w-3.5 h-3.5 rounded border-line-strong text-accent focus:ring-accent cursor-pointer"
                        title={tx('ai.knowledge.table.selectAll')}
                      />
                    </th>
                    <th className="px-3 py-2.5">{tx('ai.knowledge.table.name')}</th>
                    <th className="px-3 py-2.5 whitespace-nowrap">{tx('ai.knowledge.table.source')}</th>
                    <th className="px-3 py-2.5 whitespace-nowrap">{tx('ai.knowledge.table.category')}</th>
                    <th className="px-3 py-2.5 whitespace-nowrap">{tx('ai.knowledge.table.index')}</th>
                    <th className="px-3 py-2.5 whitespace-nowrap">{tx('ai.knowledge.table.created')}</th>
                    <TableActionHeader className="px-3 py-2.5 text-right">{tx('ai.knowledge.table.actions')}</TableActionHeader>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line bg-surface ">
                  {documents.map((doc) => {
                    const badge = sourceBadges[doc.knowledge_source_type] || sourceBadges.user_document;
                    const isSelected = selectedDocIds.has(doc.id);
                    const metaSubtitle = [
                      doc.vendor ? getVendorDisplayLabel(doc.vendor, language) : '',
                      doc.product_model || doc.product_family || '',
                      getPlatformDisplayLabel(doc.vendor, doc.platform, language),
                      doc.software_release || doc.os_family || '',
                    ].filter((v) => v && v !== '—').join(' · ');
                    return (
                      <tr key={doc.id} className={`hover:bg-surface-muted transition ${isSelected ? 'bg-accent-subtle ' : ''}`}>
                        <td className="px-2.5 py-2.5 align-top">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleDocSelection(doc.id)}
                            className="mt-1 w-3.5 h-3.5 rounded border-line-strong text-accent focus:ring-accent cursor-pointer"
                          />
                        </td>
                        <td className="px-3 py-2.5 align-top">
                          <div className="max-w-[340px]">
                            <button
                              type="button"
                              onClick={() => void openDocument(doc)}
                              className="group flex max-w-full items-center gap-2 text-left transition hover:text-accent"
                              title={tx('ai.knowledge.action.viewDocument')}
                            >
                              <FileCode className="w-4 h-4 flex-shrink-0 text-accent" />
                              <span className="min-w-0">
                                <span className="block truncate font-semibold text-fg underline-offset-4 group-hover:text-accent group-hover:underline">{doc.name}</span>
                              </span>
                              <Eye className="h-3.5 w-3.5 flex-shrink-0 text-fg-subtle opacity-0 transition group-hover:text-accent group-hover:opacity-100" />
                            </button>
                            {metaSubtitle && (
                              <div className="mt-0.5 pl-6 truncate font-mono text-[11px] font-normal text-fg-muted">{metaSubtitle}</div>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-2.5 align-top whitespace-nowrap">
                          <StatusBadge tone={badge.tone}>
                            {badge.label}
                          </StatusBadge>
                        </td>
                        <td className="px-3 py-2.5 align-top whitespace-nowrap text-xs text-fg-muted">{doc.document_category || '—'}</td>
                        <td className="px-3 py-2.5 align-top whitespace-nowrap">
                          <div className="flex flex-col items-start gap-1">
                            <StatusBadge tone={doc.status === 'active' && !doc.exclude_from_rag ? 'success' : 'warning'}>
                              {doc.status === 'active' && !doc.exclude_from_rag ? <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" /> : <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />}
                              {getDocumentStatusLabel(doc)}
                            </StatusBadge>
                            <span className="font-mono text-[11px] text-fg-muted">
                              {tx('ai.knowledge.table.chunkCount', { count: doc.chunk_count || 1 })}
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-2.5 align-top whitespace-nowrap text-fg-subtle font-mono text-[11px]">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </td>
                        <TableActionCell className="px-3 py-2.5 align-top text-right">
                          <div className="flex items-center justify-end gap-0.5">
                            <ActionIconButton
                              icon={doc.status === 'disabled' ? CheckCircle2 : Archive}
                              label={doc.status === 'disabled' ? tx('ai.knowledge.action.enable') : tx('ai.knowledge.action.disable')}
                              tooltip={doc.status === 'disabled' ? tx('ai.knowledge.action.enableIndependent') : tx('ai.knowledge.action.disableIndependent')}
                              variant={doc.status === 'disabled' ? 'success' : 'danger'}
                              disabled={Boolean(documentActionBusy)}
                              onClick={() => void requestDocumentAction(doc, doc.status === 'disabled' ? 'enable' : 'disable')}
                            />
                            <ActionIconButton
                              icon={FileText}
                              label={tx('ai.knowledge.action.reparse')}
                              tooltip={tx('ai.knowledge.action.reparseIndependent')}
                              variant="accent"
                              disabled={Boolean(documentActionBusy)}
                              onClick={() => void requestDocumentAction(doc, 'reparse')}
                            />
                            <ActionIconButton
                              icon={Layers}
                              label={tx('ai.knowledge.action.rechunk')}
                              tooltip={tx('ai.knowledge.action.rechunkIndependent')}
                              variant="accent"
                              disabled={Boolean(documentActionBusy)}
                              onClick={() => void requestDocumentAction(doc, 'rechunk')}
                            />
                            <ActionIconButton
                              icon={RefreshCw}
                              label={tx('ai.knowledge.action.reindex')}
                              tooltip={tx('ai.knowledge.action.reindexIndependent')}
                              variant="accent"
                              disabled={Boolean(documentActionBusy)}
                              onClick={() => void requestDocumentAction(doc, 'reindex')}
                            />
                            <ActionIconButton
                              icon={Trash2}
                              label={tx('ai.knowledge.action.deleteIndependent')}
                              size="sm"
                              variant="danger"
                              onClick={() => void requestDocumentAction(doc, 'delete')}
                              disabled={Boolean(documentActionBusy)}
                            />
                          </div>
                        </TableActionCell>
                      </tr>
                    );
                  })}
                </tbody>
                </DataTable>
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
                language={language}
              />
            )}
          </Panel>
          </div>
          </div>
        </div>
      </div>

      {/* Document Content Viewer */}
      {selectedDocument && (
        <div
          ref={documentViewerDialogRef}
          className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-[2px]"
          role="dialog"
          aria-modal="true"
          aria-labelledby="knowledge-document-title"
          tabIndex={-1}
          onClick={closeDocument}
        >
          <aside
            className="ml-auto flex h-full w-full max-w-3xl flex-col border-l border-line bg-surface shadow-2xl shadow-slate-950/20 "
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-5 sm:px-7">
              <div className="min-w-0">
                <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-accent">
                  <BookOpen className="h-3.5 w-3.5" />
                  {tx('ai.knowledge.viewer.title')}
                </div>
                <h2 id="knowledge-document-title" className="truncate text-xl font-bold tracking-tight text-fg ">{selectedDocument.name}</h2>
                <p className="mt-1 truncate font-mono text-[11px] text-fg-subtle" title={selectedDocument.id}>{selectedDocument.id}</p>
              </div>
              <button type="button" data-knowledge-document-close aria-label={tx('ai.knowledge.action.closeViewer')} title={tx('ai.knowledge.action.closeViewer')} onClick={closeDocument} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-subtle transition hover:bg-surface-muted hover:text-fg ">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-4 sm:px-7">
              {(() => {
                const badge = sourceBadges[selectedDocument.knowledge_source_type] || sourceBadges.user_document;
                return <StatusBadge tone={badge.tone}>{badge.label}</StatusBadge>;
              })()}
              <StatusBadge>{getVendorDisplayLabel(selectedDocument.vendor, language)} / {getPlatformDisplayLabel(selectedDocument.vendor, selectedDocument.platform, language)}</StatusBadge>
              <StatusBadge tone={selectedDocument.status === 'active' ? 'success' : 'warning'}><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />{selectedDocument.status === 'active' ? tx('ai.knowledge.viewer.ready') : getKnowledgeLifecycleStatusLabel(selectedDocument.status)}</StatusBadge>
              <StatusBadge><Layers className="h-3.5 w-3.5" aria-hidden="true" />{tx('ai.knowledge.viewer.chunkCount', { count: selectedDocument.chunk_count })}</StatusBadge>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
              {documentDetailLoading ? (
                <div className="space-y-4" aria-label={tx('ai.knowledge.viewer.actionLoading')}>
                  {[0, 1, 2].map((item) => <div key={item} className="animate-pulse rounded-2xl border border-line p-4 "><div className="h-4 w-1/3 rounded bg-surface-muted " /><div className="mt-4 h-20 rounded-xl bg-surface-muted " /></div>)}
                </div>
              ) : documentDetailError ? (
                <div className="rounded-2xl border border-danger/30 bg-danger-subtle p-5 text-sm text-danger ">
                  <div className="flex items-start gap-3"><XCircle className="mt-0.5 h-5 w-5 shrink-0" /><div><p className="font-semibold">{tx('ai.knowledge.error.documentLoad')}</p><p className="mt-1 text-xs leading-5 opacity-80">{documentDetailError}</p><button type="button" onClick={() => void openDocument(selectedDocument)} className="mt-3 rounded-lg bg-surface px-3 py-1.5 text-xs font-semibold ">{tx('ai.knowledge.viewer.retry')}</button></div></div>
                </div>
              ) : selectedDocument.chunks.length === 0 ? (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <section className="rounded-2xl border border-line bg-surface-muted p-4 ">
                      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-fg-subtle">{tx('ai.knowledge.viewer.rawSource')}</div>
                      <div className="mt-2 text-xs font-medium text-fg ">{selectedDocument.raw_source?.source || selectedDocument.source || tx('ai.knowledge.viewer.sourceNotRecorded')}</div>
                    </section>
                    <section className="rounded-2xl border border-line bg-surface-muted p-4 ">
                      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-fg-subtle">Version / Index</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-fg ">
                        <span>{tx('ai.knowledge.viewer.documentVersion')}{selectedDocument.document_version || tx('ai.knowledge.status.notRecorded')}</span>
                        <span>{tx('ai.knowledge.viewer.indexVersion')}{selectedDocument.index_version || tx('ai.knowledge.status.notRecorded')}</span>
                        <span>{tx('ai.knowledge.viewer.parser')}{selectedDocument.parser_version || tx('ai.knowledge.status.notRecorded')}</span>
                        <span>{tx('ai.knowledge.viewer.history')}{tx('ai.knowledge.viewer.historyCount', { count: selectedDocument.source_version_history?.length || 0 })}</span>
                      </div>
                    </section>
                  </div>
                  {versionManagementPanel}
                  {selectedDocument.original_content && <details className="rounded-2xl border border-line bg-surface shadow-sm "><summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-fg ">{tx('ai.knowledge.viewer.original')}</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-line px-4 py-4 font-mono text-xs leading-6 text-fg ">{selectedDocument.original_content}</pre></details>}
                  <EmptyState className="py-8" icon={Layers} title={tx('ai.knowledge.viewer.noChunksTitle')} description={copy.noChunksBody} />
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-2">
                    <section className="rounded-2xl border border-line bg-surface-muted p-4 ">
                      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-fg-subtle">{tx('ai.knowledge.viewer.rawSource')}</div>
                      <div className="mt-2 text-xs font-medium text-fg ">{selectedDocument.raw_source?.source || selectedDocument.source || tx('ai.knowledge.viewer.sourceNotRecorded')}</div>
                      {selectedDocument.raw_source?.references?.map((reference, index) => (
                        <div key={`${String(reference.source_registry_id || 'source')}-${index}`} className="mt-1 truncate text-xs text-fg-muted " title={String(reference.canonical_url || '')}>{String(reference.canonical_url || reference.source_version_id || tx('ai.knowledge.viewer.sourceObservation'))}</div>
                      ))}
                    </section>
                    <section className="rounded-2xl border border-line bg-surface-muted p-4 ">
                      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-fg-subtle">Version / Index</div>
                      <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-fg ">
                        <span>{tx('ai.knowledge.viewer.documentVersion')}{selectedDocument.document_version || tx('ai.knowledge.status.notRecorded')}</span>
                        <span>{tx('ai.knowledge.viewer.indexVersion')}{selectedDocument.index_version || tx('ai.knowledge.status.notRecorded')}</span>
                        <span>{tx('ai.knowledge.viewer.parser')}{selectedDocument.parser_version || tx('ai.knowledge.status.notRecorded')}</span>
                        <span>{tx('ai.knowledge.viewer.history')}{tx('ai.knowledge.viewer.historyCount', { count: selectedDocument.source_version_history?.length || 0 })}</span>
                      </div>
                    </section>
                  </div>
                  {versionManagementPanel}
                  {selectedDocument.original_content && (
                    <details className="rounded-2xl border border-line bg-surface shadow-sm ">
                      <summary className="cursor-pointer px-4 py-3 text-xs font-semibold text-fg ">{tx('ai.knowledge.viewer.original')}</summary>
                      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words border-t border-line px-4 py-4 font-mono text-xs leading-6 text-fg ">{selectedDocument.original_content}</pre>
                    </details>
                  )}
                  <div className="flex items-center gap-2 rounded-2xl border border-accent/30 bg-accent-subtle px-4 py-3 text-xs leading-5 text-fg "><Info className="h-4 w-4 shrink-0 text-accent" />{tx('ai.knowledge.viewer.chunkInfo')}</div>
                  {selectedDocument.chunks.map((chunk, index) => (
                    <section key={chunk.id} className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm ">
                      <div className="flex items-start gap-3 border-b border-line bg-surface-muted px-4 py-3 ">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-subtle text-[11px] font-bold text-accent ">{String(chunk.page || index + 1).padStart(2, '0')}</span>
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-bold text-fg ">{chunk.section || 'General Overview'}</h3>
                          <p className="mt-0.5 text-xs uppercase tracking-[0.12em] text-fg-subtle">{tx('ai.knowledge.viewer.chunkHeading', { index: index + 1, ordinal: chunk.ordinal ?? index })}</p>
                        </div>
                        <div className="ml-auto flex shrink-0 flex-wrap justify-end gap-1 text-xs">
                          {chunk.chunk_role && <StatusBadge tone="accent">{chunk.chunk_role}</StatusBadge>}
                          {chunk.chunk_type && <StatusBadge>{chunk.chunk_type}</StatusBadge>}
                        </div>
                      </div>
                      <pre className="whitespace-pre-wrap break-words px-4 py-4 font-mono text-xs leading-6 text-fg ">{chunk.content}</pre>
                      <div className="grid gap-2 border-t border-line bg-surface-muted px-4 py-3 text-xs sm:grid-cols-2">
                        <div className="flex flex-wrap items-center gap-1.5 text-fg-muted ">
                          <span className="font-semibold text-fg-muted ">{tx('ai.knowledge.viewer.retrievable')}</span>{chunk.is_retrieval_candidate === false ? tx('ai.knowledge.viewer.retrievalNo') : tx('ai.knowledge.viewer.retrievalYes')}
                          <span className="ml-2 font-semibold text-fg-muted ">{tx('ai.knowledge.viewer.token')}</span>{chunk.token_count ?? 0}
                          {chunk.content_hash && <span className="ml-2 font-mono" title={chunk.content_hash}>{tx('ai.knowledge.viewer.hash', { value: chunk.content_hash.slice(0, 10) })}</span>}
                        </div>
                        <div className="text-right text-fg-subtle">{chunk.chunking_version || tx('ai.knowledge.viewer.chunkerNotRecorded')} · {chunk.parser_version || selectedDocument.parser_version || tx('ai.knowledge.viewer.parserNotRecorded')}</div>
                      </div>
                      {(chunk.parent_chunk || (chunk.neighbors && chunk.neighbors.length > 0)) && (
                        <div className="space-y-2 border-t border-line px-4 py-3 ">
                          {chunk.parent_chunk && (
                            <details className="rounded-xl border border-warning/30 bg-warning-subtle px-3 py-2 ">
                              <summary className="cursor-pointer text-xs font-semibold text-warning ">{tx('ai.knowledge.viewer.parent', { name: chunk.parent_chunk.section || chunk.parent_chunk.id })}</summary>
                              <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap break-words border-t border-warning/30 pt-2 font-mono text-xs leading-5 text-warning ">{chunk.parent_chunk.content || tx('ai.knowledge.viewer.parentEmpty')}</pre>
                            </details>
                          )}
                          {chunk.neighbors && chunk.neighbors.length > 0 && (
                            <details className="rounded-xl border border-accent/30 bg-accent-subtle px-3 py-2 ">
                              <summary className="cursor-pointer text-xs font-semibold text-accent ">{tx('ai.knowledge.viewer.neighbors', { count: chunk.neighbors.length })}</summary>
                              <div className="mt-2 space-y-2 border-t border-accent/30 pt-2 ">
                                {chunk.neighbors.map((neighbor) => <div key={neighbor.id} className="rounded-lg bg-surface p-2 "><div className="font-semibold text-xs text-accent ">{tx('ai.knowledge.viewer.ordinal', { name: neighbor.section || neighbor.id, ordinal: neighbor.ordinal ?? '—' })}</div><pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-fg-muted ">{neighbor.content || tx('ai.knowledge.viewer.neighborEmpty')}</pre></div>)}
                              </div>
                            </details>
                          )}
                        </div>
                      )}
                      <details className="border-t border-line px-4 py-3 ">
                        <summary className="cursor-pointer text-xs font-semibold text-fg-muted ">{tx('ai.knowledge.viewer.metadataFields')}</summary>
                        <div className="mt-2 grid gap-3 border-t border-line pt-2 sm:grid-cols-2">
                          <div><div className="mb-1 text-xs font-semibold text-fg-subtle">{tx('ai.knowledge.viewer.metadata')}</div><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950/[0.03] p-2 font-mono text-xs leading-5 text-fg-muted dark:bg-white/[0.04] ">{JSON.stringify(chunk.metadata || {}, null, 2)}</pre></div>
                          <div><div className="mb-1 text-xs font-semibold text-fg-subtle">{tx('ai.knowledge.viewer.sourceLocator')}</div><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950/[0.03] p-2 font-mono text-xs leading-5 text-fg-muted dark:bg-white/[0.04] ">{JSON.stringify(chunk.source_locator || {}, null, 2)}</pre><div className="mt-2 text-xs text-fg-subtle">{tx('ai.knowledge.viewer.documentIndex', { document: chunk.document_version || selectedDocument.document_version || tx('ai.knowledge.status.notRecorded'), index: chunk.index_version || selectedDocument.index_version || tx('ai.knowledge.status.notRecorded') })}</div></div>
                        </div>
                      </details>
                    </section>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-4 text-xs text-fg-subtle sm:px-7"><span className="inline-flex items-center gap-1.5"><CalendarDays className="h-3.5 w-3.5" />{tx('ai.knowledge.viewer.indexedAt')}{new Date(selectedDocument.created_at).toLocaleString()}</span><button type="button" onClick={closeDocument} className="rounded-xl bg-surface-muted px-4 py-2 text-sm font-semibold text-fg transition hover:bg-surface-emphasis ">{tx('ai.knowledge.viewer.close')}</button></div>
          </aside>
        </div>
      )}

      {pendingDocumentAction && (
        <div ref={documentActionDialogRef} className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-labelledby="knowledge-action-impact-title" tabIndex={-1}>
          <div className="w-full max-w-xl rounded-2xl border border-danger/30 bg-surface p-5 shadow-2xl ">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-danger-subtle text-danger "><AlertTriangle className="h-5 w-5" /></div>
              <div className="min-w-0">
                <h3 id="knowledge-action-impact-title" className="text-base font-bold text-fg ">{tx('ai.knowledge.danger.title')}</h3>
                <p className="mt-1 text-xs text-fg-muted ">{tx('ai.knowledge.danger.before', { action: documentActionLabels[pendingDocumentAction.action], name: pendingDocumentAction.preview.name })}</p>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {([
                [tx('ai.knowledge.danger.documents'), pendingDocumentAction.preview.impact.documents],
                [tx('ai.knowledge.danger.chunks'), pendingDocumentAction.preview.impact.chunks],
                [tx('ai.knowledge.danger.indexes'), pendingDocumentAction.preview.impact.indexes],
                [tx('ai.knowledge.danger.references'), pendingDocumentAction.preview.impact.references],
              ] as const).map(([label, value]) => (
                <div key={label} className="rounded-xl border border-line bg-surface-muted px-3 py-2 ">
                  <div className="text-xs text-fg-subtle">{label}</div>
                  <div className="mt-1 font-mono text-lg font-bold text-fg ">{value}</div>
                </div>
              ))}
            </div>
            {pendingDocumentAction.preview.impact.reference_details && pendingDocumentAction.preview.impact.reference_details.length > 0 && (
              <div className="mt-3 rounded-xl border border-warning/30 bg-warning-subtle px-3 py-2 text-[11px] text-warning ">
                {tx('ai.knowledge.danger.referenceDetails')}{pendingDocumentAction.preview.impact.reference_details.map((item) => `${item.type} ${item.count}`).join(tx('ai.knowledge.danger.referenceSeparator'))}
              </div>
            )}
            <div className="mt-3 rounded-xl border border-accent/30 bg-accent-subtle px-3 py-2 text-[11px] leading-5 text-fg ">
              <span className="font-semibold">{tx('ai.knowledge.danger.recovery')}</span>{pendingDocumentAction.preview.recovery[pendingDocumentAction.action] || tx('ai.knowledge.danger.defaultRecovery')}
            </div>
            <div className="mt-3 rounded-xl border border-danger/30 bg-danger-subtle px-3 py-2 text-[11px] leading-5 text-danger ">
              {pendingDocumentAction.action === 'delete' ? tx('ai.knowledge.danger.deleteWarning') : tx('ai.knowledge.danger.taskWarning')}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" data-knowledge-action-cancel onClick={() => setPendingDocumentAction(null)} disabled={Boolean(documentActionBusy)} className="rounded-xl px-4 py-2 text-xs font-semibold text-fg-muted transition hover:bg-surface-muted disabled:opacity-40 ">{tx('ai.knowledge.danger.cancel')}</button>
              <button type="button" onClick={() => void confirmDocumentAction()} disabled={Boolean(documentActionBusy)} className="rounded-xl bg-danger px-4 py-2 text-xs font-semibold text-white transition hover:bg-danger disabled:cursor-wait disabled:opacity-50">{tx('ai.knowledge.danger.confirm', { action: documentActionLabels[pendingDocumentAction.action] })}</button>
            </div>
          </div>
        </div>
      )}

      {/* Upload File & Create Document Modal */}
      {showModal && (
        <div ref={uploadDialogRef} className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="knowledge-upload-title" tabIndex={-1}>
          <div className="bg-surface rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-line pb-3">
              <h3 id="knowledge-upload-title" className="text-base font-bold text-fg flex items-center gap-2">
                <UploadCloud className="w-5 h-5 text-accent" />
                {tx('ai.knowledge.upload.title')}
              </h3>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1 bg-surface-muted p-1 rounded-xl text-xs font-semibold">
                  <button
                    type="button"
                    onClick={() => setInputMode('upload')}
                    aria-pressed={inputMode === 'upload'}
                    className={`px-3 py-1 rounded-lg transition cursor-pointer ${
 inputMode === 'upload' ? 'bg-surface text-accent shadow-2xs' : 'text-fg-muted'
                    }`}
                  >
                    📁 {tx('ai.knowledge.upload.batch')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setInputMode('paste')}
                    aria-pressed={inputMode === 'paste'}
                    className={`px-3 py-1 rounded-lg transition cursor-pointer ${
 inputMode === 'paste' ? 'bg-surface text-accent shadow-2xs' : 'text-fg-muted'
                    }`}
                  >
                    📝 {tx('ai.knowledge.upload.manual')}
                  </button>
                </div>
                <button
                  type="button"
                  onClick={closeModal}
                  disabled={batchSubmitting || submitting}
                  data-knowledge-upload-close
                  aria-label={tx('ai.knowledge.upload.close')}
                  title={tx('ai.knowledge.upload.close')}
                  className="p-1.5 text-fg-subtle hover:text-fg rounded-lg hover:bg-surface-muted disabled:opacity-40"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className={`rounded-xl px-3 py-2 text-[11px] ${
 assetOptionsError || directoryVendorOptions.length === 0
 ? 'bg-warning-subtle text-warning '
                : 'bg-accent-subtle text-accent '
            }`}>
              {assetOptionsLoading
                ? tx('ai.knowledge.upload.assetSyncing')
                : assetOptionsError
                ? assetOptionsError
                : directoryVendorOptions.length === 0
                ? tx('ai.knowledge.upload.noAssets')
                : tx('ai.knowledge.upload.assetSynced', { count: assetOptions.asset_count })}
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
 ? 'border-accent bg-accent-subtle '
                      : fileQueue.length > 0
                      ? 'border-success bg-success-subtle '
                      : 'border-line-strong hover:border-accent bg-surface-muted '
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
                      <UploadCloud className="w-7 h-7 text-accent" />
                      <Archive className="w-6 h-6 text-warning" />
                    </div>
                    <div className="text-xs font-semibold text-fg ">
                      {tx('ai.knowledge.upload.chooseFiles')}
                    </div>
                    <div className="text-[11px] text-fg-subtle space-y-0.5">
                      <div>
                        {tx('ai.knowledge.upload.textFormatsFull')}
                      </div>
                      <div>
                        {tx('ai.knowledge.upload.customFormatFull')}
                      </div>
                      <div>
                        {tx('ai.knowledge.upload.archiveFull')}
                      </div>
                      <div>
                        {tx('ai.knowledge.upload.binaryFull')}
                      </div>
                      <div className="pt-1 text-accent ">
                        {tx('ai.knowledge.upload.restoreNote')}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Metadata selectors (shared for all files in batch) */}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.category')}</label>
                    <DirectoryTreePicker
                      nodes={directoryTree}
                      selectedPath={knowledgeDirectory}
                      loading={directoryTreeLoading}
                      error={directoryTreeError}
                      disabled={batchSubmitting || submitting}
                      canManage={canManageDirectories}
                      title={tx('ai.knowledge.directory.pickerTitle')}
                      onSelect={(node) => setKnowledgeDirectory(node.path)}
                      onCreate={handleCreateDirectory}
                      onRename={handleRenameDirectory}
                      onDelete={handleDeleteDirectory}
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.source')}</label>
                    <select
                      value={sourceType}
                      onChange={(e) => setSourceType(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl "
                    >
                      <option value="internal_sop">{tx('ai.knowledge.upload.source.internalSop')}</option>
                      <option value="internal_standard">{tx('ai.knowledge.upload.source.internalStandard')}</option>
                      <option value="case">{tx('ai.knowledge.upload.source.case')}</option>
                      <option value="sample">{tx('ai.knowledge.upload.source.sample')}</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.vendor')}</label>
                    <select
                      value={vendor}
                      onChange={(e) => {
                        const nextVendor = e.target.value;
                        setVendor(nextVendor);
                        const nextOption = directoryVendorOptions.find((item) => item.value === nextVendor);
                        setPlatform(nextOption?.platforms[0]?.value || '');
                      }}
                      disabled={assetOptionsLoading || directoryVendorOptions.length === 0}
                      className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl "
                    >
                      <option value="">{tx('ai.knowledge.upload.selectVendor')}</option>
                      {directoryVendorOptions.map((item) => (
                        <option key={item.value} value={item.value}>{getVendorDisplayLabel(item.value, language)}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.platform')}</label>
                    <select
                      value={platform}
                      onChange={(e) => setPlatform(e.target.value)}
                      disabled={assetOptionsLoading || !selectedVendorOption}
                      className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl "
                    >
                      <option value="">{tx('ai.knowledge.upload.selectPlatform')}</option>
                      {(selectedVendorOption?.platforms || []).map((item) => (
                        <option key={item.value} value={item.value}>{getPlatformDisplayLabel(vendor, item.value, language)}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="rounded-xl border border-accent/30 bg-accent-subtle px-3 py-2 text-[11px] text-accent ">
                  {tx('ai.knowledge.upload.directoryPrefix')}<span className="font-mono font-semibold">{getDirectoryImportPath(knowledgeDirectory, vendor, language)}</span>
                  <span className="ml-2 text-accent ">{tx('ai.knowledge.upload.zipPathNote')}</span>
                </div>

                {/* File Queue List */}
                {fileQueue.length > 0 && (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="text-xs font-semibold text-fg flex items-center gap-2">
                        <FileUp className="w-4 h-4 text-accent" />
                        {tx('ai.knowledge.upload.fileQueue')}
                        <span className="text-xs font-mono text-fg-subtle">
                          ({tx('ai.knowledge.upload.fileCount', { count: fileQueue.length, size: formatFileSize(totalQueueSize) })})
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-xs font-mono">
                        {pendingCount > 0 && <span className="text-accent">{tx('ai.knowledge.upload.pending', { count: pendingCount })}</span>}
                        {doneCount > 0 && <span className="text-success">{tx('ai.knowledge.upload.done', { count: doneCount })}</span>}
                        {errorCount > 0 && <span className="text-danger">{tx('ai.knowledge.upload.failed', { count: errorCount })}</span>}
                        <button
                          type="button"
                          onClick={clearQueue}
                          disabled={batchSubmitting}
                          className="text-fg-subtle hover:text-danger transition cursor-pointer disabled:opacity-40"
                        >
                          {tx('ai.knowledge.upload.clearQueue')}
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
                              ? 'bg-success-subtle border border-success/30 '
                              : item.status === 'error'
                              ? 'bg-danger-subtle border border-danger/30 '
                              : item.status === 'indexing'
                              ? 'bg-accent-subtle border border-accent/30 '
                              : 'bg-surface-muted border border-line '
                          }`}
                        >
                          {/* Status icon */}
                          <div className="flex-shrink-0">
                            {item.status === 'done' && <CheckCircle className="w-4 h-4 text-success" />}
                            {item.status === 'error' && <XCircle className="w-4 h-4 text-danger" />}
                            {item.status === 'indexing' && <Loader2 className="w-4 h-4 text-accent animate-spin" />}
                            {item.status === 'pending' && <FileText className="w-4 h-4 text-fg-subtle" />}
                          </div>

                          {item.status === 'pending' && (
                            <div className="w-full basis-full rounded-xl border border-line bg-surface p-2 ">
                              <div className="mb-1 flex items-center justify-between gap-2 text-xs font-semibold text-fg-muted ">
                                <span>{tx('ai.knowledge.upload.preview')}</span>
                                <span className={metadata.validation === 'error' ? 'text-danger' : metadata.validation === 'warning' ? 'text-warning' : 'text-success'}>{metadata.validation === 'error' ? tx('ai.knowledge.upload.metadata.needsFix') : metadata.validation === 'warning' ? tx('ai.knowledge.upload.metadata.confirm') : tx('ai.knowledge.upload.metadata.ready')}</span>
                              </div>
                              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                                <select value={metadata.vendor} onChange={(event) => updateQueueMetadata(item.id, 'vendor', event.target.value)} className="rounded-lg border border-line bg-surface-muted px-2 py-1.5 text-xs " aria-label={`${item.fileName} Vendor Metadata`}>
                                  <option value="">Vendor</option>
                                  {directoryVendorOptions.map((option) => <option key={option.value} value={option.value}>{option.value}</option>)}
                                </select>
                                <select value={metadata.platform} onChange={(event) => updateQueueMetadata(item.id, 'platform', event.target.value)} className="rounded-lg border border-line bg-surface-muted px-2 py-1.5 text-xs " aria-label={`${item.fileName} Platform Metadata`}>
                                  <option value="">CLI Platform</option>
                                  {(directoryVendorOptions.find((option) => option.value === metadata.vendor)?.platforms || []).map((option) => <option key={option.value} value={option.value}>{option.value}</option>)}
                                </select>
                                <select value={metadata.sourceType} onChange={(event) => updateQueueMetadata(item.id, 'sourceType', event.target.value)} className="rounded-lg border border-line bg-surface-muted px-2 py-1.5 text-xs " aria-label={`${item.fileName} source type Metadata`}>
                                  <option value="internal_sop">{tx('ai.knowledge.upload.source.internalSop')}</option>
                                  <option value="internal_standard">{tx('ai.knowledge.upload.source.internalStandard')}</option>
                                  <option value="case">{tx('ai.knowledge.upload.source.case')}</option>
                                  <option value="sample">{tx('ai.knowledge.upload.source.sample')}</option>
                                  <option value="user_document">{tx('ai.knowledge.upload.source.userDocument')}</option>
                                </select>
                              </div>
                              <div className="mt-1 text-xs text-fg-muted ">{tx('ai.knowledge.upload.metadata.directory', { path: metadata.directoryPath, issue: metadata.issue ? ` · ${metadata.issue}` : '' })}</div>
                            </div>
                          )}

                          {/* File info */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-fg truncate">{item.fileName}</span>
                              <span className="text-xs text-fg-subtle font-mono flex-shrink-0">{formatFileSize(item.fileSize)}</span>
                            </div>
                            {item.fromZip && (
                              <div className="text-xs text-warning flex items-center gap-1 mt-0.5">
                                <PackageOpen className="w-3 h-3" />
                                {tx('ai.knowledge.upload.fromZip', { name: item.fromZip })}
                              </div>
                            )}
                            {item.relativePath && (
                              <div className="text-xs text-accent truncate mt-0.5" title={item.relativePath}>
                                {tx('ai.knowledge.upload.relativePath', { path: item.relativePath })}
                              </div>
                            )}
                            {item.error && (
                              <div className="text-xs text-danger mt-0.5">{item.error}</div>
                            )}
                          </div>

                          {/* Status label */}
                          <div className="flex-shrink-0 text-xs font-mono">
                            {item.status === 'pending' && <span className="text-accent">{tx('ai.knowledge.upload.queueStatus.pending')}</span>}
                            {item.status === 'indexing' && <span className="text-accent">{tx('ai.knowledge.upload.queueStatus.indexing')}</span>}
                            {item.status === 'done' && <span className="text-success">{tx('ai.knowledge.upload.queueStatus.done')}</span>}
                            {item.status === 'error' && <span className="text-danger">{tx('ai.knowledge.upload.queueStatus.error')}</span>}
                          </div>

                          {/* Remove button */}
                          {item.status !== 'indexing' && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); removeFromQueue(item.id); }}
                              disabled={batchSubmitting}
                              className="flex-shrink-0 p-1 text-fg-subtle hover:text-danger transition cursor-pointer disabled:opacity-40"
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
                      <div className="p-3 bg-accent-subtle rounded-xl border border-accent/30 space-y-2">
                        <div className="flex items-center justify-between text-xs font-semibold text-accent ">
                          <span className="flex items-center gap-2">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            {tx('ai.knowledge.upload.parsing')}
                          </span>
                          <span className="font-mono">{batchProgress.done} / {batchProgress.total}</span>
                        </div>
                        <div className="w-full bg-accent-subtle rounded-full h-1.5">
                          <div
                            className="bg-accent h-1.5 rounded-full transition-all duration-300"
                            style={{ width: `${batchProgress.total > 0 ? (batchProgress.done / batchProgress.total) * 100 : 0}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Action buttons */}
                <div className="flex justify-end gap-3 pt-3 border-t border-line ">
                  <button
                    type="button"
                    onClick={closeModal}
                    disabled={batchSubmitting}
                    className="px-4 py-2 text-xs text-fg-muted hover:bg-surface-muted rounded-xl cursor-pointer disabled:opacity-40"
                  >
                    {tx('ai.knowledge.common.cancel')}
                  </button>
                  <button
                    type="button"
                    onClick={handleBatchSubmit}
                    disabled={batchSubmitting || pendingCount === 0 || !vendor || !platform || assetOptionsLoading}
                    className="px-5 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold disabled:opacity-50 transition shadow-xs cursor-pointer flex items-center gap-2"
                  >
                    {batchSubmitting ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        {tx('ai.knowledge.upload.batchIndexing')}
                      </>
                    ) : (
                      <>
                        <UploadCloud className="w-3.5 h-3.5" />
                        {tx('ai.knowledge.upload.batchSubmit', { count: pendingCount })}
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
                  <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.documentTitle')}</label>
                  <input
                    type="text"
                    required
                    placeholder={tx('ai.knowledge.upload.documentTitlePlaceholder')}
                    value={docName}
                    onChange={(e) => setDocName(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl "
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.category')}</label>
                    <DirectoryTreePicker
                      nodes={directoryTree}
                      selectedPath={knowledgeDirectory}
                      loading={directoryTreeLoading}
                      error={directoryTreeError}
                      disabled={batchSubmitting || submitting}
                      canManage={canManageDirectories}
                      title={tx('ai.knowledge.directory.pickerTitle')}
                      onSelect={(node) => setKnowledgeDirectory(node.path)}
                      onCreate={handleCreateDirectory}
                      onRename={handleRenameDirectory}
                      onDelete={handleDeleteDirectory}
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.source')}</label>
                    <select
                      value={sourceType}
                      onChange={(e) => setSourceType(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl "
                    >
                      <option value="internal_sop">{tx('ai.knowledge.upload.source.internalSop')}</option>
                      <option value="internal_standard">{tx('ai.knowledge.upload.source.internalStandard')}</option>
                      <option value="case">{tx('ai.knowledge.upload.source.case')}</option>
                      <option value="sample">{tx('ai.knowledge.upload.source.sample')}</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.vendor')}</label>
                    <select
                      value={vendor}
                      onChange={(e) => {
                        const nextVendor = e.target.value;
                        setVendor(nextVendor);
                        const nextOption = directoryVendorOptions.find((item) => item.value === nextVendor);
                        setPlatform(nextOption?.platforms[0]?.value || '');
                      }}
                      disabled={assetOptionsLoading || directoryVendorOptions.length === 0}
                      className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl "
                    >
                      <option value="">{tx('ai.knowledge.upload.selectVendor')}</option>
                      {directoryVendorOptions.map((item) => (
                        <option key={item.value} value={item.value}>{getVendorDisplayLabel(item.value, language)}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-fg mb-1">{tx('ai.knowledge.upload.platform')}</label>
                    <select
                      value={platform}
                      onChange={(e) => setPlatform(e.target.value)}
                      disabled={assetOptionsLoading || !selectedVendorOption}
                      className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl "
                    >
                      <option value="">{tx('ai.knowledge.upload.selectPlatform')}</option>
                      {(selectedVendorOption?.platforms || []).map((item) => (
                        <option key={item.value} value={item.value}>{getPlatformDisplayLabel(vendor, item.value, language)}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="rounded-xl border border-accent/30 bg-accent-subtle px-3 py-2 text-[11px] text-accent ">
                  {tx('ai.knowledge.upload.directory')}<span className="font-mono font-semibold">{getDirectoryImportPath(knowledgeDirectory, vendor, language)}</span>
                  <span className="ml-2 text-accent ">{tx('ai.knowledge.upload.sourceNote')}</span>
                </div>

                <div>
                  <label className="block text-xs font-medium text-fg mb-1">
                    {tx('ai.knowledge.upload.contentPreview')}
                  </label>
                  <textarea
                    required
                    rows={5}
                    placeholder={tx('ai.knowledge.upload.contentPlaceholder')}
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-line-strong rounded-xl font-mono leading-relaxed"
                  />
                </div>

                {/* 6-Step Indexing Stepper */}
                {submitting && (
                  <div className="p-3 bg-surface-muted rounded-xl border border-line space-y-2">
                    <div className="text-xs font-semibold text-accent flex items-center justify-between">
                      <span>{tx('ai.knowledge.upload.pipeline')}</span>
                      <span>{indexingStep} / 6</span>
                    </div>
                    <div className="grid grid-cols-6 gap-1">
                      {pipelineSteps.map((stepLabel, idx) => {
                        const isCompleted = idx + 1 <= indexingStep;
                        return (
                          <div
                            key={idx}
                            className={`h-1.5 rounded-full transition-colors ${
 isCompleted ? 'bg-accent' : 'bg-surface-emphasis '
                            }`}
                            title={stepLabel}
                          />
                        );
                      })}
                    </div>
                    <div className="text-[11px] text-fg-muted font-mono text-center pt-1">
                      {tx('ai.knowledge.upload.currentStage', { stage: pipelineSteps[Math.max(0, indexingStep - 1)] })}
                    </div>
                  </div>
                )}

                <div className="flex justify-end gap-3 pt-3 border-t border-line ">
                  <button
                    type="button"
                    onClick={closeModal}
                    disabled={submitting}
                    className="px-4 py-2 text-xs text-fg-muted hover:bg-surface-muted rounded-xl cursor-pointer"
                  >
                    {tx('ai.knowledge.common.cancel')}
                  </button>
                  <button
                    type="submit"
                    disabled={submitting || !docName.trim() || !content.trim() || !vendor || !platform || assetOptionsLoading}
                    className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold disabled:opacity-50 transition shadow-xs cursor-pointer"
                  >
                    {submitting ? tx('ai.knowledge.ingestion.submitting') : tx('ai.knowledge.upload.parseIndex')}
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

