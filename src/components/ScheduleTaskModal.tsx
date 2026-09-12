import React from 'react';
import { XCircle } from 'lucide-react';
import { motion } from 'motion/react';
import type { Device } from '../types';
import DateTimePicker from './DateTimePicker';

type ScheduleType = 'once' | 'recurring';
type ScheduleInterval = 'daily' | 'weekly' | 'monthly';

export interface ScheduleFormState {
  type: ScheduleType;
  interval: ScheduleInterval;
  time: string;
  timezone: string;
}

interface ScheduleTaskModalProps {
  open: boolean;
  language: string;
  t: (key: string) => string;
  selectedDevice: Device | null;
  schedulingTask: string | null;
  scheduleForm: ScheduleFormState;
  onScheduleFormChange: (next: ScheduleFormState) => void;
  onClose: () => void;
  onSubmit: () => void;
}

const ScheduleTaskModal: React.FC<ScheduleTaskModalProps> = ({
  open,
  language,
  t,
  selectedDevice,
  schedulingTask,
  scheduleForm,
  onScheduleFormChange,
  onClose,
  onSubmit,
}) => {
  if (!open || !schedulingTask) return null;

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="bg-white rounded-2xl w-full max-w-md shadow-2xl overflow-hidden"
      >
        <div className="p-6 border-b border-black/5 flex justify-between items-center bg-black/5">
          <div>
            <h3 className="text-lg font-medium">{t('scheduleTask')}</h3>
            <p className="text-xs text-black/40">{schedulingTask} for {selectedDevice?.hostname}</p>
          </div>
          <button onClick={onClose} title={language === 'zh' ? '关闭定时任务窗口' : 'Close schedule dialog'} className="text-black/40 hover:text-black">
            <XCircle size={24} />
          </button>
        </div>

        <div className="p-6 space-y-6">
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase text-black/40">{t('scheduleType')}</label>
            <div className="flex gap-2">
              {(['once', 'recurring'] as const).map((type) => (
                <button
                  key={type}
                  onClick={() => onScheduleFormChange({ ...scheduleForm, type })}
                  className={`flex-1 py-2 rounded-xl text-xs font-medium border transition-all ${
                    scheduleForm.type === type
                      ? 'bg-black text-white border-black'
                      : 'bg-white text-black/60 border-black/10 hover:border-black/20'
                  }`}
                >
                  {t(type)}
                </button>
              ))}
            </div>
          </div>

          {scheduleForm.type === 'recurring' && (
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase text-black/40">{t('interval')}</label>
              <select
                value={scheduleForm.interval}
                onChange={(event) => onScheduleFormChange({ ...scheduleForm, interval: event.target.value as ScheduleInterval })}
                title={language === 'zh' ? '计划周期' : 'Schedule interval'}
                className="w-full px-4 py-2 bg-black/[0.02] border border-black/10 rounded-xl text-xs outline-none focus:border-black/20"
              >
                <option value="daily">{t('daily')}</option>
                <option value="weekly">{t('weekly')}</option>
                <option value="monthly">{t('monthly')}</option>
              </select>
            </div>
          )}

          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase text-black/40">{t('scheduledTime')}</label>
            <DateTimePicker
              value={scheduleForm.time}
              onChange={(v) => onScheduleFormChange({ ...scheduleForm, time: v })}
              language={language}
            />
          </div>

          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase text-black/40">{t('timezone')}</label>
            <select
              value={scheduleForm.timezone}
              onChange={(event) => onScheduleFormChange({ ...scheduleForm, timezone: event.target.value })}
              title={language === 'zh' ? '时区' : 'Timezone'}
              className="w-full px-4 py-2 bg-black/[0.02] border border-black/10 rounded-xl text-xs outline-none focus:border-black/20"
            >
              <option value="UTC">UTC</option>
              <option value="PST">PST (UTC-8)</option>
              <option value="EST">EST (UTC-5)</option>
              <option value="CST">CST (UTC+8)</option>
            </select>
          </div>
        </div>

        <div className="p-6 bg-white border-t border-black/5 flex justify-end gap-4">
          <button onClick={onClose} className="px-6 py-2 text-sm font-medium text-black/60 hover:text-black">
            {t('cancel')}
          </button>
          <button onClick={onSubmit} className="px-8 py-2 bg-black text-white rounded-xl text-sm font-medium hover:bg-black/80 transition-all shadow-lg shadow-black/20">
            {t('schedule')}
          </button>
        </div>
      </motion.div>
    </div>
  );
};

export default ScheduleTaskModal;