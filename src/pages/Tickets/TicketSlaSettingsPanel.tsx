import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { LoaderCircle, Plus, X } from 'lucide-react';
import { ActionButton, ActionIconButton } from '../../components/ui/ActionIconButton';
import { FormSection } from '../../components/ui/FormLayout';
import { SelectField, TextField } from '../../components/ui/FormField';
import { TicketDialog, ticketInputClass } from '../../components/tickets/TicketUI';
import { getTicketSlaPolicies, getTicketWorkCalendars, saveTicketSlaPolicy, saveTicketWorkCalendar } from './api';
import type { TicketSlaPolicy, TicketSourceType, TicketWorkCalendar } from './types';

interface TicketSlaSettingsPanelProps {
  open: boolean;
  onClose: () => void;
  language: string;
}

type DayName = 'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday';
type TimeWindow = { start: string; end: string };
const days: Array<{ key: DayName; zh: string; en: string }> = [
  { key: 'monday', zh: '周一', en: 'Mon' }, { key: 'tuesday', zh: '周二', en: 'Tue' },
  { key: 'wednesday', zh: '周三', en: 'Wed' }, { key: 'thursday', zh: '周四', en: 'Thu' },
  { key: 'friday', zh: '周五', en: 'Fri' }, { key: 'saturday', zh: '周六', en: 'Sat' },
  { key: 'sunday', zh: '周日', en: 'Sun' },
];
const emptySchedule = (): Record<DayName, TimeWindow[]> => ({ monday: [], tuesday: [], wednesday: [], thursday: [], friday: [], saturday: [], sunday: [] });

