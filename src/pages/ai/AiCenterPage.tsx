import React from 'react';
import { ProviderManagementTab } from './Providers/ProviderManagementTab';
import { ModelManagementTab } from './Models/ModelManagementTab';
import { PromptCenterTab } from './PromptCenter/PromptCenterTab';
import { UsageDashboardTab } from './Usage/UsageDashboardTab';
import { SecurityPolicyTab } from './Security/SecurityPolicyTab';
import { AssistantTab } from './Copilot/AssistantTab';
import { AgentManagementTab } from './Agents/AgentManagementTab';
import { GovernanceTab } from './Governance/GovernanceTab';
import { KnowledgeManagementTab } from './Knowledge/KnowledgeManagementTab';
import { ProductCatalogManagementTab } from './Catalog/ProductCatalogManagementTab';

interface AiCenterPageProps {
  activeSubTab?: string;
}

export const AiCenterPage: React.FC<AiCenterPageProps> = ({ activeSubTab }) => {
  const activeTab = activeSubTab || 'providers';
  const isCopilot = activeTab === 'copilot';

  return (
    <div className={`box-border flex w-full h-full min-h-0 flex-1 flex-col p-3 sm:p-6 ${isCopilot ? 'overflow-hidden' : 'overflow-y-auto'}`}>
      {activeTab === 'providers' && <ProviderManagementTab />}
      {activeTab === 'models' && <ModelManagementTab />}
      {activeTab === 'prompts' && <PromptCenterTab />}
      {activeTab === 'copilot' && <AssistantTab />}
      {activeTab === 'agents' && <AgentManagementTab />}
      {activeTab === 'knowledge' && <KnowledgeManagementTab />}
      {activeTab === 'catalog' && <ProductCatalogManagementTab />}
      {activeTab === 'governance' && <GovernanceTab />}
      {activeTab === 'usage' && <UsageDashboardTab />}
      {activeTab === 'security' && <SecurityPolicyTab />}
    </div>
  );
};

export default AiCenterPage;
