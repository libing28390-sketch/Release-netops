import React from 'react';
import { motion } from 'motion/react';
import { Search, ChevronLeft, Server, Zap } from 'lucide-react';
import type { Device } from '../../../types';
import type { AutomationScenario, StepId } from '../types';
import { CATEGORY_META, RISK_CONFIG } from '../constants';
import { getVendor } from '../helpers';

interface ScenarioSelectionStepProps {
  isZh: boolean;
  scenarioCategories: string[];
  categoryFilter: string;
  setCategoryFilter: (val: string) => void;
  scenarioSearch: string;
  onScenarioSearchChange: (val: string) => void;
  riskFilter: string;
  setRiskFilter: (val: string) => void;
  targetCount: number;
  batchMode: boolean;
  selectedDevice: Device | null;
  displayScenarios: AutomationScenario[];
  onOpenScenario: (scenario: AutomationScenario) => void;
  setCurrentStep: (val: StepId) => void;
  filteredScenarios: AutomationScenario[];
}

export const ScenarioSelectionStep: React.FC<ScenarioSelectionStepProps> = ({
  isZh,
  scenarioCategories,
  categoryFilter,
  setCategoryFilter,
  scenarioSearch,
  onScenarioSearchChange,
  riskFilter,
  setRiskFilter,
  targetCount,
  batchMode,
  selectedDevice,
  displayScenarios,
  onOpenScenario,
  setCurrentStep,
  filteredScenarios,
}) => {
  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      transition={{ duration: 0.2 }}
      className="h-full flex flex-col gap-3"
    >
      {/* Category + Filter bar */}
      <div className="flex-shrink-0 flex items-center gap-3 bg-white rounded-2xl border border-gray-100 shadow-sm px-4 py-3">
        <div className="flex items-center gap-1 flex-1 overflow-auto">
          {scenarioCategories.map((cat) => {
            const meta =
              cat === 'all'
                ? { label: '全部', labelEn: 'All', icon: '📋', color: 'text-gray-600' }
                : CATEGORY_META[cat] || { label: cat, labelEn: cat, icon: '📦', color: 'text-gray-600' };
            const count = cat === 'all' ? filteredScenarios.length : filteredScenarios.filter((s) => (s.category || 'Custom') === cat).length;
            const isActive = categoryFilter === cat;
            return (
              <button
                key={cat}
                onClick={() => setCategoryFilter(cat)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold whitespace-nowrap transition-all ${
                  isActive ? 'bg-cyan-50 text-cyan-700 border border-cyan-200 shadow-sm' : 'text-gray-500 hover:bg-gray-50'
                }`}
              >
                <span>{meta.icon}</span>
                <span>{isZh ? meta.label : meta.labelEn}</span>
                <span className="text-[10px] font-mono opacity-60">{count}</span>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-300" size={12} />
            <input
              type="text"
              value={scenarioSearch}
              onChange={(e) => onScenarioSearchChange(e.target.value)}
              placeholder={isZh ? '搜索场景...' : 'Search...'}
              className="pl-7 pr-3 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300 w-40"
            />
          </div>
          <select
            value={riskFilter}
            onChange={(e) => setRiskFilter(e.target.value)}
            className="px-2.5 py-1.5 border border-gray-100 rounded-lg text-xs bg-gray-50 outline-none focus:border-cyan-300"
          >
            <option value="all">{isZh ? '全部风险' : 'All Risks'}</option>
            <option value="low">{isZh ? '🟢 低风险' : '🟢 Low'}</option>
            <option value="medium">{isZh ? '🟡 中等' : '🟡 Medium'}</option>
            <option value="high">{isZh ? '🔴 高危' : '🔴 High'}</option>
          </select>
        </div>
      </div>

      {/* Target summary */}
      <div className="flex-shrink-0 flex items-center gap-3 px-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">{isZh ? '目标设备' : 'TARGET'}</span>
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-cyan-700 px-2.5 py-1 rounded-full bg-cyan-50 border border-cyan-100">
          <Server size={11} />
          {batchMode ? `${targetCount} ${isZh ? '台设备' : 'devices'}` : selectedDevice?.hostname || ''}
        </span>
        <button onClick={() => setCurrentStep(1)} className="text-[10px] font-semibold text-gray-400 hover:text-cyan-600 transition-colors">
          {isZh ? '修改' : 'Change'}
        </button>
      </div>

      {/* Scenario grid */}
      <div className="flex-1 min-h-0 overflow-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {displayScenarios.map((scenario) => {
            const risk = RISK_CONFIG[scenario.risk];
            const cat = CATEGORY_META[scenario.category || 'Custom'] || CATEGORY_META.Custom;
            return (
              <motion.button
                key={scenario.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                onClick={() => {
                  onOpenScenario(scenario);
                  setCurrentStep(3);
                }}
                className={`group relative p-4 rounded-xl border-2 border-l-4 text-left transition-all hover:shadow-lg hover:-translate-y-0.5 bg-white border-gray-100 hover:border-cyan-200 ${risk.stripe}`}
              >
                <div className="flex items-start justify-between gap-2 mb-2.5">
                  <div className="flex items-center gap-2.5">
                    <span className="text-2xl leading-none">{scenario.icon}</span>
                    <div>
                      <p className="text-sm font-bold text-gray-800 group-hover:text-cyan-700 transition-colors">
                        {isZh ? scenario.name_zh : scenario.name}
                      </p>
                      <p className="text-[11px] text-gray-400 mt-0.5 line-clamp-2">
                        {isZh ? scenario.description_zh : scenario.description}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 flex-wrap mt-3">
                  <span className={`inline-flex items-center gap-1 text-[9px] font-bold px-2 py-0.5 rounded-full border ${risk.bg} ${risk.border} ${risk.text}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${risk.dot}`} />
                    {isZh ? risk.label : risk.labelEn}
                  </span>
                  <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full bg-gray-50 border border-gray-100 ${cat.color}`}>
                    {isZh ? cat.label : cat.labelEn}
                  </span>
                  {(scenario.supported_platforms || []).length > 0 && (
                    <span className="text-[9px] text-gray-400 ml-auto">
                      {(scenario.supported_platforms || [])
                        .slice(0, 3)
                        .map((p) => getVendor(p))
                        .filter((v, i, a) => a.indexOf(v) === i)
                        .join(' · ')}
                      {(scenario.supported_platforms || []).length > 3 && ' +'}
                    </span>
                  )}
                </div>
              </motion.button>
            );
          })}
          {displayScenarios.length === 0 && (
            <div className="col-span-full py-16 text-center text-gray-300">
              <Zap size={32} strokeWidth={1} className="mx-auto mb-3 opacity-50" />
              <p className="text-sm">{isZh ? '没有匹配的场景' : 'No matching scenarios'}</p>
            </div>
          )}
        </div>
      </div>

      {/* Bottom bar */}
      <div className="flex-shrink-0 flex items-center justify-between bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-3">
        <button
          onClick={() => setCurrentStep(1)}
          className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 transition-colors"
        >
          <ChevronLeft size={14} />
          {isZh ? '返回设备选择' : 'Back to Devices'}
        </button>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          {['low', 'medium', 'high'].map((risk) => {
            const count = filteredScenarios.filter((s) => s.risk === risk).length;
            const cfg = RISK_CONFIG[risk as keyof typeof RISK_CONFIG];
            return (
              <span key={risk} className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${cfg.dot}`} />
                <span className="font-bold tabular-nums">{count}</span>
                {isZh ? cfg.label : cfg.labelEn}
              </span>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
};
