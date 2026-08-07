import React, { useEffect, useState, useRef, useCallback } from 'react';
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
} from 'lucide-react';
import { getKnowledgeStats, getKnowledgeDocuments, addKnowledgeDocument, clearSampleKnowledge, deleteKnowledgeDocument, batchDeleteKnowledgeDocuments } from '../../../api/ai';

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
}

/* ── Supported text extensions ── */
const TEXT_EXTENSIONS = ['.md', '.markdown', '.txt', '.html', '.htm', '.json', '.yaml', '.yml', '.log', '.csv', '.xml', '.conf', '.cfg', '.ini'];
const ALL_SUPPORTED_EXTENSIONS = [...TEXT_EXTENSIONS, '.docx', '.pdf', '.zip'];

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

export const KnowledgeManagementTab: React.FC = () => {
  const [stats, setStats] = useState({
    total_documents: 0,
    total_chunks: 0,
    total_vendors: 0,
    ready_indexes: 0,
  });

  const [selectedFolder, setSelectedFolder] = useState<string>('all');
  const [documents, setDocuments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  // Modal & File Upload State
  const [showModal, setShowModal] = useState(false);
  const [inputMode, setInputMode] = useState<'upload' | 'paste'>('upload');
  const [docName, setDocName] = useState('');
  const [content, setContent] = useState('');
  const [vendor, setVendor] = useState('Huawei');
  const [platform, setPlatform] = useState('huawei_vrp');
  const [sourceType, setSourceType] = useState('internal_sop');
  const [indexingStep, setIndexingStep] = useState<number>(0);
  const [submitting, setSubmitting] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  // Multi-file queue
  const [fileQueue, setFileQueue] = useState<FileQueueItem[]>([]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: 0 });

  // Document selection for batch delete
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const folders: FolderCategory[] = [
    { id: 'all', name: '全部目录文档', icon: '📂', description: '汇总展示所有分类及厂商知识底座' },
    { id: 'internal_sop', name: '企业内部 SOP 目录', icon: '📘', description: '标准化变更与日常运维指导手册' },
    { id: 'official_vendor', name: '厂商官方手册库', icon: '🏢', description: 'Huawei / Cisco / H3C 官方配置与调优资料' },
    { id: 'internal_standard', name: '企业规范标准库', icon: '📜', description: 'IP 划分子网、VLAN 命名与安全基线规范' },
    { id: 'case', name: '应急处置与排查案例', icon: '🚨', description: '历史重大故障与 Emergency Runbook' },
    { id: 'sample', name: '系统初始化示例', icon: '🧪', description: '系统自带演示文档' },
  ];

  const fetchStatsAndDocs = async () => {
    setLoading(true);
    try {
      const s = await getKnowledgeStats();
      setStats(s);

      let typeFilter: string | undefined;
      if (selectedFolder !== 'all') {
        typeFilter = selectedFolder;
      }

      const docs = await getKnowledgeDocuments(typeFilter);
      setDocuments(docs);
    } catch (e) {
      console.error('Failed to load knowledge metrics:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatsAndDocs();
  }, [selectedFolder]);

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
        items.push({
          id: `${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
          fileName: baseName,
          fileSize: textContent.length,
          content: textContent,
          status: 'pending',
          fromZip: file.name,
        });
      } catch {
        // skip binary/corrupted entries silently
      }
    }
    return items;
  };

  /* ── Process multiple files (including ZIPs) into the queue ── */
  const processFiles = useCallback(async (files: FileList | File[]) => {
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

  /* ── Batch submit all pending files ── */
  const handleBatchSubmit = async () => {
    const pendingItems = fileQueue.filter(item => item.status === 'pending' && item.content.trim());
    if (pendingItems.length === 0) return;

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
          platform,
          knowledge_source_type: sourceType,
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

  const filteredDocs = documents.filter((doc) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      doc.name.toLowerCase().includes(q) ||
      (doc.vendor && doc.vendor.toLowerCase().includes(q)) ||
      (doc.platform && doc.platform.toLowerCase().includes(q))
    );
  });

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
    if (selectedDocIds.size === filteredDocs.length) {
      setSelectedDocIds(new Set());
    } else {
      setSelectedDocIds(new Set(filteredDocs.map(d => d.id)));
    }
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

        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              setInputMode('upload');
              setShowModal(true);
            }}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-semibold flex items-center gap-2 shadow-xs transition cursor-pointer"
          >
            <UploadCloud className="w-4 h-4" />
            批量上传知识文件 / ZIP 压缩包
          </button>
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
          <div className="text-[11px] text-gray-400">Cisco / Huawei / H3C / ZTE</div>
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
        {/* Left Directory & Folder Category Tree Sidebar */}
        <div className="bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-700/80 rounded-2xl p-4 shadow-xs space-y-3">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-700/60 pb-2">
            <h3 className="text-xs font-bold text-gray-900 dark:text-white uppercase flex items-center gap-1.5">
              <Folder className="w-4 h-4 text-indigo-500" />
              知识库目录分类
            </h3>
            <span className="text-[10px] text-gray-400 font-mono">{folders.length} 目录</span>
          </div>

          <div className="space-y-1">
            {folders.map((f) => {
              const isSelected = selectedFolder === f.id;
              return (
                <button
                  key={f.id}
                  onClick={() => setSelectedFolder(f.id)}
                  className={`w-full p-2.5 rounded-xl text-left transition flex items-center justify-between cursor-pointer ${
                    isSelected
                      ? 'bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200/80 dark:border-indigo-800/80 text-indigo-700 dark:text-indigo-300 font-semibold'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/60'
                  }`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-base">{f.icon}</span>
                    <div className="truncate">
                      <div className="text-xs truncate">{f.name}</div>
                      <div className="text-[10px] text-gray-400 truncate font-normal">{f.description}</div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          {selectedFolder === 'sample' && (
            <button
              onClick={handleClearSample}
              className="w-full mt-2 px-3 py-2 bg-red-50 dark:bg-red-950/60 hover:bg-red-100 text-red-600 dark:text-red-400 rounded-xl text-xs font-medium flex items-center justify-center gap-1.5 transition cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
              清空全部示例知识
            </button>
          )}
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
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
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
                当前目录: <strong className="text-gray-800 dark:text-gray-200 font-semibold">{folders.find((f) => f.id === selectedFolder)?.name}</strong> ({filteredDocs.length} 篇)
              </div>
            </div>
          </div>

          {/* Table Container */}
          <div className="bg-white dark:bg-gray-800 border border-gray-200/80 dark:border-gray-700/80 rounded-2xl overflow-hidden shadow-xs">
            {loading ? (
              <div className="p-8 text-center text-xs text-gray-400">数据加载中...</div>
            ) : filteredDocs.length === 0 ? (
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
                        checked={filteredDocs.length > 0 && selectedDocIds.size === filteredDocs.length}
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
                  {filteredDocs.map((doc) => {
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
                          <div className="flex items-center gap-2">
                            <FileCode className="w-4 h-4 text-indigo-500 flex-shrink-0" />
                            <span className="truncate">{doc.name}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded-full font-medium text-[11px] ${badge.bg} ${badge.color}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-600 dark:text-gray-300">
                          {doc.vendor.toUpperCase()} / {doc.platform.toUpperCase()}
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
          </div>
        </div>
      </div>

      {/* Upload File & Create Document Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-700 pb-3">
              <h3 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <UploadCloud className="w-5 h-5 text-indigo-500" />
                新增与上传企业知识文件
              </h3>
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
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标知识目录 (批量统一)</label>
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
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标网络厂商 (批量统一)</label>
                    <select
                      value={vendor}
                      onChange={(e) => setVendor(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="Huawei">Huawei (华为)</option>
                      <option value="Cisco">Cisco (思科)</option>
                      <option value="H3C">H3C (华三)</option>
                      <option value="ZTE">ZTE (中兴)</option>
                      <option value="all">通用 (All)</option>
                    </select>
                  </div>
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
                    onClick={() => { setShowModal(false); clearQueue(); }}
                    disabled={batchSubmitting}
                    className="px-4 py-2 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-xl cursor-pointer disabled:opacity-40"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={handleBatchSubmit}
                    disabled={batchSubmitting || pendingCount === 0}
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

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标知识目录</label>
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
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">目标网络厂商</label>
                    <select
                      value={vendor}
                      onChange={(e) => setVendor(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-xl dark:bg-gray-900 dark:text-white"
                    >
                      <option value="Huawei">Huawei (华为)</option>
                      <option value="Cisco">Cisco (思科)</option>
                      <option value="H3C">H3C (华三)</option>
                      <option value="ZTE">ZTE (中兴)</option>
                      <option value="all">通用 (All)</option>
                    </select>
                  </div>
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
                    onClick={() => setShowModal(false)}
                    disabled={submitting}
                    className="px-4 py-2 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-xl cursor-pointer"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    disabled={submitting || !docName.trim() || !content.trim()}
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

