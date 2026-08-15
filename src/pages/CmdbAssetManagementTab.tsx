import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import * as XLSX from "xlsx";
import {
  Check,
  ChevronRight,
  Download,
  Filter,
  FolderTree,
  Package,
  RefreshCw,
  Search,
  Server,
  Settings2,
  Tag,
  X,
} from "lucide-react";
import TagFilterDropdown from "../components/TagFilterDropdown";
import Pagination from "../components/Pagination";
import { DataTable } from "../components/DataTable";
import { BatchTagModal } from "./AssetManagement/components/BatchTagModal";
import type { SessionUser, TagDefinition } from "../types";

interface Props {
  language?: string;
  currentUser?: Pick<SessionUser, "role">;
}

interface TreeRow {
  site_id: string;
  site_name: string;
  site_code?: string;
  asset_type: string;
  device_category: string;
  device_role: string;
  online_status: string;
  asset_count: number;
}

interface AssetRow {
  id: string;
  device_id?: string;
  hostname: string;
  asset_tag: string;
  serial_number: string;
  asset_type: string;
  device_category: string;
  device_role: string;
  vendor: string;
  model: string;
  site_id: string;
  site_name?: string;
  site_code?: string;
  management_ip: string;
  online_status: string;
  status: string;
  lifecycle_status: string;
  created_at: string;
  updated_at: string;
  tags?: Array<{
    id: string;
    label: string;
    label_zh: string;
    color: string;
    category: string;
  }>;
}

interface TreeNode {
  id: string;
  label: string;
  kind: "root" | "site" | "type" | "category" | "role";
  count: number;
  branch?: Partial<
    Pick<TreeRow, "site_id" | "asset_type" | "device_category" | "device_role">
  >;
  children: TreeNode[];
}

type ColumnKey =
  | "asset"
  | "category"
  | "site"
  | "status"
  | "tags"
  | "vendor"
  | "model"
  | "serial"
  | "management_ip"
  | "lifecycle"
  | "created"
  | "updated";
type ColumnVisibility = Record<ColumnKey, boolean>;

const TYPE_LABELS: Record<string, [string, string]> = {
  network_device: ["网络设备", "Network devices"],
  server: ["服务器", "Servers"],
  other: ["其他资产", "Other assets"],
};
const CATEGORY_LABELS: Record<string, [string, string]> = {
  router: ["路由器", "Routers"],
  switch: ["交换机", "Switches"],
  firewall: ["防火墙", "Firewalls"],
  blade_server: ["刀片服务器", "Blade servers"],
  rack_server: ["机架服务器", "Rack servers"],
  storage: ["存储设备", "Storage"],
  other: ["未分类产品", "Uncategorised"],
};
const STATUS_LABELS: Record<string, [string, string]> = {
  online: ["在线", "Online"],
  offline: ["离线", "Offline"],
  pending: ["待确认", "Pending"],
};
const LIFECYCLE_LABELS: Record<string, [string, string]> = {
  production: ["已投产", "Production"],
  staging: ["待投产", "Staging"],
  maintenance: ["维护中", "Maintenance"],
  decommissioned: ["已退役", "Decommissioned"],
};
const COLUMN_DEFS: Array<{ key: ColumnKey; zh: string; en: string }> = [
  { key: "asset", zh: "设备", en: "Asset" },
  { key: "category", zh: "分类 / 角色", en: "Category / role" },
  { key: "site", zh: "站点", en: "Site" },
  { key: "status", zh: "在线状态", en: "Status" },
  { key: "tags", zh: "标签", en: "Tags" },
  { key: "vendor", zh: "厂商", en: "Vendor" },
  { key: "model", zh: "型号", en: "Model" },
  { key: "serial", zh: "序列号", en: "Serial" },
  { key: "management_ip", zh: "管理 IP", en: "Management IP" },
  { key: "lifecycle", zh: "资产状态", en: "Asset status" },
  { key: "created", zh: "创建时间", en: "Created" },
  { key: "updated", zh: "更新时间", en: "Updated" },
];
const DEFAULT_COLUMNS: ColumnVisibility = {
  asset: true,
  category: true,
  site: true,
  status: true,
  tags: true,
  vendor: false,
  model: false,
  serial: false,
  management_ip: false,
  lifecycle: false,
  created: true,
  updated: true,
};
const COLUMN_STORAGE_KEY = "cmdb-asset-catalog-columns-v1";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("netops_token") || "";
  return { Authorization: `Bearer ${token}` };
}
function labelOf(
  map: Record<string, [string, string]>,
  value: string,
  zh: boolean,
): string {
  return map[value]?.[zh ? 0 : 1] || value || (zh ? "未分配" : "Unassigned");
}
function formatDate(value?: string): string {
  return value
    ? value
        .replace("T", " ")
        .replace(/\+00:00$/, "")
        .slice(0, 19)
    : "—";
}

