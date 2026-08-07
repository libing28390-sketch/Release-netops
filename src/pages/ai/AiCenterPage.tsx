import React from 'react';
import { ProviderManagementTab } from './Providers/ProviderManagementTab';
import { ModelManagementTab } from './Models/ModelManagementTab';
import { PromptCenterTab } from './PromptCenter/PromptCenterTab';
import { UsageDashboardTab } from './Usage/UsageDashboardTab';
import { AssistantTab } from './Copilot/AssistantTab';
import { AgentManagementTab } from './Agents/AgentManagementTab';
import { GovernanceTab } from './Governance/GovernanceTab';
import { KnowledgeManagementTab } from './Knowledge/KnowledgeManagementTab';

interface AiCenterPageProps {
  activeSubTab?: string;
}

export const AiCenterPage: React.FC<AiCenterPageProps> = ({ activeSubTab }) => {
  const activeTab = activeSubTab || 'providers';

  return (
    <div className="w-full h-full flex-1 overflow-y-auto p-6">
      {activeTab === 'providers' && <ProviderManagementTab />}
      {activeTab === 'models' && <ModelManagementTab />}
      {activeTab === 'prompts' && <PromptCenterTab />}
      {activeTab === 'copilot' && <AssistantTab />}
      {activeTab === 'agents' && <AgentManagementTab />}
      {activeTab === 'knowledge' && <KnowledgeManagementTab />}
      {activeTab === 'governance' && <GovernanceTab />}
      {activeTab === 'usage' && <UsageDashboardTab />}
    </div>
  );
};

export default AiCenterPage;
