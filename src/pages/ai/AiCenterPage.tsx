import React, { lazy, Suspense } from 'react';
import { LoaderCircle, ShieldOff } from 'lucide-react';
import { useCoreApp } from '../../contexts/AppDomainContext';
import { EmptyState } from '../../components/ui/EmptyState';
import { ActionButton } from '../../components/ui/ActionIconButton';
import { getAiCenterCopy } from './AiCenterPage.copy';

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

/* ── Access (review item L6-e) ────────────────────────────────────────────
 * Mirrors backend/ai/security/permissions.py (ROLE_AI_PERMISSIONS) so the AI
 * Center does not open on a page whose API answers 403.  The server stays the
 * authority: this only decides what to render.  Keep both tables in sync. */

export const ROLE_AI_PERMISSIONS: Record<string, readonly string[]> = {
  Operator: [
    'ai.view', 'ai.use', 'ai.command_explain', 'ai.config_analyze',
    'ai.diff_analyze', 'ai.alarm_analyze', 'ai.assistant', 'ai.audit.view',
    'ai.agent.use', 'ai.copilot.feedback', 'ai.diagnostics.run',
  ],
  Viewer: ['ai.view', 'ai.command_explain', 'ai.config_analyze', 'ai.diff_analyze', 'ai.alarm_analyze'],
};

/** Permission the main API of each sub-page requires. */
export const AI_CENTER_TAB_PERMISSIONS: Record<string, string> = {
  providers: 'ai.provider.manage',
  models: 'ai.model.manage',
  health: 'ai.view',
  prompts: 'ai.prompt.manage',
  copilot: 'ai.assistant',
  agents: 'ai.agent.use',
  knowledge: 'ai.knowledge.manage',
  'retrieval-test': 'ai.knowledge.manage',
  catalog: 'ai.view',
  governance: 'ai.use',
  usage: 'ai.usage.view',
  security: 'ai.audit.view',
};

/** Landing order when no sub-page was asked for: providers, then Copilot, then sidebar order. */
const AI_CENTER_LANDING_ORDER = [
  'providers', 'copilot', 'models', 'health', 'prompts', 'agents', 'knowledge',
  'retrieval-test', 'catalog', 'governance', 'usage', 'security',
];

interface AccessUser {
  role?: string | null;
  permissions?: unknown;
}

export const hasAiPermission = (user: AccessUser | null | undefined, permission: string): boolean => {
  const role = String(user?.role || '').trim();
  // No role in the session (should not happen for a signed-in user): do not
  // hide anything in the UI; the server still enforces every permission.
  if (!role) return true;
  if (role === 'Administrator') return true;
  const extra = Array.isArray(user?.permissions) ? user?.permissions as unknown[] : [];
  if (extra.includes(permission)) return true;
  return (ROLE_AI_PERMISSIONS[role] || []).includes(permission);
};

export const canOpenAiCenterTab = (user: AccessUser | null | undefined, tab: string): boolean => {
  const permission = AI_CENTER_TAB_PERMISSIONS[tab];
  return permission ? hasAiPermission(user, permission) : false;
};

export const firstAccessibleAiCenterTab = (user: AccessUser | null | undefined): string | null => (
  AI_CENTER_LANDING_ORDER.find((tab) => canOpenAiCenterTab(user, tab)) || null
);

export type AiCenterTabResolution =
  | { kind: 'page'; tab: string }
  | { kind: 'forbidden'; tab: string; permission: string; fallback: string | null }
  | { kind: 'none' };

/**
 * `implicit` is true when the user opened the AI Center itself (/ai/center)
 * rather than a specific sub-page: then the first page they may use is shown
 * instead of a permission error.
 */
export const resolveAiCenterTab = (
  user: AccessUser | null | undefined,
  requested: string | undefined,
  implicit: boolean,
): AiCenterTabResolution => {
  const known = Boolean(requested && AI_CENTER_TAB_PERMISSIONS[requested]);
  const tab = known ? requested as string : 'providers';
  if (canOpenAiCenterTab(user, tab)) return { kind: 'page', tab };
  const fallback = firstAccessibleAiCenterTab(user);
  if (implicit || !known) {
    return fallback ? { kind: 'page', tab: fallback } : { kind: 'none' };
  }
  return { kind: 'forbidden', tab, permission: AI_CENTER_TAB_PERMISSIONS[tab], fallback };
};

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
  const { language, currentUser, activeTab: appActiveTab, navTo } = useCoreApp();
  const copy = getAiCenterCopy(language);
  // AppMainContent passes "providers" for /ai/center as well; that case is
  // the AI Center landing, not an explicit request for the Provider page.
  const implicit = !activeSubTab || appActiveTab === 'ai-center';
  const resolution = resolveAiCenterTab(currentUser, activeSubTab, implicit);
  const activeTab = resolution.kind === 'page' ? resolution.tab : '';
  const isCopilot = activeTab === 'copilot';

  return (
    <div className={`box-border flex h-full min-h-0 w-full min-w-0 flex-1 flex-col p-3 sm:p-6 ${isCopilot ? 'overflow-hidden' : 'overflow-y-auto'}`}>
      <div className="mx-auto flex min-h-0 w-full max-w-[1680px] flex-1 flex-col">
        {resolution.kind === 'forbidden' ? (
          <EmptyState
            icon={ShieldOff}
            title={copy.forbiddenTitle}
            description={copy.forbiddenBody(copy.pages[resolution.tab] || resolution.tab, resolution.permission)}
            action={resolution.fallback ? (
              <ActionButton type="button" variant="primary" size="md" onClick={() => navTo(`/ai/${resolution.fallback}`)}>
                {copy.forbiddenGoTo(copy.pages[resolution.fallback] || resolution.fallback)}
              </ActionButton>
            ) : undefined}
          />
        ) : resolution.kind === 'none' ? (
          <EmptyState icon={ShieldOff} title={copy.noAccessTitle} description={copy.noAccessBody} />
        ) : (
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
        )}
      </div>
    </div>
  );
};

export default AiCenterPage;
