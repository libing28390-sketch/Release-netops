import React from 'react';
import { Activity, BookOpen, ClipboardCheck, Gauge, ShieldCheck, type LucideIcon } from 'lucide-react';

export type KnowledgeAdminView = 'documents' | 'sources' | 'uat' | 'evaluation' | 'traces';

interface KnowledgeAdminNavigationProps {
  activeView: KnowledgeAdminView;
  onChange: (view: KnowledgeAdminView) => void;
}

interface KnowledgeAdminViewOption {
  id: KnowledgeAdminView;
  title: string;
  englishTitle: string;
  category: '日常管理' | '发布验收' | '高级诊断';
  description: string;
  whenToUse: string;
  icon: LucideIcon;
}

const VIEW_OPTIONS: KnowledgeAdminViewOption[] = [
  {
    id: 'documents',
    title: '文档与版本',
    englishTitle: 'Documents',
    category: '日常管理',
    description: '导入、分类、发布版本并维护索引',
    whenToUse: '新增知识、检查不同版本内容，或重新解析和建立索引时使用。',
    icon: BookOpen,
  },
  {
    id: 'sources',
    title: '来源与更新',
    englishTitle: 'Source Registry',
    category: '日常管理',
    description: '校验厂商官网并监控来源更新',
    whenToUse: '确认官方 URL 是否可信、手动刷新官网资料，或处理 Copilot 未命中的来源补充任务时使用。',
    icon: ShieldCheck,
  },
  {
    id: 'uat',
    title: 'UAT 签署',
    englishTitle: 'Browser UAT',
    category: '发布验收',
    description: '逐案例记录浏览器验收结论并签署',
    whenToUse: '完成四厂商和安全边界浏览器案例后，在当前登录账号下保存可审计的验收结论。',
    icon: ClipboardCheck,
  },
  {
    id: 'evaluation',
    title: '基线自检',
    englishTitle: 'RAG Evaluation',
    category: '高级诊断',
    description: '用固定夹具检查检索规则是否回退',
    whenToUse: '检索代码或规则变更后运行；它不读取当前租户文档，也不评测真实向量模型效果。',
    icon: Gauge,
  },
  {
    id: 'traces',
    title: '检索诊断',
    englishTitle: 'Retrieval Trace',
    category: '高级诊断',
    description: '查看一次检索为何命中或未命中',
    whenToUse: 'Copilot 回答不准确、没有引用或找不到知识时，按检索阶段定位问题。',
    icon: Activity,
  },
];

export const KnowledgeAdminNavigation: React.FC<KnowledgeAdminNavigationProps> = ({ activeView, onChange }) => {
  const activeOption = VIEW_OPTIONS.find((item) => item.id === activeView) || VIEW_OPTIONS[0];

  return (
    <section className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200/80 bg-white px-2.5 py-2 shadow-xs dark:border-slate-700/80 dark:bg-slate-800" aria-label="知识库功能导航">
      <div className="flex min-w-0 items-center gap-2">
        <BookOpen className="h-4 w-4 shrink-0 text-indigo-500" />
        <span className="text-xs font-bold text-slate-900 dark:text-white">知识库工作台</span>
        <span className="hidden rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700 sm:inline-flex dark:bg-indigo-950/40 dark:text-indigo-300">当前：{activeOption.title}</span>
      </div>

      <div className="flex min-w-0 flex-1 flex-wrap justify-end gap-1.5" aria-label="知识管理视图切换">
        {VIEW_OPTIONS.map((item) => {
          const Icon = item.icon;
          const active = item.id === activeView;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onChange(item.id)}
              aria-pressed={active}
              title={`${item.description} ${item.whenToUse}`}
              className={`group inline-flex min-w-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-left transition ${active
                ? 'border-indigo-300 bg-indigo-50 font-semibold text-indigo-800 shadow-sm ring-1 ring-indigo-100 dark:border-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-200 dark:ring-indigo-900/50'
                : 'border-slate-200 bg-slate-50/70 text-slate-700 hover:border-indigo-200 hover:bg-indigo-50/50 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200 dark:hover:border-indigo-800 dark:hover:bg-indigo-950/20'
              }`}
            >
              <span className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md ${active ? 'bg-indigo-600 text-white' : 'bg-white text-slate-500 shadow-xs group-hover:text-indigo-600 dark:bg-slate-800 dark:text-slate-400'}`}><Icon className="h-3 w-3" /></span>
              <span className="truncate text-[11px]">{item.title}</span>
              <span className={`hidden rounded-full px-1.5 py-0.5 text-[8px] font-semibold md:inline-flex ${item.category === '日常管理' ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : item.category === '发布验收' ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300' : 'bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300'}`}>{item.category}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
};

export default KnowledgeAdminNavigation;
