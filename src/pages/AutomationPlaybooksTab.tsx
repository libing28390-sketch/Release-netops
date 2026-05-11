import React from 'react';
import { FileText, Search, Zap } from 'lucide-react';
import type { Device } from '../types';
import PageHero from '../components/PageHero';

interface PlatformMeta {
  icon?: string;
  vendor?: string;
  name?: string;
  description?: string;
}

interface ScenarioVariable {
  key: string;
  label?: string;
  label_zh?: string;
  required?: boolean;
  type?: string;
  placeholder?: string;
  options?: string[];
  platform_hints?: Record<string, string>;
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
  supported_platforms?: string[];
  default_platform?: string;
  variables?: ScenarioVariable[];
}

interface PlaybookPreview {
  platform?: string;
  pre_check?: string[];
  execute?: string[];
  post_check?: string[];
  rollback?: string[];
}

interface AutomationPlaybooksTabProps {
  t: (key: string) => string;
  language: string;
  scenarioSearch: string;
  filteredScenarios: AutomationScenario[];
  selectedScenario: AutomationScenario | null;
  playbookVars: Record<string, string>;
  playbookPreview: PlaybookPreview | null;
  playbookPlatform: string;
  playbookDeviceIds: string[];
  playbookConcurrency: number;
  executionStatus: string;
  playbookDryRun: boolean;
  devices: Device[];
  platforms: Record<string, PlatformMeta>;
  onScenarioSearchChange: (value: string) => void;
  onSelectScenario: (scenario: AutomationScenario) => void;
  onPlatformChange: (platform: string) => void;
  onVariableChange: (key: string, value: string) => void;
  onToggleDevice: (deviceId: string) => void;
  onConcurrencyChange: (value: number) => void;
  onPreview: () => Promise<void> | void;
  onExecuteValidation: () => Promise<void> | void;
  onExecuteApply: () => Promise<void> | void;
}

