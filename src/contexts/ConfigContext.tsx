import React, { createContext, useContext, ReactNode } from 'react';
import type { ConfigTemplate } from '../types';

interface ConfigContextValue {
  // config snapshots / schedule
  isTakingSnapshot: boolean;
  activeBackupRunId: string | null;
  scheduleEnabled: boolean;
  setScheduleEnabled: React.Dispatch<React.SetStateAction<boolean>>;
  scheduleCron: string;
  setScheduleCron: (cron: string) => void;
  scheduleLoading: boolean;
  retentionDays: number;
  setRetentionDays: (days: number) => void;
  retentionMaxPerDevice: number;
  setRetentionMaxPerDevice: (count: number) => void;
  saveScheduleConfig: () => Promise<void>;
  configSnapshots: any[];
  handleRunBackupAllOnline: () => Promise<void>;
  handleBackupSingleDevice: (deviceId: string) => Promise<void>;
  
  // config diff
  handleNavigateToConfigDiff: (deviceId?: string) => void;
  diffPreSelectedDeviceId: string | null;
  activeDiffLines: any[];
  activeChangeLineIndexes: number[];
  diffFocusChangeIdx: number;
  diffOnlyChanges: boolean;
  diffShowFullBoth: boolean;
  diffMode: 'normalized' | 'raw';
  renderedDiffLines: any[];
  fullSideBySideRows: any[];
  diffChangeBlocks: any[];
  filteredDiffChangeBlocks: any[];
  diffBlockQuery: string;
  diffLineRefs: any;
  focusDiffChangeAt: (index: number) => void;
  configDiffLeft: any;
  configDiffRight: any;
  handleResetDiffView: () => void;
  handleSelectSnapshotPair: (left: any, right: any) => void;
  jumpToDiff: (direction: 'prev' | 'next') => void;
  setDiffOnlyChanges: React.Dispatch<React.SetStateAction<boolean>>;
  setDiffShowFullBoth: React.Dispatch<React.SetStateAction<boolean>>;
  setDiffMode: React.Dispatch<React.SetStateAction<'normalized' | 'raw'>>;
  setDiffBlockQuery: React.Dispatch<React.SetStateAction<string>>;
  
  // config workspace
  configTemplates: ConfigTemplate[];
  configVariableKeys: string[];
  configMissingVariables: string[];
  configScopedDevices: any[];
  configScopedOnlineCount: number;
  configReadinessScore: number;
  configValidationIssues: string[];
  configValidationWarnings: string[];
  configWorkspaceView: 'source' | 'rendered' | 'checks';
  selectedTemplateId: string;
  selectedConfigTemplate: ConfigTemplate | null;
  globalVars: any[];
  editorContent: string;
  configRenderedPreview: string;
  configScopePlatform: string;
  configScopeRole: string;
  configScopeSite: string;
  configPlatformOptions: string[];
  configRoleOptions: string[];
  configSiteOptions: string[];
  extractVars: (input: string) => string[];
  getPlatformLabel: (platform: string) => string;
  handleImportVars: (event: React.ChangeEvent<HTMLInputElement>) => Promise<void>;
  handleNewTemplate: () => void;
  handleAddVar: () => Promise<void>;
  handleDeleteVar: (id: string) => Promise<void>;
  handleDiscardChanges: () => Promise<void>;
  handleValidateTemplateWorkspace: () => void;
  handleSaveTemplate: () => Promise<void>;
  handleCreateScenarioDraftFromTemplate: () => void;
  handleOpenTemplateDeploy: () => void;
  setConfigWorkspaceView: (view: 'source' | 'rendered' | 'checks') => void;
  setSelectedTemplateId: (id: string) => void;
  setEditorContent: (content: string) => void;
  setConfigTemplates: React.Dispatch<React.SetStateAction<ConfigTemplate[]>>;
  setConfigScopePlatform: (platform: string) => void;
  setConfigScopeRole: (role: string) => void;
  setConfigScopeSite: (site: string) => void;
}

const ConfigContext = createContext<ConfigContextValue | null>(null);

export const useConfigContext = () => {
  const context = useContext(ConfigContext);
  if (!context) {
    throw new Error('useConfigContext must be used within ConfigProvider');
  }
  return context;
};

interface ConfigProviderProps {
  children: ReactNode;
  value: ConfigContextValue;
}

export const ConfigProvider: React.FC<ConfigProviderProps> = ({ children, value }) => (
  <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>
);
