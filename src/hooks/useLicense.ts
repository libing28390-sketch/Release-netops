import { useCallback, useEffect, useState } from 'react';
import type { NavigateFunction, Location } from 'react-router-dom';
import type { Language } from '../i18n.tsx';

/**
 * Tab → required feature mapping.
 * Must stay in sync with backend `middleware._FEATURE_REQUIRED`.
 */
const TAB_FEATURE_MAP: Record<string, string> = {
  automation: 'automation',
  config: 'config_management',
  monitoring: 'monitoring',
  overview: 'monitoring',
  alerts: 'alerting',
  'alert-history': 'alerting',
  'alert-rules': 'alerting',
  maintenance: 'alerting',
  topology: 'topology',
  ipam: 'ipam',
  capacity: 'capacity',
  reports: 'reports',
  compliance: 'compliance',
  inspections: 'inspections',
  'change-orders': 'change_orders',
  access: 'access_center',
  pam: 'access_center',
  'pam-audit': 'access_center',
  'scheduled-jobs': 'scheduled_jobs',
  credentials: 'password_rotation',
  audit: 'rbac',
};

const BASIC_ALLOWED_TABS = ['dashboard', 'inventory', 'monitoring', 'topology', 'license', 'health', 'setup'];

const POLL_INTERVAL_MS = 60_000;

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

export const useLicense = ({
  isAuthenticated,
  activeTab,
  language,
  navigate,
  location,
  showToast,
}: UseLicenseArgs): UseLicenseResult => {
  const [isLicenseValid, setIsLicenseValid] = useState(true);
  const [licenseError, setLicenseError] = useState<string | null>(null);
  const [licenseFeatures, setLicenseFeatures] = useState<string[]>([]);

  const checkLicenseStatus = useCallback(async () => {
    try {
      const token = localStorage.getItem('netops_token');
      const resp = await fetch('/api/license/status', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (resp.ok) {
        const data = await resp.json();
        setIsLicenseValid(data.valid);
        setLicenseError(data.error || null);
        setLicenseFeatures(data.features || []);
      }
    } catch {
      // ignore network errors; the next poll will retry.
    }
  }, []);

  // Poll license status every 60s while authenticated.
  useEffect(() => {
    if (!isAuthenticated) return;
    checkLicenseStatus();
    const timer = setInterval(checkLicenseStatus, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isAuthenticated, checkLicenseStatus]);

  // Enforce license/feature gating on tab change.
  useEffect(() => {
    if (!isAuthenticated) return;

    if (!isLicenseValid) {
      if (!BASIC_ALLOWED_TABS.includes(activeTab)) {
        showToast(
          language === 'zh'
            ? '该功能属于高级特性，请激活有效授权以继续使用'
            : 'This is an advanced feature. Please activate a valid license to continue.',
          'info',
        );
        navigate('/license');
      }
      return;
    }

    const requiredFeature = TAB_FEATURE_MAP[activeTab];
    if (requiredFeature && licenseFeatures.length > 0 && !licenseFeatures.includes(requiredFeature)) {
      showToast(
        language === 'zh'
          ? `功能「${requiredFeature}」未在您的授权范围内，请升级 License`
          : `Feature '${requiredFeature}' is not included in your license. Please upgrade.`,
        'info',
      );
      navigate('/license');
    }

    if (location.pathname === '/history') {
      navigate('/audit', { replace: true });
    }
  }, [
    isAuthenticated,
    isLicenseValid,
    licenseFeatures,
    activeTab,
    navigate,
    location.pathname,
    showToast,
    language,
  ]);

  return { isLicenseValid, licenseError, licenseFeatures, checkLicenseStatus };
};
