import React from 'react';
import { motion } from 'motion/react';
import { X } from 'lucide-react';

interface ScenarioVariableDraft {
  key: string;
  label: string;
  type: string;
  required: boolean;
  placeholder?: string;
}

interface ScenarioDraftOrigin {
  kind: 'manual' | 'template';
  templateName?: string;
  variableKeys: string[];
}

interface ScenarioFormState {
  name: string;
  name_zh: string;
  description: string;
  description_zh: string;
  category: string;
  icon: string;
  risk: string;
  platform: string;
  pre_check: string;
  execute: string;
  post_check: string;
  rollback: string;
}

interface AddScenarioModalProps {
  open: boolean;
  language: string;
  resolvedTheme: 'light' | 'dark';
  platforms: Record<string, unknown>;
  form: ScenarioFormState;
  variables: ScenarioVariableDraft[];
  draftOrigin: ScenarioDraftOrigin;
  isSaving: boolean;
  onClose: () => void;
  onSubmit: () => void;
  onFormChange: (updater: (prev: ScenarioFormState) => ScenarioFormState) => void;
}

const AddScenarioModal: React.FC<AddScenarioModalProps> = ({
  open,
  language,
  resolvedTheme,
  platforms,
  form,
  variables,
  draftOrigin,
  isSaving,
  onClose,
  onSubmit,
  onFormChange,
}) => {
  if (!open) return null;

  const isDark = resolvedTheme === 'dark';

  return (
    <div className="fixed inset-0 bg-black/35 backdrop-blur-sm flex items-center justify-center z-[70] p-4">
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className={`w-full max-w-3xl rounded-2xl border shadow-2xl overflow-hidden ${isDark ? 'bg-[#121c2d] border-white/10' : 'bg-white border-black/10'}`}
      >
        <div className={`px-6 py-4 border-b flex items-center justify-between ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <div>
            <h3 className={`text-lg font-bold ${isDark ? 'text-white/90' : 'text-[#0b2a3c]'}`}>Create Custom Scenario</h3>
            <p className={`text-xs mt-1 ${isDark ? 'text-white/45' : 'text-black/45'}`}>Define a reusable playbook scenario (single platform).</p>
          </div>
          <button onClick={onClose} className={isDark ? 'text-white/50 hover:text-white' : 'text-black/40 hover:text-black'} title="Close">
            <X size={18} />
          </button>
        </div>
        <div className="p-6 grid grid-cols-2 gap-4 max-h-[70vh] overflow-auto">
          {draftOrigin.kind === 'template' && (
            <div className="col-span-2 rounded-2xl border border-[#00bceb]/20 bg-[#00bceb]/6 px-4 py-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#007d9d]">
                    {language === 'zh' ? 'Template Imported Draft' : 'Template Imported Draft'}
                  </p>
                  <p className="mt-1 text-sm font-semibold text-black/80">
                    {language === 'zh'
                      ? `草稿来源：${draftOrigin.templateName || '配置模板'}`
                      : `Draft source: ${draftOrigin.templateName || 'Configuration Template'}`}
                  </p>
                  <p className="mt-1 text-xs text-black/50">
                    {language === 'zh'
                      ? '已自动把模板正文带入 Execute 阶段，并把占位符转换成场景变量。你可以继续补充 pre-check、post-check 和 rollback。'
                      : 'The template body has been imported into the Execute phase and placeholders were converted into scenario variables. You can continue editing pre-check, post-check, and rollback.'}
                  </p>
                </div>
                <span className="shrink-0 rounded-full bg-white px-2.5 py-1 text-[10px] font-semibold text-[#007d9d] border border-[#00bceb]/20">
                  {draftOrigin.variableKeys.length} {language === 'zh' ? '变量' : 'vars'}
                </span>
              </div>
            </div>
          )}
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Name</label>
            <input value={form.name} onChange={(e) => onFormChange((prev) => ({ ...prev, name: e.target.value }))} title="Scenario name" placeholder="e.g. Core interface recovery" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none" />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Name (ZH)</label>
            <input value={form.name_zh} onChange={(e) => onFormChange((prev) => ({ ...prev, name_zh: e.target.value }))} title="Scenario name in Chinese" placeholder="例如：核心链路恢复" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none" />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Description</label>
            <input value={form.description} onChange={(e) => onFormChange((prev) => ({ ...prev, description: e.target.value }))} title="Scenario description" placeholder="Short summary for operators" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none" />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Description (ZH)</label>
            <input value={form.description_zh} onChange={(e) => onFormChange((prev) => ({ ...prev, description_zh: e.target.value }))} title="Scenario description in Chinese" placeholder="给运维人员的简要说明" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none" />
          </div>
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Category</label>
            <input value={form.category} onChange={(e) => onFormChange((prev) => ({ ...prev, category: e.target.value }))} title="Scenario category" placeholder="routing / access / security" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none" />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Icon</label>
              <input value={form.icon} onChange={(e) => onFormChange((prev) => ({ ...prev, icon: e.target.value }))} title="Scenario icon" placeholder="Zap" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none" />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Risk</label>
              <select value={form.risk} onChange={(e) => onFormChange((prev) => ({ ...prev, risk: e.target.value }))} title="Scenario risk" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none bg-white">
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Platform</label>
              <select value={form.platform} onChange={(e) => onFormChange((prev) => ({ ...prev, platform: e.target.value }))} title="Scenario platform" className="mt-1 w-full px-3 py-2 border border-black/10 rounded-xl text-sm outline-none bg-white">
                {Object.keys(platforms).map((pk) => <option key={pk} value={pk}>{pk}</option>)}
              </select>
            </div>
          </div>
          <div className="col-span-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Pre-Check Commands (one per line)</label>
            <textarea value={form.pre_check} onChange={(e) => onFormChange((prev) => ({ ...prev, pre_check: e.target.value }))} title="Pre-check commands" placeholder="show interface status" className="mt-1 w-full h-20 px-3 py-2 border border-black/10 rounded-xl text-xs font-mono outline-none" />
          </div>
          <div className="col-span-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Execute Commands (one per line)</label>
            <textarea value={form.execute} onChange={(e) => onFormChange((prev) => ({ ...prev, execute: e.target.value }))} title="Execute commands" placeholder="configure terminal" className="mt-1 w-full h-24 px-3 py-2 border border-black/10 rounded-xl text-xs font-mono outline-none" />
          </div>
          {variables.length > 0 && (
            <div className="col-span-2 rounded-2xl border border-black/10 bg-black/[0.02] p-4">
              <div className="flex items-center justify-between gap-3 mb-3">
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Variables</label>
                  <p className="mt-1 text-xs text-black/40">
                    {language === 'zh' ? '以下变量会随场景一起保存，后续在 Automation 执行时填写。' : 'These variables will be saved with the scenario and filled in later during Automation execution.'}
                  </p>
                </div>
                <span className="text-[10px] text-black/35">{variables.length}</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {variables.map((variable) => (
                  <div key={variable.key} className="rounded-xl border border-black/8 bg-white px-3 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-black/75">{variable.label}</span>
                      <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-50 text-red-600 font-bold">
                        {variable.required ? (language === 'zh' ? '必填' : 'REQ') : (language === 'zh' ? '选填' : 'OPT')}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] font-mono text-black/45">{variable.key}</p>
                    <p className="mt-2 text-[11px] text-black/40">
                      {language === 'zh' ? `类型：${variable.type}` : `Type: ${variable.type}`}
                      {variable.placeholder ? ` · ${language === 'zh' ? '默认提示' : 'Hint'}: ${variable.placeholder}` : ''}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="col-span-2 grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Post-Check Commands</label>
              <textarea value={form.post_check} onChange={(e) => onFormChange((prev) => ({ ...prev, post_check: e.target.value }))} title="Post-check commands" placeholder="show logging | last 20" className="mt-1 w-full h-20 px-3 py-2 border border-black/10 rounded-xl text-xs font-mono outline-none" />
            </div>
            <div>
              <label className="text-[10px] font-bold uppercase tracking-widest text-black/45">Rollback Commands</label>
              <textarea value={form.rollback} onChange={(e) => onFormChange((prev) => ({ ...prev, rollback: e.target.value }))} title="Rollback commands" placeholder="rollback configuration" className="mt-1 w-full h-20 px-3 py-2 border border-black/10 rounded-xl text-xs font-mono outline-none" />
            </div>
          </div>
        </div>
        <div className={`px-6 py-4 border-t flex gap-3 ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <button onClick={onClose} className={`flex-1 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${isDark ? 'bg-white/10 text-white/80 hover:bg-white/15' : 'bg-black/[0.04] text-black/70 hover:bg-black/[0.08]'}`}>
            Cancel
          </button>
          <button onClick={onSubmit} disabled={isSaving} className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold text-white bg-[#008bb0] hover:bg-[#00769a] transition-all shadow-lg shadow-[#00bceb]/20 disabled:opacity-60">
            {isSaving ? 'Saving...' : 'Create Scenario'}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default AddScenarioModal;