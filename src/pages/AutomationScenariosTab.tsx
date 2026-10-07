import React, { useState, useMemo, useCallback } from 'react';
import {
  Play, Search, Star, ChevronDown, SlidersHorizontal,
  Plus, Eye, ArrowUpDown, Layers, Shield, X, FolderOpen,
} from 'lucide-react';
import PageHero from '../components/PageHero';
import { ActionButton, ActionIconButton, ActionIconGroup } from '../components/ui/ActionIconButton';

/* ─── Types ─── */
interface PlatformMeta { icon?: string; vendor?: string }

interface ScenarioPhaseCommands {
  pre_check?: string[];
  execute?: string[];
  post_check?: string[];
  rollback?: string[];
}

interface AutomationScenario {
  id: string;
  icon?: string;
  risk: 'low' | 'medium' | 'high';
  name: string;
  name_zh?: string;
  description: string;
  description_zh?: string;
  category: string;
  is_custom?: boolean;
  supported_platforms?: string[];
  default_platform?: string;
  platform_phases?: Record<string, ScenarioPhaseCommands>;
}

interface AutomationScenariosTabProps {
  t: (key: string) => string;
  language: string;
  scenarioSearch: string;
  filteredScenarios: AutomationScenario[];
  platforms: Record<string, PlatformMeta>;
  onScenarioSearchChange: (value: string) => void;
  onOpenManualScenarioDraft: () => void;
  onUseScenario: (scenario: AutomationScenario) => void;
}

/* ─── Constants ─── */
const RISK_CFG = {
  high:   { label: 'HIGH',   dotCls: 'bg-red-500',     badgeBg: 'bg-red-500/10 dark:bg-red-500/20',     badgeText: 'text-red-600 dark:text-red-400',     border: 'border-l-red-500' },
  medium: { label: 'MEDIUM', dotCls: 'bg-amber-500',   badgeBg: 'bg-amber-500/10 dark:bg-amber-500/20', badgeText: 'text-amber-600 dark:text-amber-400', border: 'border-l-amber-500' },
  low:    { label: 'LOW',    dotCls: 'bg-emerald-500', badgeBg: 'bg-emerald-500/10 dark:bg-emerald-500/20', badgeText: 'text-emerald-600 dark:text-emerald-400', border: 'border-l-emerald-500' },
} as const;

type SortKey = 'risk' | 'name' | 'category';
const MAX_VISIBLE_PLATFORMS = 3;

/* ─── Helpers ─── */
function totalSteps(phases?: ScenarioPhaseCommands): number {
  if (!phases) return 0;
  return (phases.pre_check?.length || 0) + (phases.execute?.length || 0) +
    (phases.post_check?.length || 0) + (phases.rollback?.length || 0);
}

const HighlightText: React.FC<{ text: string; keyword: string }> = ({ text, keyword }) => {
  if (!keyword.trim()) return <>{text}</>;
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === keyword.toLowerCase()
          ? <mark key={i} className="bg-[#00bceb]/20 text-inherit rounded-sm px-0.5">{part}</mark>
          : part
      )}
    </>
  );
};

/* ─── Filter Chip ─── */
const FilterChip: React.FC<{
  label: string; active: boolean; onClick: () => void; dot?: string;
}> = ({ label, active, onClick, dot }) => (
  <button
    onClick={onClick}
    className={`
      inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-medium transition-all
      border cursor-pointer select-none whitespace-nowrap
      ${active
        ? 'bg-[#00bceb]/10 border-[#00bceb]/30 text-[#00899e] dark:text-[#5dd8f0] dark:bg-[#00bceb]/15 dark:border-[#00bceb]/25'
        : 'bg-transparent border-black/8 text-black/50 hover:border-black/15 hover:text-black/70 dark:border-white/10 dark:text-white/40 dark:hover:border-white/20 dark:hover:text-white/60'
      }
    `}
  >
    {dot && <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />}
    {label}
  </button>
);