function buildTree(rows: TreeRow[], zh: boolean): TreeNode[] {
  const root: TreeNode = {
    id: "root",
    label: zh ? "全部资产" : "All assets",
    kind: "root",
    count: 0,
    children: [],
  };
  const findOrCreate = (
    parent: TreeNode,
    id: string,
    label: string,
    kind: TreeNode["kind"],
    branch: TreeNode["branch"],
    count: number,
  ) => {
    let node = parent.children.find((item) => item.id === id);
    if (!node) {
      node = { id, label, kind, branch, count: 0, children: [] };
      parent.children.push(node);
    }
    node.count += count;
    return node;
  };
  rows.forEach((row) => {
    const siteId = row.site_id === "unassigned" ? "" : row.site_id;
    const site = findOrCreate(
      root,
      `site:${row.site_id}`,
      row.site_name || (zh ? "未分配站点" : "Unassigned site"),
      "site",
      { site_id: siteId },
      row.asset_count,
    );
    const type = findOrCreate(
      site,
      `${site.id}:type:${row.asset_type}`,
      labelOf(TYPE_LABELS, row.asset_type, zh),
      "type",
      { site_id: siteId, asset_type: row.asset_type },
      row.asset_count,
    );
    const category = findOrCreate(
      type,
      `${type.id}:category:${row.device_category}`,
      labelOf(CATEGORY_LABELS, row.device_category, zh),
      "category",
      {
        site_id: siteId,
        asset_type: row.asset_type,
        device_category: row.device_category,
      },
      row.asset_count,
    );
    const role = row.device_role === "unassigned" ? "" : row.device_role;
    findOrCreate(
      category,
      `${category.id}:role:${row.device_role}`,
      role || (zh ? "未分配角色" : "Unassigned role"),
      "role",
      {
        site_id: siteId,
        asset_type: row.asset_type,
        device_category: row.device_category,
        device_role: role,
      },
      row.asset_count,
    );
  });
  return [root];
}

