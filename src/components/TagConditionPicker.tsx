import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Ban, Brackets, Layers, Plus, Search, Tag, X } from 'lucide-react';
import type { TagCategory, TagDefinition } from '../types';
import { TAG_CATEGORY_LABELS } from '../types';

export type TagBooleanOperator = 'and' | 'or';

export interface TagExpressionGroup {
  operator: TagBooleanOperator;
  negated: boolean;
  tag_ids: string[];
  groups: TagExpressionGroup[];
}

interface LegacyTagConditionGroup {
  tag_ids: string[];
  operator?: 'and' | 'or' | 'not';
}

export interface TagFilterConfig {
  expression: TagExpressionGroup;
  /** Kept for callers that still hold an old in-memory filter. */
  groups: LegacyTagConditionGroup[];
  /** Kept for callers that still hold an old in-memory filter. */
  exclude_tag_ids: string[];
}

const emptyExpression = (): TagExpressionGroup => ({
  operator: 'and',
  negated: false,
  tag_ids: [],
  groups: [],
});

export const EMPTY_TAG_FILTER: TagFilterConfig = {
  expression: emptyExpression(),
  groups: [],
  exclude_tag_ids: [],
};

const uniqueIds = (values: unknown): string[] => (
  Array.isArray(values)
    ? Array.from(new Set(values.map(value => String(value || '').trim()).filter(Boolean)))
    : []
);

const normalizeExpression = (raw: unknown, depth = 0): TagExpressionGroup => {
  if (!raw || typeof raw !== 'object' || depth > 12) return emptyExpression();
  const value = raw as Record<string, unknown>;
  return {
    operator: value.operator === 'or' ? 'or' : 'and',
    negated: value.negated === true,
    tag_ids: uniqueIds(value.tag_ids),
    groups: Array.isArray(value.groups)
      ? value.groups.map(group => normalizeExpression(group, depth + 1))
      : [],
  };
};

const legacyConfigToExpression = (raw: Record<string, unknown>): TagExpressionGroup => {
  const root = emptyExpression();
  const oldGroups = Array.isArray(raw.groups) ? raw.groups as Array<Record<string, unknown>> : [];
  const orTagIds: string[] = [];

  oldGroups.forEach(group => {
    const tagIds = uniqueIds(group.tag_ids);
    if (tagIds.length === 0) return;
    const operator = group.operator === 'or' || group.operator === 'not' ? group.operator : 'and';
    if (operator === 'or') {
      orTagIds.push(...tagIds);
      return;
    }
    root.groups.push({
      operator: 'or',
      negated: operator === 'not',
      tag_ids: tagIds,
      groups: [],
    });
  });

  if (orTagIds.length > 0) {
    root.groups.push({
      operator: 'or',
      negated: false,
      tag_ids: uniqueIds(orTagIds),
      groups: [],
    });
  }

  const oldTagIds = uniqueIds(raw.tag_ids);
  if (oldTagIds.length > 0) {
    root.groups.push({
      operator: raw.match_mode === 'or' ? 'or' : 'and',
      negated: false,
      tag_ids: oldTagIds,
      groups: [],
    });
  }

  const excluded = uniqueIds(raw.exclude_tag_ids);
  if (excluded.length > 0) {
    root.groups.push({
      operator: 'or',
      negated: true,
      tag_ids: excluded,
      groups: [],
    });
  }
  return root;
};

export const parseTagFilter = (raw: string): TagFilterConfig => {
  try {
    const value = JSON.parse(raw) as Record<string, unknown>;
    const expression = value.expression
      ? normalizeExpression(value.expression)
      : legacyConfigToExpression(value);
    return { expression, groups: [], exclude_tag_ids: [] };
  } catch {
    return { expression: emptyExpression(), groups: [], exclude_tag_ids: [] };
  }
};

export const serializeTagFilter = (config: TagFilterConfig): string => {
  const expression = config.expression
    ? normalizeExpression(config.expression)
    : legacyConfigToExpression(config as unknown as Record<string, unknown>);
  return JSON.stringify({
    version: 2,
    expression,
    groups: [],
    exclude_tag_ids: [],
  });
};