/* ─── Main Component ─── */
const AutomationScenariosTab: React.FC<AutomationScenariosTabProps> = ({
  t, language, scenarioSearch, filteredScenarios, platforms,
  onScenarioSearchChange, onOpenManualScenarioDraft, onUseScenario,
}) => {
  const [riskFilter, setRiskFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');
  const [vendorFilter, setVendorFilter] = useState<string>('all');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [sortKey, setSortKey] = useState<SortKey>('risk');
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [favorites, setFavorites] = useState<Set<string>>(() => {
    try {
      const val = JSON.parse(localStorage.getItem('netops_scenario_favs') || '[]');
      return new Set(Array.isArray(val) ? val : []);
    } catch {
      return new Set();
    }
  });
  const [showFilters, setShowFilters] = useState(false);

  /* derived lists for filter options */
  const allVendors = useMemo(() => {
    const set = new Set<string>();
    filteredScenarios.forEach(s =>
      (s.supported_platforms || []).forEach(pk => {
        const v = platforms[pk]?.vendor;
        if (v) set.add(v);
      })
    );
    return Array.from(set).sort();
  }, [filteredScenarios, platforms]);

  const allCategories = useMemo(() => {
    const set = new Set<string>();
    filteredScenarios.forEach(s => set.add(s.category));
    return Array.from(set).sort();
  }, [filteredScenarios]);

  /* filter + sort pipeline */
  const processed = useMemo(() => {
    let list = [...filteredScenarios];
    if (riskFilter !== 'all') list = list.filter(s => s.risk === riskFilter);
    if (vendorFilter !== 'all') list = list.filter(s =>
      (s.supported_platforms || []).some(pk => platforms[pk]?.vendor === vendorFilter)
    );
    if (categoryFilter !== 'all') list = list.filter(s => s.category === categoryFilter);

    const riskOrder: Record<string, number> = { high: 0, medium: 1, low: 2 };
    list.sort((a, b) => {
      // favorites first
      const fa = favorites.has(a.id) ? 0 : 1;
      const fb = favorites.has(b.id) ? 0 : 1;
      if (fa !== fb) return fa - fb;
      if (sortKey === 'risk') return (riskOrder[a.risk] ?? 9) - (riskOrder[b.risk] ?? 9);
      if (sortKey === 'name') {
        const na = (language === 'zh' ? a.name_zh : a.name) || a.name;
        const nb = (language === 'zh' ? b.name_zh : b.name) || b.name;
        return na.localeCompare(nb);
      }
      return a.category.localeCompare(b.category);
    });
    return list;
  }, [filteredScenarios, riskFilter, vendorFilter, categoryFilter, sortKey, favorites, platforms, language]);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const toggleFavorite = useCallback((id: string) => {
    setFavorites(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      localStorage.setItem('netops_scenario_favs', JSON.stringify([...next]));
      return next;
    });
  }, []);

  const hasActiveFilter = riskFilter !== 'all' || vendorFilter !== 'all' || categoryFilter !== 'all';

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <PageHero
        icon={FolderOpen}
        title={t('scenarioLibrary')}
        subtitle={t('scenarioLibraryDesc')}
        actions={
          <>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30 dark:text-white/30 pointer-events-none" size={13} />
              <input
                value={scenarioSearch}
                onChange={e => onScenarioSearchChange(e.target.value)}
                placeholder={language === 'zh' ? '搜索场景关键词…' : 'Search scenarios…'}
                className="pl-8 pr-3 py-1.5 text-xs border border-black/10 dark:border-white/10 rounded-lg
                  bg-transparent outline-none focus:border-[#00bceb]/40 dark:focus:border-[#00bceb]/40
                  text-black/80 dark:text-white/80 placeholder:text-black/30 dark:placeholder:text-white/25 w-56"
              />
            </div>
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`p-1.5 rounded-lg border transition-all ${
                showFilters || hasActiveFilter
                  ? 'border-[#00bceb]/30 text-[#00bceb] bg-[#00bceb]/5'
                  : 'border-black/10 dark:border-white/10 text-black/40 dark:text-white/40 hover:text-black/60 dark:hover:text-white/60'
              }`}
              title={language === 'zh' ? '筛选' : 'Filters'}
            >
              <SlidersHorizontal size={14} />
            </button>
            <button
              onClick={onOpenManualScenarioDraft}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-[#00bceb] text-white rounded-lg text-xs
                font-medium hover:bg-[#0096bd] transition-all shadow-sm shadow-[#00bceb]/20"
            >
              <Plus size={12} /> {language === 'zh' ? '自定义场景' : 'Custom'}
            </button>
          </>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 scenario-library-scroll">

      {/* ── Filter Bar ── */}
      {showFilters && (
        <div className="mb-4 p-3 rounded-lg border border-black/6 dark:border-white/8 bg-black/[.02] dark:bg-white/[.02] space-y-2.5">
          {/* Risk */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-black/35 dark:text-white/30 w-14 shrink-0">
              <Shield size={10} className="inline mr-1 -mt-0.5" />{language === 'zh' ? '风险' : 'Risk'}
            </span>
            {(['all', 'high', 'medium', 'low'] as const).map(r => (
              <FilterChip
                key={r}
                label={r === 'all' ? (language === 'zh' ? '全部' : 'All') : RISK_CFG[r].label}
                active={riskFilter === r}
                onClick={() => setRiskFilter(r)}
                dot={r !== 'all' ? RISK_CFG[r].dotCls : undefined}
              />
            ))}
          </div>
          {/* Vendor */}
          {allVendors.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-black/35 dark:text-white/30 w-14 shrink-0">
                <Layers size={10} className="inline mr-1 -mt-0.5" />{language === 'zh' ? '厂商' : 'Vendor'}
              </span>
              <FilterChip label={language === 'zh' ? '全部' : 'All'} active={vendorFilter === 'all'} onClick={() => setVendorFilter('all')} />
              {allVendors.map(v => (
                <FilterChip key={v} label={v} active={vendorFilter === v} onClick={() => setVendorFilter(v)} />
              ))}
            </div>
          )}
          {/* Category */}
          {allCategories.length > 1 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-black/35 dark:text-white/30 w-14 shrink-0">
                <ArrowUpDown size={10} className="inline mr-1 -mt-0.5" />{language === 'zh' ? '分类' : 'Type'}
              </span>
              <FilterChip label={language === 'zh' ? '全部' : 'All'} active={categoryFilter === 'all'} onClick={() => setCategoryFilter('all')} />
              {allCategories.map(c => (
                <FilterChip key={c} label={c} active={categoryFilter === c} onClick={() => setCategoryFilter(c)} />
              ))}
            </div>
          )}
          {/* Sort */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-black/35 dark:text-white/30 w-14 shrink-0">
              <ArrowUpDown size={10} className="inline mr-1 -mt-0.5" />{language === 'zh' ? '排序' : 'Sort'}
            </span>
            {([['risk', '风险', 'Risk'], ['name', '名称', 'Name'], ['category', '分类', 'Category']] as [SortKey, string, string][]).map(([k, zh, en]) => (
              <FilterChip key={k} label={language === 'zh' ? zh : en} active={sortKey === k} onClick={() => setSortKey(k)} />
            ))}
          </div>
          {hasActiveFilter && (
            <button
              onClick={() => { setRiskFilter('all'); setVendorFilter('all'); setCategoryFilter('all'); }}
              className="text-[10px] text-[#00bceb] hover:underline inline-flex items-center gap-0.5"
            >
              <X size={10} /> {language === 'zh' ? '清除筛选' : 'Clear filters'}
            </button>
          )}
        </div>
      )}

      {/* ── Stats Bar ── */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] text-black/35 dark:text-white/30">
          {processed.length} {language === 'zh' ? '个场景' : 'scenarios'}
          {hasActiveFilter && <span className="ml-1 text-[#00bceb]">({language === 'zh' ? '已筛选' : 'filtered'})</span>}
        </span>
      </div>

      {/* ── Card Grid ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {processed.map((scenario) => {
          const risk = RISK_CFG[scenario.risk];
          const expanded = expandedIds.has(scenario.id);
          const isFav = favorites.has(scenario.id);
          const name = (language === 'zh' ? scenario.name_zh : scenario.name) || scenario.name;
          const desc = (language === 'zh' ? scenario.description_zh : scenario.description) || scenario.description;
          const defaultPlatform = scenario.default_platform || scenario.supported_platforms?.[0];
          const platformPhases = defaultPlatform ? scenario.platform_phases?.[defaultPlatform] : undefined;
          const steps = totalSteps(platformPhases);
          const visiblePlatforms = (scenario.supported_platforms || []).slice(0, MAX_VISIBLE_PLATFORMS);
          const hiddenCount = (scenario.supported_platforms?.length || 0) - visiblePlatforms.length;

          return (
            <div
              key={scenario.id}
              className={`
                group relative rounded-xl border-l-[3px] ${risk.border}
                border border-l-[3px] border-black/6 dark:border-white/8
                bg-[var(--card-bg)] hover:shadow-md dark:hover:shadow-black/30
                hover:-translate-y-0.5 transition-all duration-200 ease-out
              `}
            >
              {/* Layer 1: Title + Risk */}
              <div className="flex items-start gap-3 px-4 pt-4 pb-2">
                <span className="text-2xl leading-none shrink-0 mt-0.5">{scenario.icon || '📦'}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className="text-[13px] font-semibold truncate text-black/85 dark:text-white/90">
                      <HighlightText text={name} keyword={scenarioSearch} />
                    </h3>
                    <span className={`shrink-0 inline-flex items-center gap-1 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${risk.badgeBg} ${risk.badgeText}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${risk.dotCls}`} />
                      {risk.label}
                    </span>
                  </div>
                  {/* tags row */}
                  <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                    <span className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded bg-black/5 dark:bg-white/8 text-black/40 dark:text-white/40">
                      {scenario.category}
                    </span>
                    {scenario.is_custom && (
                      <span className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded bg-[#00bceb]/10 text-[#008bb0] dark:text-[#5dd8f0]">
                        Custom
                      </span>
                    )}
                    {visiblePlatforms.map(pk => {
                      const p = platforms[pk];
                      return (
                        <span key={pk} className="text-[9px] px-1.5 py-0.5 rounded bg-black/[.04] dark:bg-white/6 text-black/35 dark:text-white/35">
                          {p ? `${p.icon || ''} ${p.vendor}` : pk}
                        </span>
                      );
                    })}
                    {hiddenCount > 0 && (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-black/[.04] dark:bg-white/6 text-black/30 dark:text-white/30">
                        +{hiddenCount}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Layer 2: Description */}
              <div className="px-4 pb-2">
                <p className="text-[11px] leading-relaxed text-black/45 dark:text-white/45 line-clamp-2">
                  <HighlightText text={desc} keyword={scenarioSearch} />
                </p>
              </div>

              {/* Layer 3: Expandable Details + Actions */}
              <div className="px-4 pb-3">
                {/* steps summary & expand toggle */}
                <button
                  onClick={() => toggleExpand(scenario.id)}
                  className="w-full flex items-center justify-between py-1.5 text-[10px] text-black/35 dark:text-white/35
                    hover:text-black/55 dark:hover:text-white/55 transition-colors"
                >
                  <span className="inline-flex items-center gap-1.5">
                    <Layers size={10} />
                    {steps > 0
                      ? `${steps} ${language === 'zh' ? '步骤' : 'steps'} · ${scenario.supported_platforms?.length || 0} ${language === 'zh' ? '平台' : 'platforms'}`
                      : `${scenario.supported_platforms?.length || 0} ${language === 'zh' ? '平台' : 'platforms'}`
                    }
                  </span>
                  <ChevronDown size={11} className={`transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
                </button>

                {/* expanded phase detail */}
                {expanded && platformPhases && (
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 pt-1 pb-2 text-[10px] text-black/40 dark:text-white/40 border-t border-black/5 dark:border-white/8">
                    {[
                      ['📋', 'Pre-Check', platformPhases.pre_check],
                      ['⚡', 'Execute', platformPhases.execute],
                      ['✅', 'Post-Check', platformPhases.post_check],
                      ['↩️', 'Rollback', platformPhases.rollback],
                    ].map(([icon, label, cmds]) => (
                      <div key={label as string} className="flex items-center gap-1">
                        <span>{icon as string}</span>
                        <span>{label as string}:</span>
                        <span className="font-medium text-black/55 dark:text-white/55">{(cmds as string[] | undefined)?.length || 0}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* actions */}
                <ActionIconGroup label={language === 'zh' ? '场景操作' : 'Scenario actions'} className="w-full mt-1">
                  <ActionButton
                    icon={Play}
                    variant="primary"
                    onClick={() => onUseScenario(scenario)}
                    className="flex-1"
                  >
                    {t('useScenario')}
                  </ActionButton>
                  <ActionIconButton
                    icon={Eye}
                    label={t('previewCommands')}
                    variant="accent"
                    onClick={() => onUseScenario(scenario)}
                  />
                  <ActionIconButton
                    icon={Star}
                    label={language === 'zh' ? '收藏' : 'Favorite'}
                    variant={isFav ? 'accent' : 'default'}
                    onClick={() => toggleFavorite(scenario.id)}
                    iconClassName={isFav ? 'fill-current' : undefined}
                  />
                </ActionIconGroup>
              </div>
            </div>
          );
        })}
      </div>

      {/* empty state */}
      {processed.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-black/25 dark:text-white/25">
          <Search size={32} className="mb-3 opacity-40" />
          <p className="text-sm">{language === 'zh' ? '没有匹配的场景' : 'No matching scenarios'}</p>
          {hasActiveFilter && (
            <button
              onClick={() => { setRiskFilter('all'); setVendorFilter('all'); setCategoryFilter('all'); }}
              className="mt-2 text-xs text-[#00bceb] hover:underline"
            >
              {language === 'zh' ? '清除筛选条件' : 'Clear all filters'}
            </button>
          )}
        </div>
      )}
      </div>
    </div>
  );
};

export default AutomationScenariosTab;
