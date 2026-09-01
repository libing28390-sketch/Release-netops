import React, { lazy, Suspense } from 'react';

const ProviderManagementTab = lazy(() => import('./Providers/ProviderManagementTab').then(({ ProviderManagementTab }) => ({ default: ProviderManagementTab })));
const ModelManagementTab = lazy(() => import('./Models/ModelManagementTab').then(({ ModelManagementTab }) => ({ default: ModelManagementTab })));
const PromptCenterTab = lazy(() => import('./PromptCenter/PromptCenterTab').then(({ PromptCenterTab }) => ({ default: PromptCenterTab })));
const UsageDashboardTab = lazy(() => import('./Usage/UsageDashboardTab').then(({ UsageDashboardTab }) => ({ default: UsageDashboardTab })));
const SecurityPolicyTab = lazy(() => import('./Security/SecurityPolicyTab').then(({ SecurityPolicyTab }) => ({ default: SecurityPolicyTab })));
const AssistantTab = lazy(() => import('./Copilot/AssistantTab').then(({ AssistantTab }) => ({ default: AssistantTab })));
const AgentManagementTab = lazy(() => import('./Agents/AgentManagementTab').then(({ AgentManagementTab }) => ({ default: AgentManagementTab })));
const GovernanceTab = lazy(() => import('./Governance/GovernanceTab').then(({ GovernanceTab }) => ({ default: GovernanceTab })));
const KnowledgeManagementTab = lazy(() => import('./Knowledge/KnowledgeManagementTab').then(({ KnowledgeManagementTab }) => ({ default: KnowledgeManagementTab })));
const ProductCatalogManagementTab = lazy(() => import('./Catalog/ProductCatalogManagementTab').then(({ ProductCatalogManagementTab }) => ({ default: ProductCatalogManagementTab })));
const RetrievalTestTab = lazy(() => import('./Knowledge/RetrievalTestTab').then(({ RetrievalTestTab }) => ({ default: RetrievalTestTab })));

const aiPanelFallback = (
  <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-black/5 bg-white/70 text-sm text-black/40">
    Loading...
  </div>
);

interface AiCenterPageProps {
  activeSubTab?: string;
}

export const AiCenterPage: React.FC<AiCenterPageProps> = ({ activeSubTab }) => {
  const activeTab = activeSubTab || 'providers';
  const isCopilot = activeTab === 'copilot';

  return (
    <div className={`box-border flex h-full min-h-0 w-full min-w-0 flex-1 flex-col p-3 sm:p-6 ${isCopilot ? 'overflow-hidden' : 'overflow-y-auto'}`}>
      <div className="mx-auto flex min-h-0 w-full max-w-[1680px] flex-1 flex-col">
        <Suspense fallback={aiPanelFallback}>
          {activeTab === 'providers' && <ProviderManagementTab />}
          {activeTab === 'models' && <ModelManagementTab />}
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
