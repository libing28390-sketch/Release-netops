import React from 'react';
import { Cpu } from 'lucide-react';
import PageHero from '../components/PageHero';
import MetricOidProfilesModal from '../components/DeviceList/MetricOidProfilesModal';

interface SnmpMetricTemplatesTabProps {
  language: string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
}

const SnmpMetricTemplatesTab: React.FC<SnmpMetricTemplatesTabProps> = ({ language, showToast }) => {
  const zh = language === 'zh';

  return (
    <div className="flex h-full min-h-0 flex-col" style={{ background: 'var(--main-bg)' }}>
      <PageHero
        icon={Cpu}
        title={zh ? 'SNMP 指标模板' : 'SNMP Metric Templates'}
        subtitle={zh ? '按资产管理厂商和精确型号管理 CPU、内存、温度、风扇、电源及其他硬件指标，校验通过后才会被采集器调用。' : 'Manage CPU, memory, temperature, fan, PSU, and other hardware metrics by shared vendor and exact model; only verified definitions are used by collectors.'}
        eyebrow={zh ? '平台管理' : 'PLATFORM MANAGEMENT'}
        accent="#0891b2"
        className="!px-4 !pt-3 !pb-3"
      />

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
