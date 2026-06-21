import { useCallback } from 'react';
import type { NavigateFunction, Location } from 'react-router-dom';
import type { Language } from '../i18n.tsx';

const ALL_FEATURES = [
  'automation',
  'config_management',
  'monitoring',
  'alerting',
  'topology',
  'ipam',
  'capacity',
  'reports',
  'compliance',
  'inspections',
  'change_orders',
  'access_center',
  'scheduled_jobs',
  'password_rotation',
  'rbac',
];

interface UseLicenseArgs {
  isAuthenticated: boolean;
  activeTab: string;
  language: Language;
  navigate: NavigateFunction;
  location: Pick<Location, 'pathname'>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

interface UseLicenseResult {
  isLicenseValid: boolean;
  licenseError: string | null;
  licenseFeatures: string[];
  checkLicenseStatus: () => Promise<void>;
}

export const useLicense = ({}: UseLicenseArgs): UseLicenseResult => {
  const isLicenseValid = true;
  const licenseError = null;
  const licenseFeatures = ALL_FEATURES;

  const checkLicenseStatus = useCallback(async () => {
    // No-op since license is bypassed
  }, []);

  return { isLicenseValid, licenseError, licenseFeatures, checkLicenseStatus };
};

