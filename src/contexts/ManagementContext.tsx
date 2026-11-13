import React, { createContext, useContext, ReactNode } from 'react';
import type { User as UserType } from '../types';

interface ManagementContextValue {
  // user management
  showAddUserModal: boolean;
  setShowAddUserModal: (show: boolean) => void;
  showEditUserModal: boolean;
  setShowEditUserModal: (show: boolean) => void;
  editingUser: UserType | null;
  setEditingUser: (user: UserType | null) => void;
  newUserForm: any;
  setNewUserForm: (form: any) => void;
  editUserForm: any;
  setEditUserForm: (form: any) => void;
  showNewUserPwd: boolean;
  setShowNewUserPwd: React.Dispatch<React.SetStateAction<boolean>>;
  showEditUserPwd: boolean;
  setShowEditUserPwd: React.Dispatch<React.SetStateAction<boolean>>;
  handleAddUser: () => Promise<void>;
  handleEditUser: () => Promise<void>;
  
  // audit
  auditRows: any[];
  auditTotal: number;
  auditPage: number;
  setAuditPage: (page: number) => void;
  auditPageSize: number;
  setAuditPageSize: (size: number) => void;
  auditLoading: boolean;
  auditCategoryFilter: string;
  setAuditCategoryFilter: (category: string) => void;
  auditSeverityFilter: string;
  setAuditSeverityFilter: (severity: string) => void;
  auditStatusFilter: string;
  setAuditStatusFilter: (status: string) => void;
  auditTimeFilter: string;
  setAuditTimeFilter: (time: string) => void;
  openAuditEventDetail: (event: any) => void;
  
  // compliance
  complianceOverview: any;
  complianceFindings: any[];
  complianceFindingTotal: number;
  complianceSeverityFilter: string;
  setComplianceSeverityFilter: (severity: string) => void;
  complianceStatusFilter: string;
  setComplianceStatusFilter: (status: string) => void;
  complianceCategoryFilter: string;
  setComplianceCategoryFilter: (category: string) => void;
  compliancePage: number;
  setCompliancePage: (page: number) => void;
  compliancePageSize: number;
  setCompliancePageSize: (size: number) => void;
  complianceLoading: boolean;
  complianceRunLoading: boolean;
  runComplianceAudit: () => Promise<void>;
  openComplianceFindingDetail: (finding: any) => void;
  updateComplianceFinding: (findingId: string, updates: any) => Promise<void>;
}

const ManagementContext = createContext<ManagementContextValue | null>(null);

export const useManagementContext = () => {
  const context = useContext(ManagementContext);
  if (!context) {
    throw new Error('useManagementContext must be used within ManagementProvider');
  }
  return context;
};

interface ManagementProviderProps {
  children: ReactNode;
  value: ManagementContextValue;
}

export const ManagementProvider: React.FC<ManagementProviderProps> = ({ children, value }) => (
  <ManagementContext.Provider value={value}>{children}</ManagementContext.Provider>
);