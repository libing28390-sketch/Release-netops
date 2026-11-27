import React from 'react';
import { Activity, BookOpen, ClipboardCheck, Gauge, ShieldCheck, type LucideIcon } from 'lucide-react';
import { Panel } from '../../../components/ui/Panel';
import { StatusBadge, type StatusTone } from '../../../components/ui/StatusBadge';

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

const CATEGORY_TONES: Record<KnowledgeAdminViewOption['category'], StatusTone> = {
  日常管理: 'success',
  发布验收: 'warning',
  高级诊断: 'accent',
};

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
  const primaryViews = VIEW_OPTIONS.filter((item) => item.category === '日常管理');
  const activeOption = primaryViews.find((item) => item.id === activeView) || primaryViews[0];

  return (
    <Panel className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5" aria-label="知识库功能导航">
      <div className="flex min-w-0 items-center gap-2">
        <BookOpen className="h-4 w-4 shrink-0 text-accent" />
        <span className="text-sm font-semibold text-fg">知识库工作台</span>
        <StatusBadge tone={CATEGORY_TONES[activeOption.category]}>当前：{activeOption.title}</StatusBadge>
      </div>

      <div role="group" aria-label="知识管理视图切换" className="flex flex-wrap items-center gap-1.5">
        {primaryViews.map((item) => {
          const Icon = item.icon;
          const active = item.id === activeView;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onChange(item.id)}
              aria-pressed={active}
              title={`${item.description} ${item.whenToUse}`}
              className={`group inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-left text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${active
                ? 'border-accent/40 bg-accent-subtle font-semibold text-accent shadow-xs'
                : 'border-line bg-surface text-fg hover:border-accent/30 hover:bg-surface-muted'
              }`}
            >
              <span className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md ${active ? 'bg-accent text-white' : 'bg-surface-muted text-fg-muted group-hover:text-accent'}`}>
                <Icon className="h-3 w-3" aria-hidden="true" />
              </span>
              <span className="whitespace-nowrap">{item.title}</span>
            </button>
          );
        })}
      </div>
    </Panel>
  );
};

export default KnowledgeAdminNavigation;