const CmdbAssetManagementTab: React.FC<Props> = ({
  language = "zh",
  currentUser,
}) => {
  const zh = language === "zh";
  const canManageTags = currentUser?.role === "Administrator";
  const [treeRows, setTreeRows] = useState<TreeRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(["root"]));
  const [treeCollapsed, setTreeCollapsed] = useState(false);
  const [selectedBranch, setSelectedBranch] = useState<Record<string, string>>(
    {},
  );
  const [selectedLabel, setSelectedLabel] = useState(
    zh ? "全部资产" : "All assets",
  );
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [filterTagIds, setFilterTagIds] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [treeLoading, setTreeLoading] = useState(true);
  const [error, setError] = useState("");
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const columnsMenuRef = useRef<HTMLDivElement>(null);
  const [visibleColumns, setVisibleColumns] = useState<ColumnVisibility>(() => {
    try {
      const stored = JSON.parse(
        localStorage.getItem(COLUMN_STORAGE_KEY) || "{}",
      );
      return {
        ...DEFAULT_COLUMNS,
        ...stored,
        asset: true,
        category: true,
        site: true,
        status: true,
        tags: true,
        created: true,
        updated: true,
      };
    } catch {
      return DEFAULT_COLUMNS;
    }
  });

  useEffect(() => {
    localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(visibleColumns));
  }, [visibleColumns]);
  useEffect(() => {
    if (!columnsOpen) return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (
        columnsMenuRef.current &&
        !columnsMenuRef.current.contains(event.target as Node)
      ) {
        setColumnsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [columnsOpen]);
  const activeColumns = useMemo(
    () => COLUMN_DEFS.filter((column) => visibleColumns[column.key]),
    [visibleColumns],
  );
  const allColumnsSelected = COLUMN_DEFS.every(
    (column) => visibleColumns[column.key],
  );

  const loadTree = useCallback(async () => {
    setTreeLoading(true);
    try {
      const response = await fetch("/api/cmdb/assets/tree", {
        headers: authHeaders(),
      });
      const json = await response.json();
      if (!response.ok || json.success === false)
        throw new Error(json.detail || json.message || "Failed to load tree");
      setTreeRows(json.data?.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTreeLoading(false);
    }
  }, []);

  const loadTags = useCallback(async () => {
    try {
      const response = await fetch("/api/tags/definitions", {
        headers: authHeaders(),
      });
      const json = await response.json();
      if (response.ok) setAllTags(json.data || []);
    } catch {
      /* empty tag list is rendered safely */
    }
  }, []);

  const buildParams = useCallback(
    (requestedPage: number, requestedPageSize: number) => {
      const params = new URLSearchParams({
        page: String(requestedPage),
        page_size: String(requestedPageSize),
        q: query,
        status,
      });
      Object.entries(selectedBranch).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      if (filterTagIds.length) params.set("tag_ids", filterTagIds.join(","));
      return params;
    },
    [filterTagIds, query, selectedBranch, status],
  );

  const loadAssets = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(
        `/api/cmdb/assets?${buildParams(page, pageSize).toString()}`,
        { headers: authHeaders() },
      );
      const json = await response.json();
      if (!response.ok || json.success === false)
        throw new Error(json.detail || json.message || "Failed to load assets");
      setAssets(json.data?.items || []);
      setTotal(json.data?.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [buildParams, page, pageSize]);

  useEffect(() => {
    void loadTree();
    void loadTags();
  }, [loadTags, loadTree]);
  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  const tree = useMemo(() => buildTree(treeRows, zh), [treeRows, zh]);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const allPageSelected =
    assets.length > 0 &&
    assets.every((asset) => selectedIds.includes(asset.id));

  const selectBranch = (node: TreeNode) => {
    setSelectedBranch(node.branch || {});
    setSelectedLabel(node.label);
    setPage(1);
    setSelectedIds([]);
  };
  const toggleNode = (node: TreeNode) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(node.id)) next.delete(node.id);
      else next.add(node.id);
      return next;
    });

  const batchTag = async () => {
    const deviceIds = assets
      .filter((asset) => selectedIds.includes(asset.id) && asset.device_id)
      .map((asset) => asset.device_id as string);
    if (!deviceIds.length || !selectedTagIds.length) return;
    const response = await fetch("/api/tags/devices/batch", {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ device_ids: deviceIds, tag_ids: selectedTagIds }),
    });
    const json = await response.json().catch(() => ({}));
    if (!response.ok || json.success === false) {
      setError(
        json.detail ||
          json.message ||
          (zh ? "标签更新失败" : "Tag update failed"),
      );
      return;
    }
    setTagModalOpen(false);
    setSelectedTagIds([]);
    setSelectedIds([]);
    await loadAssets();
    await loadTree();
  };

  const exportExcel = async () => {
    try {
      const firstResponse = await fetch(
        `/api/cmdb/assets?${buildParams(1, 1000).toString()}`,
        { headers: authHeaders() },
      );
      const firstJson = await firstResponse.json();
      if (!firstResponse.ok || firstJson.success === false)
        throw new Error(
          firstJson.detail || firstJson.message || "Export failed",
        );
      const rows: AssetRow[] = [...(firstJson.data?.items || [])];
      const totalExportPages = Math.min(
        Number(firstJson.data?.total_pages || 1),
        100,
      );
      for (
        let exportPage = 2;
        exportPage <= totalExportPages;
        exportPage += 1
      ) {
        const response = await fetch(
          `/api/cmdb/assets?${buildParams(exportPage, 1000).toString()}`,
          { headers: authHeaders() },
        );
        const json = await response.json();
        if (!response.ok || json.success === false)
          throw new Error(json.detail || json.message || "Export failed");
        rows.push(...(json.data?.items || []));
      }
      const data = rows.map((asset) =>
        Object.fromEntries(
          activeColumns.map((column) => {
            const title = zh ? column.zh : column.en;
            const value =
              column.key === "asset"
                ? asset.hostname
                : column.key === "category"
                  ? `${labelOf(CATEGORY_LABELS, asset.device_category || "other", zh)} / ${asset.device_role || (zh ? "未分配" : "Unassigned")}`
                  : column.key === "site"
                    ? asset.site_name || asset.site_code || asset.site_id || "—"
                    : column.key === "status"
                      ? labelOf(STATUS_LABELS, asset.online_status, zh)
                      : column.key === "tags"
                        ? (asset.tags || [])
                            .map((tag) =>
                              zh ? tag.label_zh || tag.label : tag.label,
                            )
                            .join(", ")
                        : column.key === "vendor"
                          ? asset.vendor
                          : column.key === "model"
                            ? asset.model
                            : column.key === "serial"
                              ? asset.serial_number
                              : column.key === "management_ip"
                                ? asset.management_ip
                                : column.key === "lifecycle"
                                  ? labelOf(LIFECYCLE_LABELS, asset.lifecycle_status, zh)
                                  : column.key === "created"
                                    ? formatDate(asset.created_at)
                                    : formatDate(asset.updated_at);
            return [title, value];
          }),
        ),
      );
      const worksheet = XLSX.utils.json_to_sheet(data);
      const workbook = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(
        workbook,
        worksheet,
        zh ? "资产目录" : "Asset catalog",
      );
      XLSX.writeFile(
        workbook,
        `cmdb_asset_catalog_${new Date().toISOString().slice(0, 10)}.xlsx`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const renderNode = (node: TreeNode, depth = 0): React.ReactNode => {
    const isExpanded = expanded.has(node.id);
    const isSelected =
      JSON.stringify(selectedBranch) === JSON.stringify(node.branch || {});
    return (
      <div key={node.id}>
        <div
          className={`group flex items-center gap-1.5 rounded-lg px-2 py-2 text-xs transition-colors ${isSelected ? "bg-cyan-50 text-cyan-800" : "text-slate-600 hover:bg-slate-50"}`}
          style={{ paddingLeft: `${8 + depth * 14}px` }}
        >
          {node.children.length > 0 ? (
            <button
              onClick={() => toggleNode(node)}
              className="shrink-0 text-slate-400"
            >
              <ChevronRight
                size={14}
                className={
                  isExpanded
                    ? "rotate-90 transition-transform"
                    : "transition-transform"
                }
              />
            </button>
          ) : (
            <span className="w-[14px]" />
          )}
          <button
            onClick={() => selectBranch(node)}
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
          >
            {node.kind === "site" ? (
              <FolderTree size={14} className="text-cyan-600" />
            ) : node.kind === "type" ? (
              <Server size={14} className="text-indigo-500" />
            ) : node.kind === "root" ? (
              <Package size={14} className="text-cyan-600" />
            ) : (
              <Tag size={13} className="text-slate-400" />
            )}
            <span className="truncate">{node.label}</span>
            <span className="ml-auto rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] tabular-nums text-slate-500">
              {node.count}
            </span>
          </button>
        </div>
        {isExpanded &&
          node.children.map((child) => renderNode(child, depth + 1))}
      </div>
    );
  };

  const renderCell = (asset: AssetRow, key: ColumnKey): React.ReactNode => {
    if (key === "asset")
      return (
        <>
          <div className="font-semibold text-slate-800">
            {asset.hostname || "—"}
          </div>
          <div className="mt-1 font-mono text-[10px] text-slate-400">
            {asset.management_ip ||
              asset.asset_tag ||
              asset.serial_number ||
              asset.id}
          </div>
        </>
      );
    if (key === "category")
      return (
        <>
          <div className="text-slate-700">
            {labelOf(CATEGORY_LABELS, asset.device_category || "other", zh)}
          </div>
          <div className="mt-1 text-[10px] text-slate-400">
            {asset.device_role || (zh ? "未分配角色" : "Unassigned role")}
          </div>
        </>
      );
    if (key === "site")
      return (
        <>
          <div className="text-slate-700">{asset.site_name || asset.site_code || asset.site_id || "—"}</div>
        </>
      );
    if (key === "status")
      return (
        <span
          className={`inline-flex rounded-full px-2 py-1 text-[10px] font-semibold ${asset.online_status === "online" ? "bg-emerald-50 text-emerald-700" : asset.online_status === "offline" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700"}`}
        >
          {labelOf(STATUS_LABELS, asset.online_status, zh)}
        </span>
      );
    if (key === "tags")
      return (
        <div className="flex max-w-[220px] flex-wrap gap-1">
          {asset.tags?.length ? (
            asset.tags.map((tag) => (
              <span
                key={tag.id}
                className="rounded-full px-2 py-1 text-[10px]"
                style={{
                  backgroundColor: `${tag.color || "#94a3b8"}18`,
                  color: tag.color || "#64748b",
                }}
              >
                {zh ? tag.label_zh || tag.label : tag.label}
              </span>
            ))
          ) : (
            <span className="text-slate-300">—</span>
          )}
        </div>
      );
    const values: Record<
      Exclude<ColumnKey, "asset" | "category" | "site" | "status" | "tags">,
      string | undefined
    > = {
      vendor: asset.vendor,
      model: asset.model,
      serial: asset.serial_number,
      management_ip: asset.management_ip,
      lifecycle: labelOf(LIFECYCLE_LABELS, asset.lifecycle_status, zh),
      created: formatDate(asset.created_at),
      updated: formatDate(asset.updated_at),
    };
    return (
      <span className="text-slate-600">
        {values[key as keyof typeof values] || "—"}
      </span>
    );
  };

  return (
    <div className="min-h-[calc(100vh-132px)] bg-slate-50/70 p-4 md:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700">
            <FolderTree size={15} /> CMDB / {zh ? "资产目录" : "Asset catalog"}
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">
            {zh ? "分层资产目录" : "Hierarchical asset catalog"}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {zh
              ? "按站点、资产类型、产品分类和设备角色逐级定位资产。"
              : "Browse assets by site, type, product category and physical asset role."}
          </p>
        </div>
        <button
          onClick={() => {
            void loadTree();
            void loadAssets();
          }}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-sm hover:border-cyan-300 hover:text-cyan-700"
        >
          <RefreshCw size={14} />
          {zh ? "刷新目录" : "Refresh catalog"}
        </button>
      </div>
      {error && (
        <div className="mb-4 flex items-center justify-between rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
          <span>{error}</span>
          <button onClick={() => setError("")}>
            <X size={14} />
          </button>
        </div>
      )}
      <div className={`grid items-stretch gap-4 ${treeCollapsed ? "xl:grid-cols-[56px_minmax(0,1fr)]" : "xl:grid-cols-[290px_minmax(0,1fr)]"}`}>
        <aside className={`min-h-[calc(100vh-250px)] rounded-2xl border border-slate-200 bg-white shadow-sm ${treeCollapsed ? "p-2" : "p-3"}`}>
          <div className={`mb-3 flex items-center border-b border-slate-100 pb-3 ${treeCollapsed ? "justify-center px-0" : "justify-between px-2"}`}>
            {!treeCollapsed && (
              <div>
                <div className="text-sm font-bold text-slate-800">
                  {zh ? "资产分类树" : "Asset tree"}
                </div>
                <div className="mt-0.5 text-[11px] text-slate-400">
                  {zh
                    ? "站点 → 类型 → 产品 → 角色"
                    : "Site → type → product → role"}
                </div>
              </div>
            )}
            <div className="flex items-center gap-1">
              {!treeCollapsed && treeLoading && (
                <RefreshCw size={14} className="animate-spin text-cyan-600" />
              )}
              <button
                type="button"
                onClick={() => setTreeCollapsed((current) => !current)}
                className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-cyan-50 hover:text-cyan-700"
                title={treeCollapsed ? (zh ? "展开资产分类树" : "Expand asset tree") : (zh ? "折叠资产分类树" : "Collapse asset tree")}
                aria-label={treeCollapsed ? (zh ? "展开资产分类树" : "Expand asset tree") : (zh ? "折叠资产分类树" : "Collapse asset tree")}
              >
                {treeCollapsed ? <FolderTree size={15} /> : <ChevronRight size={15} className="rotate-180" />}
              </button>
            </div>
          </div>
          {!treeCollapsed && (
            <div className="max-h-[calc(100vh-300px)] overflow-y-auto">
              {tree.length ? (
                tree.map((node) => renderNode(node))
              ) : (
                <div className="px-2 py-10 text-center text-xs text-slate-400">
                  {treeLoading ? "Loading…" : zh ? "暂无资产" : "No assets"}
                </div>
              )}
            </div>
          )}
        </aside>
        <section className="flex min-h-[calc(100vh-250px)] min-w-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="relative flex flex-wrap items-center gap-2 border-b border-slate-100 p-4">
            <div className="relative min-w-[220px] flex-1">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder={
                  zh
                    ? "搜索设备名、资产编号、IP、厂商…"
                    : "Search hostname, tag, IP or vendor…"
                }
                className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-cyan-400 focus:bg-white"
              />
            </div>
            <select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600"
            >
              <option value="all">
                {zh ? "全部在线状态" : "All statuses"}
              </option>
              <option value="online">在线</option>
              <option value="offline">离线</option>
              <option value="pending">待确认</option>
            </select>
            <TagFilterDropdown
              allTags={allTags}
              selectedTagIds={filterTagIds}
              onChange={(ids) => {
                setFilterTagIds(ids);
                setPage(1);
              }}
              language={language}
            />
            <div ref={columnsMenuRef} className="relative">
              <button
                onClick={() => setColumnsOpen((open) => !open)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 hover:border-cyan-300 hover:text-cyan-700"
              >
                <Settings2 size={13} />
                {zh ? "列配置" : "Columns"}
              </button>
              {columnsOpen && (
                <div className="absolute right-0 top-full z-40 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
                  <div className="mb-2 text-xs font-bold text-slate-700">
                    {zh ? "选择展示字段" : "Visible columns"}
                  </div>
                  <button
                    onClick={() =>
                      setVisibleColumns(
                        Object.fromEntries(
                          COLUMN_DEFS.map((column) => [column.key, true]),
                        ) as ColumnVisibility,
                      )
                    }
                    disabled={allColumnsSelected}
                    className="mb-2 w-full rounded-lg bg-cyan-50 px-2 py-1.5 text-left text-[11px] font-semibold text-cyan-700 disabled:cursor-default disabled:opacity-50"
                  >
                    {zh ? "一键全选" : "Select all"}
                  </button>
                  {COLUMN_DEFS.map((column) => (
                    <label
                      key={column.key}
                      className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                    >
                      <input
                        type="checkbox"
                        checked={visibleColumns[column.key]}
                        disabled={DEFAULT_COLUMNS[column.key]}
                        onChange={() => {
                          if (DEFAULT_COLUMNS[column.key]) return;
                          setVisibleColumns((current) => ({
                            ...current,
                            [column.key]: !current[column.key],
                          }));
                        }}
                      />
                      <span className="flex-1">
                        {zh ? column.zh : column.en}
                      </span>
                      {visibleColumns[column.key] && (
                        <Check size={13} className="text-cyan-600" />
                      )}
                    </label>
                  ))}
                  <button
                    onClick={() => setVisibleColumns(DEFAULT_COLUMNS)}
                    className="mt-2 w-full border-t border-slate-100 pt-2 text-left text-[11px] text-cyan-600"
                  >
                    {zh ? "恢复默认列" : "Reset columns"}
                  </button>
                </div>
              )}
            </div>
            <button
              onClick={() => void exportExcel()}
              className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 hover:bg-emerald-100"
            >
              <Download size={13} />
              {zh ? "导出 Excel" : "Export Excel"}
            </button>
            {canManageTags && (
              <button
                disabled={!selectedIds.length}
                onClick={() => setTagModalOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-cyan-600 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Tag size={13} />
                {zh ? "编辑标签" : "Edit tags"}
                {selectedIds.length ? ` (${selectedIds.length})` : ""}
              </button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2 text-[11px] text-slate-500">
            <Filter size={13} className="text-cyan-600" />
            <span>{zh ? "当前分支" : "Current branch"}:</span>
            <span className="rounded-full bg-cyan-50 px-2 py-1 text-cyan-700">
              {selectedLabel}
            </span>
            <span className="ml-auto">
              {total} {zh ? "条资产" : "assets"}
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            <DataTable className="min-w-[920px] text-left text-xs">
              <thead className="sticky top-0 z-10 bg-slate-50 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      checked={allPageSelected}
                      onChange={(event) =>
                        setSelectedIds(
                          event.target.checked
                            ? assets.map((asset) => asset.id)
                            : [],
                        )
                      }
                    />
                  </th>
                  {activeColumns.map((column) => (
                    <th
                      key={column.key}
                      className="whitespace-nowrap px-4 py-3"
                    >
                      {zh ? column.zh : column.en}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr>
                    <td
                      colSpan={activeColumns.length + 1}
                      className="py-14 text-center text-slate-400"
                    >
                      <RefreshCw
                        size={18}
                        className="mx-auto mb-2 animate-spin text-cyan-600"
                      />
                      {zh ? "加载资产中…" : "Loading assets…"}
                    </td>
                  </tr>
                ) : assets.length === 0 ? (
                  <tr>
                    <td
                      colSpan={activeColumns.length + 1}
                      className="py-14 text-center text-slate-400"
                    >
                      {zh ? "当前分类没有资产" : "No assets in this branch"}
                    </td>
                  </tr>
                ) : (
                  assets.map((asset) => (
                    <tr
                      key={asset.id}
                      className={`hover:bg-cyan-50/40 ${selectedIds.includes(asset.id) ? "bg-cyan-50/60" : ""}`}
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(asset.id)}
                          onChange={(event) =>
                            setSelectedIds((current) =>
                              event.target.checked
                                ? [...current, asset.id]
                                : current.filter((id) => id !== asset.id),
                            )
                          }
                        />
                      </td>
                      {activeColumns.map((column) => (
                        <td key={column.key} className="px-4 py-3 align-top">
                          {renderCell(asset, column.key)}
                        </td>
                      ))}
                    </tr>
                  ))
                )}
              </tbody>
            </DataTable>
          </div>
          <div className="hidden">
            <span>
              {total
                ? `${(page - 1) * pageSize + 1}-${Math.min(page * pageSize, total)} / ${total}`
                : "0"}
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((value) => value - 1)}
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 disabled:opacity-40"
              >
                ‹
              </button>
              <span>
                {page} / {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((value) => value + 1)}
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 disabled:opacity-40"
              >
                ›
              </button>
            </div>
          </div>
          <Pagination
            currentPage={page}
            totalItems={total}
            onPageChange={setPage}
            itemsPerPage={pageSize}
            onItemsPerPageChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
            language={language}
            alwaysVisible
          />
        </section>
      </div>
      <BatchTagModal
        isOpen={tagModalOpen}
        onClose={() => setTagModalOpen(false)}
        selectedCount={selectedIds.length}
        allTags={allTags}
        selectedTagIds={selectedTagIds}
        setSelectedTagIds={setSelectedTagIds}
        batchTag={() => {
          void batchTag();
        }}
        language={language}
      />
    </div>
  );
};

export default CmdbAssetManagementTab;