export const countTagFilterConditions = (config: TagFilterConfig): number => {
  const countGroup = (group: TagExpressionGroup): number => (
    group.tag_ids.length + group.groups.reduce((total, child) => total + countGroup(child), 0)
  );
  return countGroup(config.expression) + config.groups.reduce(
    (total, group) => total + group.tag_ids.length,
    0,
  ) + config.exclude_tag_ids.length;
};

export const hasTagFilterConditions = (config: TagFilterConfig): boolean => (
  countTagFilterConditions(config) > 0
);

interface TagDropdownProps {
  allTags: TagDefinition[];
  excludeIds: Set<string>;
  onSelect: (tagId: string) => void;
  language: string;
}

const TagDropdown: React.FC<TagDropdownProps> = ({
  allTags,
  excludeIds,
  onSelect,
  language,
}) => {
  const zh = language === 'zh';
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const filtered = useMemo(() => {
    const available = allTags.filter(tag => !excludeIds.has(tag.id));
    const query = search.trim().toLowerCase();
    if (!query) return available;
    return available.filter(tag => [
      tag.label,
      tag.label_zh,
      tag.code,
      tag.category,
      tag.description,
    ].some(value => String(value || '').toLowerCase().includes(query)));
  }, [allTags, excludeIds, search]);

  const grouped = useMemo(() => {
    const result: Record<string, TagDefinition[]> = {};
    filtered.forEach(tag => {
      const category = String(tag.category || 'other');
      if (!result[category]) result[category] = [];
      result[category].push(tag);
    });
    return result;
  }, [filtered]);

  return (
    <div ref={ref} className="relative">
      <div className="flex items-center gap-2 rounded-lg border border-black/[0.06] bg-white px-2.5 py-1.5">
        <button
          type="button"
          onClick={() => {
            setOpen(true);
            inputRef.current?.focus();
          }}
          title={zh ? '添加一个标签条件' : 'Add a tag condition'}
          aria-label={zh ? '添加一个标签条件' : 'Add a tag condition'}
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-cyan-50 text-cyan-600 transition-colors hover:bg-cyan-100"
        >
          <Plus size={12} />
        </button>
        <Search size={12} className="shrink-0 text-black/20" />
        <input
          ref={inputRef}
          type="search"
          value={search}
          onFocus={() => setOpen(true)}
          onChange={event => {
            setSearch(event.target.value);
            setOpen(true);
          }}
          placeholder={zh ? '添加条件：搜索标签名称、编码或分类…' : 'Add condition: search tag name, code, or category…'}
          className="min-w-0 flex-1 bg-transparent text-[11px] text-black/70 outline-none placeholder:text-black/20"
        />
        {search && (
          <button type="button" onClick={() => setSearch('')} className="text-black/20 hover:text-black/50">
            <X size={11} />
          </button>
        )}
      </div>
      {open && (
        <div className="absolute z-40 mt-1 max-h-56 w-full min-w-[250px] overflow-y-auto rounded-lg border border-black/8 bg-white shadow-xl">
          {filtered.length === 0 ? (
            <div className="px-3 py-4 text-center text-[10px] text-black/30">
              {zh ? '没有匹配的可用标签' : 'No matching tags'}
            </div>
          ) : (
            Object.entries(grouped).map(([category, tags]) => {
              const labels = TAG_CATEGORY_LABELS[category as TagCategory];
              return (
                <div key={category}>
                  <div className="sticky top-0 bg-slate-50 px-2.5 py-1 text-[9px] font-bold text-black/35">
                    {labels ? (zh ? labels.zh : labels.en) : category}
                  </div>
                  {tags.map(tag => (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() => {
                        onSelect(tag.id);
                        setSearch('');
                        setOpen(false);
                      }}
                      className="flex w-full items-center gap-2 px-2.5 py-2 text-left hover:bg-cyan-50/60"
                    >
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: tag.color || '#94a3b8' }} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[11px] text-black/70">
                          {zh ? (tag.label_zh || tag.label) : tag.label}
                        </span>
                        <span className="block truncate text-[9px] text-black/35">
                          {[zh ? tag.label : tag.label_zh, tag.code]
                            .filter((item, index, items) => item && items.indexOf(item) === index)
                            .join(' · ')}
                        </span>
                      </span>
                      {tag.built_in === 0 && (
                        <span className="rounded bg-violet-50 px-1 py-0.5 text-[8px] font-semibold text-violet-600">
                          {zh ? '自定义' : 'Custom'}
                        </span>
                      )}
                      <span className={`text-[9px] ${Number(tag.assignment_count || 0) > 0 ? 'text-black/30' : 'text-amber-500'}`}>
                        {zh ? `${Number(tag.assignment_count || 0)} 台` : `${Number(tag.assignment_count || 0)} devices`}
                      </span>
                      <span className="truncate text-[9px] text-black/25">{tag.code}</span>
                    </button>
                  ))}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
};

interface TagConditionPickerProps {
  value: TagFilterConfig;
  onChange: (value: TagFilterConfig) => void;
  language: string;
  tagDefinitions?: TagDefinition[];
}

type GroupPath = number[];

const updateGroupAtPath = (
  root: TagExpressionGroup,
  path: GroupPath,
  updater: (group: TagExpressionGroup) => TagExpressionGroup,
): TagExpressionGroup => {
  if (path.length === 0) return updater(root);
  const [index, ...rest] = path;
  return {
    ...root,
    groups: root.groups.map((group, groupIndex) => (
      groupIndex === index ? updateGroupAtPath(group, rest, updater) : group
    )),
  };
};

const collectTagIds = (group: TagExpressionGroup, output = new Set<string>()): Set<string> => {
  group.tag_ids.forEach(tagId => output.add(tagId));
  group.groups.forEach(child => collectTagIds(child, output));
  return output;
};

const TagConditionPicker: React.FC<TagConditionPickerProps> = ({
  value,
  onChange,
  language,
  tagDefinitions,
}) => {
  const zh = language === 'zh';
  const expression = value.expression || emptyExpression();
  const [allTags, setAllTags] = useState<TagDefinition[]>([]);

  useEffect(() => {
    if (tagDefinitions) {
      setAllTags(tagDefinitions.filter(tag => Number(tag.is_active ?? 1) !== 0));
      return;
    }
    const controller = new AbortController();
    const token = localStorage.getItem('netops_token');
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
    fetch('/api/tags/definitions', { headers, signal: controller.signal })
      .then(response => response.ok ? response.json() : Promise.reject(new Error('Failed to load tags')))
      .then(payload => {
        const definitions = (Array.isArray(payload) ? payload : (payload.data ?? [])) as TagDefinition[];
        setAllTags(definitions.filter(tag => Number(tag.is_active ?? 1) !== 0));
      })
      .catch(() => {});
    return () => controller.abort();
  }, [tagDefinitions]);

  const tagMap = useMemo(() => new Map(allTags.map(tag => [tag.id, tag])), [allTags]);
  const usedTagIds = useMemo(() => collectTagIds(expression), [expression]);

  const commitExpression = (nextExpression: TagExpressionGroup) => {
    onChange({
      expression: nextExpression,
      groups: [],
      exclude_tag_ids: [],
    });
  };

  const updateGroup = (path: GroupPath, updater: (group: TagExpressionGroup) => TagExpressionGroup) => {
    commitExpression(updateGroupAtPath(expression, path, updater));
  };

  const removeGroup = (path: GroupPath) => {
    const parentPath = path.slice(0, -1);
    const childIndex = path[path.length - 1];
    updateGroup(parentPath, group => ({
      ...group,
      groups: group.groups.filter((_, index) => index !== childIndex),
    }));
  };

  const addNestedGroup = (path: GroupPath, operator: TagBooleanOperator, negated = false) => {
    updateGroup(path, group => ({
      ...group,
      groups: [
        ...group.groups,
        { operator, negated, tag_ids: [], groups: [] },
      ],
    }));
  };

  const formatExpression = (group: TagExpressionGroup, root = false): string => {
    const directTerms = group.tag_ids.map(tagId => {
      const tag = tagMap.get(tagId);
      return tag ? (zh ? (tag.label_zh || tag.label) : tag.label) : tagId;
    });
    const nestedTerms = group.groups.map(child => formatExpression(child));
    const terms = [...directTerms, ...nestedTerms].filter(Boolean);
    if (terms.length === 0) return '';
    const separator = group.operator === 'and' ? ' AND ' : ' OR ';
    const combined = terms.join(separator);
    const wrapped = root || terms.length === 1 ? combined : `(${combined})`;
    return group.negated ? `NOT ${wrapped}` : wrapped;
  };

  const expressionPreview = formatExpression(expression, true);
  const totalConditions = countTagFilterConditions(value);

  const renderTagChip = (tagId: string, path: GroupPath) => {
    const tag = tagMap.get(tagId);
    const label = tag ? (zh ? (tag.label_zh || tag.label) : tag.label) : tagId;
    return (
      <span
        key={tagId}
        title={tag ? [tag.label_zh, tag.label, tag.code].filter(Boolean).join(' / ') : tagId}
        className="inline-flex items-center gap-1 rounded-lg border border-cyan-200/60 bg-cyan-50 px-2 py-0.5 text-[11px] font-medium text-cyan-800"
      >
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: tag?.color || '#06b6d4' }} />
        {label}
        <button
          type="button"
          onClick={() => updateGroup(path, group => ({
            ...group,
            tag_ids: group.tag_ids.filter(id => id !== tagId),
          }))}
          className="ml-0.5 text-cyan-400 hover:text-red-400"
        >
          <X size={10} />
        </button>
      </span>
    );
  };

  const renderGroup = (group: TagExpressionGroup, path: GroupPath, depth: number): React.ReactNode => {
    const root = path.length === 0;
    const connector = group.operator.toUpperCase();
    const groupName = root
      ? (zh ? '根条件组' : 'Root condition group')
      : (zh ? `子条件组 ${path.map(index => index + 1).join('.')}` : `Child group ${path.map(index => index + 1).join('.')}`);
    return (
      <div
        key={root ? 'root' : path.join('.')}
        className={`space-y-2 rounded-xl border p-2.5 ${
          group.negated
            ? 'border-red-200 bg-red-50/35'
            : root
              ? 'border-cyan-200/70 bg-cyan-50/20'
              : 'border-black/[0.07] bg-white'
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
            <Brackets size={12} className={group.negated ? 'text-red-400' : 'text-cyan-500'} />
            <span className="text-[10px] font-bold text-black/55">{groupName}</span>
            <span className={`rounded-md px-1.5 py-0.5 text-[9px] font-bold ${group.negated ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-600'}`}>
              {group.negated ? 'NOT ' : ''}{connector}
            </span>
            <select
              value={group.operator}
              onChange={event => updateGroup(path, current => ({
                ...current,
                operator: event.target.value as TagBooleanOperator,
              }))}
              className="rounded-md border border-black/10 bg-white px-1.5 py-1 text-[10px] font-bold text-slate-600 outline-none"
              aria-label={zh ? '组内运算符' : 'Group operator'}
            >
              <option value="and">AND</option>
              <option value="or">OR</option>
            </select>
            <button
              type="button"
              onClick={() => updateGroup(path, current => ({ ...current, negated: !current.negated }))}
              className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-1 text-[10px] font-bold ${
                group.negated
                  ? 'border-red-300 bg-red-100 text-red-700'
                  : 'border-black/10 bg-white text-black/35 hover:border-red-200 hover:text-red-500'
              }`}
            >
              <Ban size={10} />NOT
            </button>
            </div>
            <p className="mt-1 text-[9px] text-black/35">
              {group.negated
                ? (zh ? '排除满足本组条件的设备' : 'Exclude devices matching this group')
                : group.operator === 'and'
                  ? (zh ? '本组需要满足全部条件' : 'All items in this group must match')
                  : (zh ? '本组满足任一条件即可' : 'Any item in this group may match')}
            </p>
          </div>
          {!root && (
            <button type="button" onClick={() => removeGroup(path)} className="text-black/20 hover:text-red-500">
              <X size={12} />
            </button>
          )}
        </div>

        {group.tag_ids.length > 0 && (
          <div>
            <div className="mb-1 text-[9px] font-semibold text-black/35">{zh ? `本组标签（${connector}）` : `Tags in this group (${connector})`}</div>
            <div className="flex flex-wrap items-center gap-1.5">
            {group.tag_ids.map((tagId, index) => (
              <React.Fragment key={tagId}>
                {index > 0 && <span className="text-[9px] font-bold text-black/30">{connector}</span>}
                {renderTagChip(tagId, path)}
              </React.Fragment>
            ))}
            </div>
          </div>
        )}

        {group.groups.map((child, index) => (
          <React.Fragment key={`${path.join('.')}-${index}`}>
            {index === 0 && <div className="text-[9px] font-semibold text-black/35">{zh ? `子条件组（与本组使用 ${connector} 连接）` : `Child groups (joined with ${connector})`}</div>}
            <div className="flex items-center gap-2 py-0.5">
              <div className="flex-1 border-t border-dashed border-black/10" />
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-black/40">{connector}</span>
              <div className="flex-1 border-t border-dashed border-black/10" />
            </div>
            <div className="ml-3 border-l border-cyan-200/60 pl-3">
              {renderGroup(child, [...path, index], depth + 1)}
            </div>
          </React.Fragment>
        ))}

        <TagDropdown
          allTags={allTags}
          excludeIds={usedTagIds}
          onSelect={tagId => updateGroup(path, current => ({
            ...current,
            tag_ids: [...current.tag_ids, tagId],
          }))}
          language={language}
        />

        {depth < 6 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <button type="button" onClick={() => addNestedGroup(path, 'and')} className="inline-flex items-center gap-1 rounded-md border border-dashed border-cyan-200 px-2 py-1 text-[10px] font-semibold text-cyan-600 hover:bg-cyan-50">
              <Plus size={10} />{zh ? '添加子组 · AND' : 'Add child group · AND'}
            </button>
            <button type="button" onClick={() => addNestedGroup(path, 'or')} className="inline-flex items-center gap-1 rounded-md border border-dashed border-amber-200 px-2 py-1 text-[10px] font-semibold text-amber-600 hover:bg-amber-50">
              <Plus size={10} />{zh ? '添加子组 · OR' : 'Add child group · OR'}
            </button>
            <button type="button" onClick={() => addNestedGroup(path, 'or', true)} className="inline-flex items-center gap-1 rounded-md border border-dashed border-red-200 px-2 py-1 text-[10px] font-semibold text-red-500 hover:bg-red-50">
              <Ban size={10} />{zh ? '添加子组 · NOT' : 'Add child group · NOT'}
            </button>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between text-[10px] text-black/35">
        <span className="inline-flex items-center gap-1"><Tag size={10} />{zh ? `已加载 ${allTags.length} 个启用标签` : `${allTags.length} active tags loaded`}</span>
        <span>{zh ? `${totalConditions} 个标签条件` : `${totalConditions} tag conditions`}</span>
      </div>
      <div className="rounded-lg border border-cyan-200/60 bg-[#f0fdfa] px-3 py-2">
        <div className="mb-1 flex items-center gap-2 text-[10px] font-bold text-cyan-700">
          <Layers size={12} className="mt-0.5 shrink-0 text-cyan-500" />
          <span>{zh ? '最终匹配规则' : 'Final matching rule'}</span>
        </div>
        <p className="break-all rounded-md bg-white/70 px-2 py-1.5 font-mono text-[11px] font-semibold leading-relaxed text-[#164e63]">
          {expressionPreview || (zh ? '尚未添加条件' : 'No conditions added yet')}
        </p>
        <p className="mt-1 text-[9px] text-cyan-700/60">
          {zh ? '括号表示子条件组；AND=全部满足，OR=任一满足，NOT=排除。' : 'Parentheses indicate child groups; AND means all, OR means any, NOT excludes.'}
        </p>
      </div>
      {renderGroup(expression, [], 0)}
      {totalConditions === 0 && (
        <p className="text-[10px] leading-relaxed text-black/30">
          {zh
            ? '可直接在根组添加标签，也可以创建嵌套 AND、OR、NOT 条件组。例如：A AND B AND (C OR D)。'
            : 'Add tags to the root or create nested AND, OR, and NOT groups, for example A AND B AND (C OR D).'}
        </p>
      )}
    </div>
  );
};

export default TagConditionPicker;