const TicketSlaSettingsPanel: React.FC<TicketSlaSettingsPanelProps> = ({ open, onClose, language }) => {
  const zh = language === 'zh';
  const [tab, setTab] = useState<'policies' | 'calendars'>('policies');
  const [policies, setPolicies] = useState<TicketSlaPolicy[]>([]);
  const [calendars, setCalendars] = useState<TicketWorkCalendar[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [selectedPolicyId, setSelectedPolicyId] = useState('');
  const [policyId, setPolicyId] = useState('');
  const [policyName, setPolicyName] = useState('');
  const [policySource, setPolicySource] = useState<TicketSourceType>('service_request');
  const [policyPriority, setPolicyPriority] = useState<TicketSlaPolicy['priority']>('P3');
  const [responseMinutes, setResponseMinutes] = useState('');
  const [restoreMinutes, setRestoreMinutes] = useState('');
  const [fulfillmentMinutes, setFulfillmentMinutes] = useState('');
  const [warningBeforeMinutes, setWarningBeforeMinutes] = useState('');
  const [policyCalendarId, setPolicyCalendarId] = useState('');
  const [selectedCalendarId, setSelectedCalendarId] = useState('');
  const [calendarId, setCalendarId] = useState('');
  const [calendarName, setCalendarName] = useState('');
  const [calendarTimezone, setCalendarTimezone] = useState('Asia/Shanghai');
  const [schedule, setSchedule] = useState<Record<DayName, TimeWindow[]>>(emptySchedule);
  const [holidayText, setHolidayText] = useState('');

  const selectedPolicy = useMemo(() => policies.find((policy) => policy.id === selectedPolicyId), [policies, selectedPolicyId]);
  const selectedCalendar = useMemo(() => calendars.find((calendar) => calendar.id === selectedCalendarId), [calendars, selectedCalendarId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [policyRows, calendarRows] = await Promise.all([getTicketSlaPolicies(), getTicketWorkCalendars()]);
      setPolicies(policyRows.filter((policy) => policy.active !== false));
      setCalendars(calendarRows);
      setSelectedPolicyId((current) => current || policyRows[0]?.id || '');
      setSelectedCalendarId((current) => current || calendarRows[0]?.id || '');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '时限配置读取失败' : 'Unable to load service targets'));
    } finally {
      setLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  useEffect(() => {
    if (!open || !selectedPolicy) return;
    setPolicyId(selectedPolicy.id);
    setPolicyName(selectedPolicy.name);
    setPolicySource(selectedPolicy.source_type);
    setPolicyPriority(selectedPolicy.priority);
    setResponseMinutes(selectedPolicy.response_target_minutes == null ? '' : String(selectedPolicy.response_target_minutes));
    setRestoreMinutes(selectedPolicy.restore_target_minutes == null ? '' : String(selectedPolicy.restore_target_minutes));
    setFulfillmentMinutes(selectedPolicy.fulfillment_target_minutes == null ? '' : String(selectedPolicy.fulfillment_target_minutes));
    setWarningBeforeMinutes(selectedPolicy.warning_before_minutes == null ? '' : String(selectedPolicy.warning_before_minutes));
    setPolicyCalendarId(selectedPolicy.calendar_version_id || '');
  }, [open, selectedPolicy]);

  useEffect(() => {
    if (!open || !selectedCalendar) return;
    const next = emptySchedule();
    for (const day of days) next[day.key] = [...(selectedCalendar.schedule?.[day.key] || [])].map((window) => ({ ...window }));
    setCalendarId(selectedCalendar.id);
    setCalendarName(selectedCalendar.name);
    setCalendarTimezone(selectedCalendar.timezone || '');
    setSchedule(next);
    setHolidayText((selectedCalendar.holidays || []).join('\n'));
  }, [open, selectedCalendar]);

  if (!open) return null;

  const startNewPolicy = () => {
    setSelectedPolicyId(''); setPolicyId(''); setPolicyName(''); setPolicySource('service_request'); setPolicyPriority('P3');
    setResponseMinutes(''); setRestoreMinutes(''); setFulfillmentMinutes(''); setWarningBeforeMinutes(''); setPolicyCalendarId(''); setError('');
  };
  const startNewCalendar = () => {
    setSelectedCalendarId(''); setCalendarId(''); setCalendarName(''); setCalendarTimezone('');
    setSchedule(emptySchedule()); setHolidayText(''); setError('');
  };
  const updateDayWindows = (day: DayName, windows: TimeWindow[]) => setSchedule((current) => ({ ...current, [day]: windows }));

  const submitPolicy = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!policyName.trim() || saving) return;
    const selectedPolicyCalendar = calendars.find((calendar) => calendar.version_id === policyCalendarId);
    if (!selectedPolicyCalendar) {
      setError(zh ? '请先选择一个工作日历。' : 'Select a work calendar.');
      return;
    }
    if (!Object.values(selectedPolicyCalendar.schedule || {}).some((windows) => windows.length > 0)) {
      setError(zh ? '所选日历没有工作时段，无法用于计时策略。' : 'The selected calendar has no working hours and cannot be used for an SLA target.');
      return;
    }
    const target = (value: string) => value.trim() ? Number(value) : undefined;
    if (![responseMinutes, restoreMinutes, fulfillmentMinutes].some((value) => value.trim() && Number(value) > 0)) {
      setError(zh ? '请至少设置一个正数服务时限。' : 'Enter at least one positive service target.');
      return;
    }
    setSaving(true); setError('');
    try {
      const policy = await saveTicketSlaPolicy({
        ...(policyId ? { id: policyId } : {}),
        name: policyName.trim(), source_type: policySource, priority: policyPriority,
        ...(target(responseMinutes) != null ? { response_target_minutes: target(responseMinutes) } : {}),
        ...(target(restoreMinutes) != null ? { restore_target_minutes: target(restoreMinutes) } : {}),
        ...(target(fulfillmentMinutes) != null ? { fulfillment_target_minutes: target(fulfillmentMinutes) } : {}),
        ...(target(warningBeforeMinutes) != null ? { warning_before_minutes: target(warningBeforeMinutes) } : {}),
        ...(policyCalendarId ? { calendar_version_id: policyCalendarId } : {}),
      });
      const rows = (await getTicketSlaPolicies()).filter((row) => row.active !== false);
      setPolicies(rows); setSelectedPolicyId(policy.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '保存时限策略失败' : 'Unable to save service target'));
    } finally { setSaving(false); }
  };

  const submitCalendar = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!calendarName.trim() || !calendarTimezone.trim() || saving) return;
    const holidays = holidayText.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
    setSaving(true); setError('');
    try {
      const calendar = await saveTicketWorkCalendar({
        ...(calendarId ? { id: calendarId } : {}), name: calendarName.trim(), timezone: calendarTimezone.trim(), schedule, holidays,
      });
      const rows = await getTicketWorkCalendars();
      setCalendars(rows); setSelectedCalendarId(calendar.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '保存工作日历失败' : 'Unable to save calendar'));
    } finally { setSaving(false); }
  };

  const groupLabel = (key: 'policies' | 'calendars') => key === 'policies' ? (zh ? '时限策略' : 'Targets') : (zh ? '工作日历' : 'Calendars');
  const isPolicyTab = tab === 'policies';
  const formatGroupOption = (group: TicketWorkCalendar) => `${group.name} · v${group.version}`;

  return (
    <TicketDialog
      title={zh ? '工单时限设置' : 'Ticket targets'}
      description={zh ? '只对显式配置的策略计时；新版本不修改既有工单的时限快照。' : 'Only configured policies create timers. New versions do not change existing ticket snapshots.'}
      onClose={onClose}
      closeDisabled={saving}
      language={language}
      widthClassName="max-w-5xl"
      className="!max-h-[94vh]"
      actions={<>
        <ActionButton onClick={onClose} disabled={saving}>{zh ? '关闭' : 'Close'}</ActionButton>
        <ActionButton type="submit" form={isPolicyTab ? 'ticket-sla-policy-form' : 'ticket-work-calendar-form'} variant="primary" disabled={loading || saving || (isPolicyTab ? (!policyName.trim() || !policyCalendarId) : (!calendarName.trim() || !calendarTimezone.trim()))} icon={saving ? LoaderCircle : undefined} iconClassName={saving ? 'animate-spin' : undefined}>{isPolicyTab ? (policyId ? (zh ? '发布新版本' : 'Publish version') : (zh ? '创建策略' : 'Create target')) : (calendarId ? (zh ? '发布新版本' : 'Publish version') : (zh ? '创建日历' : 'Create calendar'))}</ActionButton>
      </>}
      bodyClassName="!flex !min-h-0 !flex-col !overflow-hidden !p-0"
    >
      <div className="flex min-h-0 flex-1 flex-col">
        <nav aria-label={zh ? '时限设置分区' : 'Target settings sections'} className="flex shrink-0 gap-1 border-b border-[var(--ui-border)] px-4 py-2 sm:px-5">
          {(['policies', 'calendars'] as const).map((key) => <button key={key} type="button" aria-pressed={tab === key} onClick={() => { setTab(key); setError(''); }} className={`min-h-8 rounded-lg px-3 text-[var(--ui-text-label)] font-semibold ${tab === key ? 'bg-[var(--ui-accent)] text-white' : 'text-[var(--ui-fg-muted)] hover:bg-[var(--ui-surface-muted)]'}`}>{groupLabel(key)}</button>)}
        </nav>
        {loading ? (
          <p role="status" className="flex min-h-64 flex-1 items-center justify-center gap-2 text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]"><LoaderCircle size={14} className="animate-spin" />{zh ? '正在加载配置…' : 'Loading settings…'}</p>
        ) : (
          <div className="grid min-h-0 flex-1 gap-4 overflow-auto p-4 lg:grid-cols-[220px_minmax(0,1fr)] sm:p-5">
            <aside className="min-w-0 space-y-2">
              <ActionButton onClick={isPolicyTab ? startNewPolicy : startNewCalendar} className="w-full justify-center" icon={Plus}>{zh ? '新建配置' : 'New configuration'}</ActionButton>
              {isPolicyTab ? (
                policies.length ? policies.map((policy) => <button key={`${policy.id}-${policy.version}`} type="button" aria-pressed={selectedPolicyId === policy.id} onClick={() => setSelectedPolicyId(policy.id)} className={`block w-full min-w-0 rounded-lg border px-3 py-2 text-left ${selectedPolicyId === policy.id ? 'border-[var(--ui-accent)] bg-[var(--ui-accent-subtle)]' : 'border-[var(--ui-border)] hover:bg-[var(--ui-surface-muted)]'}`}><span className="block truncate text-[var(--ui-text-body)] font-semibold text-[var(--ui-fg)]">{policy.name}</span><span className="mt-0.5 block truncate text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{policy.source_type === 'incident' ? (zh ? '故障' : 'Incident') : (zh ? '服务申请' : 'Service request')} · {policy.priority} · v{policy.version}</span></button>) : <p className="px-1 py-3 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '尚未配置工单时限。' : 'No ticket targets configured.'}</p>
              ) : (
                calendars.length ? calendars.map((calendar) => <button key={`${calendar.id}-${calendar.version}`} type="button" aria-pressed={selectedCalendarId === calendar.id} onClick={() => setSelectedCalendarId(calendar.id)} className={`block w-full min-w-0 rounded-lg border px-3 py-2 text-left ${selectedCalendarId === calendar.id ? 'border-[var(--ui-accent)] bg-[var(--ui-accent-subtle)]' : 'border-[var(--ui-border)] hover:bg-[var(--ui-surface-muted)]'}`}><span className="block truncate text-[var(--ui-text-body)] font-semibold text-[var(--ui-fg)]">{calendar.name}</span><span className="mt-0.5 block truncate text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{calendar.timezone} · v{calendar.version}</span></button>) : <p className="px-1 py-3 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '尚未配置工作日历。' : 'No work calendars configured.'}</p>
              )}
            </aside>

            {isPolicyTab ? (
              <form id="ticket-sla-policy-form" onSubmit={submitPolicy} className="min-w-0 space-y-3">
                <FormSection title={zh ? '策略范围' : 'Target scope'} contentClassName="grid gap-3 sm:grid-cols-2">
                  <TextField label={zh ? '策略名称' : 'Target name'} value={policyName} onChange={setPolicyName} disabled={saving} />
                  <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '工单类型' : 'Ticket type'}<select value={policySource} onChange={(event) => setPolicySource(event.target.value as TicketSourceType)} className={ticketInputClass}><option value="incident">{zh ? '故障工单' : 'Incident'}</option><option value="service_request">{zh ? '服务申请' : 'Service request'}</option></select></label>
                  <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '优先级' : 'Priority'}<select value={policyPriority} onChange={(event) => setPolicyPriority(event.target.value as TicketSlaPolicy['priority'])} className={ticketInputClass}>{(['P1', 'P2', 'P3', 'P4'] as const).map((priority) => <option key={priority} value={priority}>{priority}</option>)}</select></label>
                  <SelectField label={zh ? '工作日历' : 'Work calendar'} value={policyCalendarId} onChange={setPolicyCalendarId} options={calendars.map((calendar) => ({ value: calendar.version_id, label: formatGroupOption(calendar) }))} language={zh ? 'zh' : 'en'} placeholder={zh ? '请选择工作日历' : 'Select a work calendar'} disabled={saving} />
                </FormSection>
                <FormSection title={zh ? '服务时限' : 'Service targets'} description={zh ? '留空的目标不计时；请仅填写已确认的服务时限。' : 'Blank targets do not start a clock. Enter approved targets only.'} contentClassName="grid gap-3 sm:grid-cols-2">
                  <TextField label={zh ? '首次响应目标（分钟）' : 'First response (minutes)'} type="number" min={1} step={1} value={responseMinutes} onChange={setResponseMinutes} placeholder={zh ? '未配置' : 'Not configured'} disabled={saving} />
                  <TextField label={zh ? '故障恢复目标（分钟）' : 'Restoration target (minutes)'} type="number" min={1} step={1} value={restoreMinutes} onChange={setRestoreMinutes} placeholder={zh ? '未配置' : 'Not configured'} disabled={saving} />
                  <TextField label={zh ? '申请履约目标（分钟）' : 'Fulfillment target (minutes)'} type="number" min={1} step={1} value={fulfillmentMinutes} onChange={setFulfillmentMinutes} placeholder={zh ? '未配置' : 'Not configured'} disabled={saving} />
                  <TextField label={zh ? '临近超时提醒（提前分钟）' : 'Near-due reminder (minutes before)'} type="number" min={1} step={1} value={warningBeforeMinutes} onChange={setWarningBeforeMinutes} placeholder={zh ? '不提前提醒' : 'No early reminder'} disabled={saving} />
                </FormSection>
                {error && <p role="alert" className="rounded-lg border border-[var(--ui-danger)] bg-[var(--ui-danger-subtle)] px-3 py-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]">{error}</p>}
              </form>
            ) : (
              <form id="ticket-work-calendar-form" onSubmit={submitCalendar} className="min-w-0 space-y-3">
                <FormSection title={zh ? '日历信息' : 'Calendar details'} contentClassName="grid gap-3 sm:grid-cols-2">
                  <TextField label={zh ? '日历名称' : 'Calendar name'} value={calendarName} onChange={setCalendarName} disabled={saving} />
                  <TextField label={zh ? '时区' : 'Time zone'} value={calendarTimezone} onChange={setCalendarTimezone} placeholder="Asia/Shanghai" disabled={saving} />
                </FormSection>
                <FormSection title={zh ? '每周工作时间' : 'Weekly working hours'} description={zh ? '可为一天添加多个工作时段。' : 'Add more than one work period when needed.'} contentClassName="!pt-2">
                  <div className="divide-y divide-[var(--ui-border)]">
                    {days.map((day) => <div key={day.key} className="grid gap-2 py-2 first:pt-0 sm:grid-cols-[70px_minmax(0,1fr)] sm:items-start">
                      <div className="flex items-center justify-between gap-2 sm:pt-2"><span className="text-[var(--ui-text-label)] font-semibold text-[var(--ui-fg)]">{zh ? day.zh : day.en}</span><ActionButton size="sm" onClick={() => updateDayWindows(day.key, [...schedule[day.key], { start: '', end: '' }])} disabled={saving} icon={Plus}>{zh ? '添加' : 'Add'}</ActionButton></div>
                      <div className="space-y-1.5">
                        {schedule[day.key].map((window, index) => <div key={`${day.key}-${index}`} className="flex min-w-0 items-center gap-2">
                          <input aria-label={`${day.key} ${zh ? '开始' : 'start'} ${index + 1}`} type="text" inputMode="numeric" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" placeholder="09:00" required disabled={saving} value={window.start} onChange={(event) => updateDayWindows(day.key, schedule[day.key].map((row, rowIndex) => rowIndex === index ? { ...row, start: event.target.value } : row))} className={`${ticketInputClass} min-w-0 w-auto flex-1`} />
                          <span aria-hidden="true" className="shrink-0 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">—</span>
                          <input aria-label={`${day.key} ${zh ? '结束' : 'end'} ${index + 1}`} type="text" inputMode="numeric" pattern="([01][0-9]|2[0-3]):[0-5][0-9]|24:00" placeholder="17:00" title={zh ? '支持 00:00 至 24:00' : 'Use a time from 00:00 to 24:00'} required disabled={saving} value={window.end} onChange={(event) => updateDayWindows(day.key, schedule[day.key].map((row, rowIndex) => rowIndex === index ? { ...row, end: event.target.value } : row))} className={`${ticketInputClass} min-w-0 w-auto flex-1`} />
                          <ActionIconButton icon={X} label={`${zh ? '移除时段' : 'Remove hours'} ${day.key} ${index + 1}`} variant="danger" disabled={saving} onClick={() => updateDayWindows(day.key, schedule[day.key].filter((_, rowIndex) => rowIndex !== index))} />
                        </div>)}
                        {schedule[day.key].length === 0 && <p className="py-2 text-[var(--ui-text-caption)] text-[var(--ui-fg-subtle)]">{zh ? '休息日' : 'Closed'}</p>}
                      </div>
                    </div>)}
                  </div>
                </FormSection>
                <FormSection title={zh ? '节假日' : 'Holidays'} description={zh ? '每行填写一个日期，格式 YYYY-MM-DD。' : 'Enter one YYYY-MM-DD date per line.'} contentClassName="!pt-2">
                  <TextField label={zh ? '节假日日期' : 'Holiday dates'} value={holidayText} onChange={setHolidayText} multiline rows={3} placeholder="2026-10-01" disabled={saving} />
                </FormSection>
                {error && <p role="alert" className="rounded-lg border border-[var(--ui-danger)] bg-[var(--ui-danger-subtle)] px-3 py-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]">{error}</p>}
              </form>
            )}
          </div>
        )}
      </div>
    </TicketDialog>
  );
};

export default TicketSlaSettingsPanel;
