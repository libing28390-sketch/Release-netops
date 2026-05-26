import React from 'react';
import ExecutionScheduleCoordinator from './ExecutionSchedule';
import type { Device } from '../types';

interface ExecutionScheduleTabProps {
  t: (key: string) => string;
  language: string;
  showToast: (msg: string, type?: 'success' | 'error' | 'info') => void;
  initialTab?: 'schedules' | 'history';
  devices: Device[];
  onRerun?: (log: any) => void;
}

const ExecutionScheduleTab: React.FC<ExecutionScheduleTabProps> = (props) => {
  return <ExecutionScheduleCoordinator {...props} />;
};

export default ExecutionScheduleTab;
