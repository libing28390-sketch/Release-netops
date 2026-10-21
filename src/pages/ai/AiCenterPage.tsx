import React, { lazy, Suspense } from 'react';
import { LoaderCircle } from 'lucide-react';
import { useCoreApp } from '../../contexts/AppDomainContext';

const ProviderManagementTab = lazy(() => import('./Providers/ProviderManagementTab').then(({ ProviderManagementTab }) => ({ default: ProviderManagementTab })));
const ModelManagementTab = lazy(() => import('./Models/ModelManagementTab').then(({ ModelManagementTab }) => ({ default: ModelManagementTab })));
const ModelHealthDashboardTab = lazy(() => import('./Health/ModelHealthDashboardTab').then(({ ModelHealthDashboardTab }) => ({ default: ModelHealthDashboardTab })));
const PromptCenterTab = lazy(() => import('./PromptCenter/PromptCenterTab').then(({ PromptCenterTab }) => ({ default: PromptCenterTab })));
const UsageDashboardTab = lazy(() => import('./Usage/UsageDashboardTab').then(({ UsageDashboardTab }) => ({ default: UsageDashboardTab })));
const SecurityPolicyTab = lazy(() => import('./Security/SecurityPolicyTab').then(({ SecurityPolicyTab }) => ({ default: SecurityPolicyTab })));
const AssistantTab = lazy(() => import('./Copilot/AssistantTab').then(({ AssistantTab }) => ({ default: AssistantTab })));
const AgentManagementTab = lazy(() => import('./Agents/AgentManagementTab').then(({ AgentManagementTab }) => ({ default: AgentManagementTab })));
const GovernanceTab = lazy(() => import('./Governance/GovernanceTab').then(({ GovernanceTab }) => ({ default: GovernanceTab })));
const KnowledgeManagementTab = lazy(() => import('./Knowledge/KnowledgeManagementTab').then(({ KnowledgeManagementTab }) => ({ default: KnowledgeManagementTab })));
const ProductCatalogManagementTab = lazy(() => import('./Catalog/ProductCatalogManagementTab').then(({ ProductCatalogManagementTab }) => ({ default: ProductCatalogManagementTab })));
const RetrievalTestTab = lazy(() => import('./Knowledge/RetrievalTestTab').then(({ RetrievalTestTab }) => ({ default: RetrievalTestTab })));

export const AiCenterPageLoadingState: React.FC<{ language?: string }> = ({ language }) => (
  <div role="status" aria-live="polite" aria-busy="true" className="flex min-h-[240px] items-center justify-center gap-2 rounded-2xl border border-[var(--ui-border)] bg-[var(--ui-surface)] text-sm text-[var(--ui-fg-muted)]">
    <LoaderCircle size={16} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
    <span>{language === 'zh' ? '正在加载 AI 中心…' : 'Loading AI Center…'}</span>
  </div>
);

interface AiCenterPageProps {
  activeSubTab?: string;
}

export const AiCenterPage: React.FC<AiCenterPageProps> = ({ activeSubTab }) => {
  const { language } = useCoreApp();
  const activeTab = activeSubTab || 'providers';
  const isCopilot = activeTab === 'copilot';

  return (
    <div className={`box-border flex h-full min-h-0 w-full min-w-0 flex-1 flex-col p-3 sm:p-6 ${isCopilot ? 'overflow-hidden' : 'overflow-y-auto'}`}>
      <div className="mx-auto flex min-h-0 w-full max-w-[1680px] flex-1 flex-col">
        <Suspense fallback={<AiCenterPageLoadingState language={language} />}>
          {activeTab === 'providers' && <ProviderManagementTab />}
          {activeTab === 'models' && <ModelManagementTab />}
          {activeTab === 'health' && <ModelHealthDashboardTab />}
          {activeTab === 'prompts' && <PromptCenterTab />}
          {activeTab === 'copilot' && <AssistantTab />}
          {activeTab === 'agents' && <AgentManagementTab />}
          {activeTab === 'knowledge' && <KnowledgeManagementTab />}
          {activeTab === 'retrieval-test' && <RetrievalTestTab />}
          {activeTab === 'catalog' && <ProductCatalogManagementTab />}
          {activeTab === 'governance' && <GovernanceTab />}
          {activeTab === 'usage' && <UsageDashboardTab />}
          {activeTab === 'security' && <SecurityPolicyTab />}
        </Suspense>
      </div>
    </div>
  );
};

export default AiCenterPage;