const AutomationPlaybooksTab: React.FC<AutomationPlaybooksTabProps> = ({
  t,
  language,
  scenarioSearch,
  filteredScenarios,
  selectedScenario,
  playbookVars,
  playbookPreview,
  playbookPlatform,
  playbookDeviceIds,
  playbookConcurrency,
  executionStatus,
  playbookDryRun,
  devices,
  platforms,
  onScenarioSearchChange,
  onSelectScenario,
  onPlatformChange,
  onVariableChange,
  onToggleDevice,
  onConcurrencyChange,
  onPreview,
  onExecuteValidation,
  onExecuteApply,
}) => {
  return (
    <div className="h-full flex flex-col overflow-hidden">
      <PageHero
        icon={FileText}
        title="Playbooks"
        subtitle={t('playbookDesc')}
      />

      <div className="flex-1 flex flex-col px-6 py-5 overflow-hidden">
      <div className="mb-4 rounded-xl border border-black/10 bg-black/[0.02] px-4 py-3 text-xs text-black/60">
        {language === 'zh'
          ? '标准流程：选择场景 -> 填写变量 -> 选择目标设备 -> Preview Commands -> Validation / Apply Changes。'
          : 'Standard workflow: Select scenario -> Fill variables -> Select targets -> Preview Commands -> Validation / Apply Changes.'}
      </div>

      <div className="flex-1 grid grid-cols-1 md:grid-cols-12 gap-5 overflow-hidden">
        <div className="md:col-span-3 flex flex-col bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-black/5 bg-black/[0.01] space-y-2">
            <h3 className="text-[10px] font-bold uppercase tracking-widest text-black/40">{t('chooseScenario')}</h3>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-black/30" size={13} />
              <input
                value={scenarioSearch}
                onChange={(event) => onScenarioSearchChange(event.target.value)}
                placeholder="Search keyword"
                className="w-full pl-8 pr-2 py-1.5 text-xs border border-black/10 rounded-lg outline-none focus:border-[#00bceb]/40"
              />
            </div>
          </div>
          <div className="flex-1 overflow-auto p-2 space-y-1">
            {filteredScenarios.map((scenario) => (
              <button
                key={scenario.id}
                onClick={() => onSelectScenario(scenario)}
                className={`w-full p-3 rounded-xl text-left transition-all ${selectedScenario?.id === scenario.id ? 'bg-black text-white' : 'hover:bg-black/5'}`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">{scenario.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold truncate">{language === 'zh' ? scenario.name_zh : scenario.name}</p>
                    <p className={`text-[10px] mt-0.5 truncate ${selectedScenario?.id === scenario.id ? 'text-white/50' : 'text-black/40'}`}>
                      {language === 'zh' ? scenario.description_zh : scenario.description}
                    </p>
                  </div>
                  <span className={`text-[8px] font-bold uppercase px-1.5 py-0.5 rounded-full ${scenario.risk === 'high' ? 'bg-red-100 text-red-600' : scenario.risk === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-emerald-100 text-emerald-600'}`}>{scenario.risk}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="md:col-span-5 flex flex-col bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          {selectedScenario ? (
            <div className="flex flex-col h-full">
              <div className="p-4 border-b border-black/5 bg-black/[0.01]">
                <div className="flex items-center gap-2">
                  <span className="text-xl">{selectedScenario.icon}</span>
                  <div className="flex-1">
                    <h3 className="text-sm font-bold">{language === 'zh' ? selectedScenario.name_zh : selectedScenario.name}</h3>
                    <p className="text-[10px] text-black/40">{selectedScenario.category} · {selectedScenario.supported_platforms?.length || 0} {t('platformsSupported')}</p>
                  </div>
                </div>
              </div>
              <div className="flex-1 overflow-auto p-5 space-y-4">
                <div>
                  <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/30 mb-2">{t('selectPlatform')}</h4>
                  <div className="grid grid-cols-2 gap-1.5">
                    {(selectedScenario.supported_platforms || []).map((platformKey) => {
                      const platform = platforms[platformKey];
                      if (!platform) return null;
                      return (
                        <button
                          key={platformKey}
                          onClick={() => onPlatformChange(platformKey)}
                          className={`flex items-center gap-2 p-2 rounded-lg text-left text-xs transition-all ${playbookPlatform === platformKey ? 'bg-[#00bceb]/10 border border-[#00bceb]/30 text-[#00bceb] font-semibold' : 'border border-black/5 hover:border-black/20'}`}
                        >
                          <span>{platform.icon}</span>
                          <div className="min-w-0">
                            <p className="font-semibold truncate">{platform.vendor} {platform.name}</p>
                            <p className={`text-[9px] truncate ${playbookPlatform === platformKey ? 'text-[#00bceb]/60' : 'text-black/30'}`}>{platform.description}</p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/30 mb-3">{t('variables')}</h4>
                  <div className="space-y-3">
                    {selectedScenario.variables?.map((variable) => (
                      <div key={variable.key}>
                        <label className="text-xs font-medium flex items-center gap-1">
                          {variable.label}
                          {variable.required && <span className="text-red-400">*</span>}
                        </label>
                        {variable.type === 'textarea' ? (
                          <textarea
                            value={playbookVars[variable.key] || ''}
                            onChange={(event) => onVariableChange(variable.key, event.target.value)}
                            placeholder={variable.platform_hints?.[playbookPlatform] || variable.placeholder}
                            rows={3}
                            className="w-full mt-1 px-3 py-2 border border-black/10 rounded-xl text-xs font-mono outline-none focus:border-[#00bceb]/50"
                          />
                        ) : variable.type === 'select' ? (
                          <select
                            value={playbookVars[variable.key] || variable.options?.[0] || ''}
                            onChange={(event) => onVariableChange(variable.key, event.target.value)}
                            title={variable.label_zh || variable.label || variable.key}
                            className="w-full mt-1 px-3 py-2 border border-black/10 rounded-xl text-xs outline-none"
                          >
                            {variable.options?.map((option) => <option key={option} value={option}>{option}</option>)}
                          </select>
                        ) : (
                          <input
                            type={variable.type === 'number' ? 'number' : 'text'}
                            value={playbookVars[variable.key] || ''}
                            onChange={(event) => onVariableChange(variable.key, event.target.value)}
                            placeholder={variable.platform_hints?.[playbookPlatform] || variable.placeholder}
                            className="w-full mt-1 px-3 py-2 border border-black/10 rounded-xl text-xs font-mono outline-none focus:border-[#00bceb]/50"
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <h4 className="text-[10px] font-bold uppercase tracking-widest text-black/30 mb-2">{t('targetDevices')}</h4>
                  <div className="grid grid-cols-2 gap-1.5 max-h-40 overflow-auto">
                    {devices.filter((device) => device.status === 'online').map((device) => (
                      <button
                        key={device.id}
                        onClick={() => onToggleDevice(device.id)}
                        className={`flex items-center gap-2 p-2 rounded-lg text-xs transition-all ${playbookDeviceIds.includes(device.id) ? 'bg-[#00bceb]/10 border border-[#00bceb]/30 text-[#00bceb] font-semibold' : 'border border-black/5 hover:border-black/20'}`}
                      >
                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        {device.hostname}
                      </button>
                    ))}
                  </div>
                  {playbookDeviceIds.length > 0 && <p className="text-[10px] mt-1.5 text-[#00bceb] font-semibold">{playbookDeviceIds.length} {t('devicesSelected')}</p>}
                </div>

                <div className="flex items-center gap-4 pt-3 border-t border-black/5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-black/40">{t('concurrency')}:</span>
                    <select value={playbookConcurrency} onChange={(event) => onConcurrencyChange(Number(event.target.value))} title={language === 'zh' ? '并发执行数量' : 'Execution concurrency'} className="text-xs border border-black/10 rounded-lg px-2 py-1 outline-none">
                      {[1, 2, 3, 5, 10].map((value) => <option key={value} value={value}>{value}</option>)}
                    </select>
                  </div>
                </div>

                <div className="pt-2 space-y-2">
                  <p className="text-[10px] text-black/35 text-center">
                    {language === 'zh' ? '推荐：先运行校验确认无误，再应用变更' : 'Recommended: validate first, then apply changes'}
                  </p>
                  <div className="grid grid-cols-3 gap-2">
                    <button onClick={() => void onPreview()} className="flex items-center justify-center gap-1 px-3 py-2.5 border border-black/10 rounded-xl text-xs font-bold hover:bg-black/5 transition-all">
                      <Search size={12} /> {t('previewCommands')}
                    </button>
                    <button
                      onClick={() => void onExecuteValidation()}
                      disabled={playbookDeviceIds.length === 0 || executionStatus === 'starting'}
                      className={`px-3 py-2.5 rounded-xl text-xs font-bold transition-all border ${playbookDeviceIds.length === 0 || executionStatus === 'starting' ? 'bg-black/5 text-black/25 border-black/8 cursor-not-allowed' : 'bg-white text-black/70 border-black/15 hover:bg-black/5'}`}
                    >
                      {executionStatus === 'starting' && playbookDryRun ? (language === 'zh' ? '校验中...' : 'Validating...') : (language === 'zh' ? '运行校验' : 'Run Validation')}
                    </button>
                    <button
                      onClick={() => void onExecuteApply()}
                      disabled={playbookDeviceIds.length === 0 || executionStatus === 'starting'}
                      className={`px-3 py-2.5 rounded-xl text-xs font-bold text-white transition-all ${playbookDeviceIds.length === 0 || executionStatus === 'starting' ? 'bg-black/15 text-black/30 cursor-not-allowed' : 'bg-[#00bceb] hover:bg-[#0096bd] shadow-lg shadow-[#00bceb]/20'}`}
                    >
                      {executionStatus === 'starting' && !playbookDryRun ? (language === 'zh' ? '下发中...' : 'Applying...') : (language === 'zh' ? '应用变更' : 'Apply Changes')}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-black/20 p-8 text-center">
              <Zap size={36} strokeWidth={1} />
              <p className="mt-3 text-sm font-medium">{t('selectScenarioHint')}</p>
            </div>
          )}
        </div>

        <div className="md:col-span-4 flex flex-col bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-black/5 bg-black/[0.01]">
            <h3 className="text-[10px] font-bold uppercase tracking-widest text-black/40">{t('commandPreview')}</h3>
          </div>
          {playbookPreview ? (
            <div className="flex-1 overflow-auto bg-[#1E1E1E] font-mono text-xs p-4 space-y-4">
              {playbookPreview.platform && platforms[playbookPreview.platform] && (
                <div className="flex items-center gap-2 pb-2 border-b border-white/10">
                  <span>{platforms[playbookPreview.platform].icon}</span>
                  <span className="text-white/50 text-[10px]">{platforms[playbookPreview.platform].vendor} {platforms[playbookPreview.platform].name}</span>
                </div>
              )}
              {(['pre_check', 'execute', 'post_check', 'rollback'] as const).map((phase) => {
                const commands = playbookPreview[phase] || [];
                if (commands.length === 0) return null;
                const colors: Record<string, string> = {
                  pre_check: 'text-blue-400',
                  execute: 'text-emerald-400',
                  post_check: 'text-purple-400',
                  rollback: 'text-red-400',
                };
                return (
                  <div key={phase}>
                    <p className={`text-[10px] font-bold uppercase tracking-wider mb-1 ${colors[phase]}`}>── {phase.replace('_', ' ')} ──</p>
                    {commands.map((command, index) => <div key={index} className="text-[#d4d4d4] leading-6 hover:bg-white/5 px-2 rounded">{command}</div>)}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex-1 bg-[#1E1E1E] flex flex-col items-center justify-center text-white/20">
              <FileText size={32} strokeWidth={1} />
              <p className="mt-3 text-sm">{t('previewHint')}</p>
            </div>
          )}
        </div>
      </div>
      </div>
    </div>
  );
};

export default AutomationPlaybooksTab;