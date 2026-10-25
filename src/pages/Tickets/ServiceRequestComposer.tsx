import React, { useEffect, useMemo, useRef, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import { ActionButton } from '../../components/ui/ActionIconButton';
import { FormSection } from '../../components/ui/FormLayout';
import { SelectField } from '../../components/ui/FormField';
import { TicketDialog, TicketEmptyState, ticketInputClass } from '../../components/tickets/TicketUI';
import type { ServiceCatalogItem, ServiceRequestField } from './types';

export interface ServiceRequestDraft {
  catalog_item_id: string;
  version: number;
  title: string;
  details: Record<string, unknown>;
}

interface ServiceRequestComposerProps {
  open: boolean;
  catalogs: ServiceCatalogItem[];
  loading: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (draft: ServiceRequestDraft) => Promise<void>;
  language: string;
}

const ServiceRequestComposer: React.FC<ServiceRequestComposerProps> = ({ open, catalogs, loading, error, onClose, onSubmit, language }) => {
  const zh = language === 'zh';
  const [catalogId, setCatalogId] = useState('');
  const [title, setTitle] = useState('');
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);
  const wasOpen = useRef(false);
  const selected = useMemo(() => catalogs.find((item) => item.id === catalogId) || catalogs[0], [catalogId, catalogs]);
  const fields: ServiceRequestField[] = selected?.request_schema?.fields || [];

  useEffect(() => {
    if (!open) {
      wasOpen.current = false;
      return;
    }
    if (wasOpen.current) return;
    wasOpen.current = true;
    setCatalogId(catalogs[0]?.id || '');
    setTitle('');
    setValues({});
    setSubmitting(false);
  }, [open, catalogs]);

  if (!open) return null;

  const updateField = (key: string, value: unknown) => setValues((current) => ({ ...current, [key]: value }));
  const renderField = (field: ServiceRequestField) => {
    const value = values[field.key];
    const requiredMark = field.required ? <span className="ml-1 text-[var(--ui-danger)]" aria-hidden="true">*</span> : null;
    const helper = field.help ? <p className="mt-1 text-[var(--ui-text-caption)] leading-4 text-[var(--ui-fg-muted)]">{field.help}</p> : null;

    if (field.type === 'boolean') {
      return (
        <label key={field.key} className="flex min-h-10 items-start gap-2 rounded-lg border border-[var(--ui-border)] px-3 py-2.5 text-[var(--ui-text-body)] text-[var(--ui-fg)]">
          <input type="checkbox" checked={Boolean(value)} onChange={(event) => updateField(field.key, event.target.checked)} className="mt-0.5 accent-[var(--ui-accent)]" />
          <span className="min-w-0">{field.label}{requiredMark}{helper}</span>
        </label>
      );
    }

    const fieldLabel = <span>{field.label}{requiredMark}</span>;
    if (field.type === 'select') {
      return (
        <label key={field.key} className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">
          {fieldLabel}
          <select required={field.required} value={String(value ?? '')} onChange={(event) => updateField(field.key, event.target.value)} className={ticketInputClass}>
            <option value="">{zh ? '请选择' : 'Select'}</option>
            {(field.options || []).map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
          {helper}
        </label>
      );
    }
    if (field.type === 'textarea') {
      return (
        <label key={field.key} className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">
          {fieldLabel}
          <textarea required={field.required} value={String(value ?? '')} onChange={(event) => updateField(field.key, event.target.value)} rows={3} className={`${ticketInputClass} py-2`} />
          {helper}
        </label>
      );
    }
    return (
      <label key={field.key} className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">
        {fieldLabel}
        <input required={field.required} type={field.type === 'number' ? 'number' : 'text'} value={String(value ?? '')} onChange={(event) => updateField(field.key, field.type === 'number' && event.target.value !== '' ? Number(event.target.value) : event.target.value)} className={ticketInputClass} />
        {helper}
      </label>
    );
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selected || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit({
        catalog_item_id: selected.id,
        version: selected.current_version ?? selected.version,
        title: title.trim() || selected.name,
        details: {
          ...values,
          ...Object.fromEntries(fields.filter((field) => field.type === 'boolean').map((field) => [field.key, Boolean(values[field.key])])),
        },
      });
    } finally {
      setSubmitting(false);
    }
  };

  const actions = (
    <>
      <ActionButton onClick={onClose} disabled={submitting}>{zh ? '取消' : 'Cancel'}</ActionButton>
      <ActionButton form="service-request-form" type="submit" variant="primary" disabled={loading || catalogs.length === 0 || submitting} icon={submitting ? LoaderCircle : undefined} iconClassName={submitting ? 'animate-spin' : undefined}>
        {zh ? '提交申请' : 'Submit request'}
      </ActionButton>
    </>
  );

  return (
    <TicketDialog
      title={zh ? '发起服务申请' : 'Request a service'}
      description={zh ? '按当前发布的目录版本填写申请内容。' : 'Use the current published service version.'}
      onClose={onClose}
      closeDisabled={submitting}
      language={language}
      widthClassName={catalogs.length ? "max-w-2xl" : "max-w-md"}
      actions={!loading && catalogs.length === 0 ? <ActionButton onClick={onClose}>{zh ? '关闭' : 'Close'}</ActionButton> : actions}
      bodyClassName="space-y-4"
    >
      {error && <p role="alert" className="rounded-lg border border-[var(--ui-danger)]/30 bg-[var(--ui-danger-subtle)] px-3 py-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]">{error}</p>}
      {loading ? (
        <p role="status" className="flex items-center justify-center gap-2 py-10 text-[var(--ui-text-body)] text-[var(--ui-fg-muted)]"><LoaderCircle size={14} className="animate-spin" />{zh ? '正在读取服务目录…' : 'Loading service catalog…'}</p>
      ) : catalogs.length === 0 ? (
        <TicketEmptyState compact title={zh ? '当前没有可申请的服务。' : 'No services are available to request.'} />
      ) : (
        <form id="service-request-form" onSubmit={submit} className="space-y-4">
          <FormSection title={zh ? '申请信息' : 'Request details'} contentClassName="grid gap-3 sm:grid-cols-2">
            <SelectField
              label={zh ? '服务项目' : 'Service'}
              value={selected?.id || ''}
              onChange={(value) => { setCatalogId(value); setTitle(''); setValues({}); }}
              options={catalogs.map((item) => ({ value: item.id, label: item.name }))}
              language={zh ? 'zh' : 'en'}
            />
            <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">
              {zh ? '申请标题' : 'Request title'}
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={selected?.name || ''} maxLength={240} className={ticketInputClass} />
            </label>
            {selected && (
              <div className="sm:col-span-2 rounded-lg bg-[var(--ui-surface-muted)] px-3 py-2 text-[var(--ui-text-caption)] leading-4 text-[var(--ui-fg-muted)]">
                <p>{selected.description || (zh ? '暂无服务说明。' : 'No service description.')}</p>
                <p className="mt-1">{zh ? `目录版本 v${selected.current_version ?? selected.version}` : `Catalog version v${selected.current_version ?? selected.version}`}{selected.requires_approval ? (zh ? ' · 需要审批' : ' · Approval required') : ''}</p>
              </div>
            )}
          </FormSection>

          <FormSection title={zh ? '申请字段' : 'Requested information'} description={zh ? '仅填写此服务要求的信息。' : 'Complete the fields required for this service.'} contentClassName="grid gap-3 sm:grid-cols-2">
            {fields.length ? fields.map(renderField) : <p className="sm:col-span-2 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '此服务暂不要求补充字段。' : 'This service has no additional request fields.'}</p>}
          </FormSection>
        </form>
      )}
    </TicketDialog>
  );
};

export default ServiceRequestComposer;
