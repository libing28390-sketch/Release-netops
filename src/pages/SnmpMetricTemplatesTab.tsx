import React from 'react';
import MetricOidProfilesModal from '../components/DeviceList/MetricOidProfilesModal';

interface SnmpMetricTemplatesTabProps {
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const SnmpMetricTemplatesTab: React.FC<SnmpMetricTemplatesTabProps> = ({ language, showToast }) => {
  return (
    <div className="flex h-full min-h-0 flex-col" style={{ background: 'var(--main-bg)' }}>
      <div className="min-h-0 flex-1 overflow-hidden p-4 md:p-5">
        <MetricOidProfilesModal
          open
          embedded
          onClose={() => undefined}
          language={language}
          showToast={showToast}
        />
      </div>
    </div>
  );
};

export default SnmpMetricTemplatesTab;
