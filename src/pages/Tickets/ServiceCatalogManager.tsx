import React, { useCallback, useEffect, useState } from 'react';
import { FilePlus2, LoaderCircle, Plus, Trash2 } from 'lucide-react';
import { ActionButton, ActionIconButton } from '../../components/ui/ActionIconButton';
import { FormSection } from '../../components/ui/FormLayout';
import { SelectField, TextField } from '../../components/ui/FormField';
import { TicketDialog, TicketEmptyState, ticketInputClass } from '../../components/tickets/TicketUI';
import { createServiceCatalogItem, createServiceCatalogVersion, getServiceCatalog, getTicketSlaPolicies } from './api';
import type { ServiceCatalogItem, ServiceCatalogFieldType, ServiceRequestField, TicketAssignmentGroup, TicketSlaPolicy } from './types';

interface ServiceCatalogManagerProps {
  open: boolean;
  groups: TicketAssignmentGroup[];
  onClose: () => void;
  onSaved: () => void;
  language: string;
}

const fieldTypes: ServiceCatalogFieldType[] = ['text', 'textarea', 'number', 'select', 'boolean'];

const ServiceCatalogManager: React.FC<ServiceCatalogManagerProps> = ({ open, groups, onClose, onSaved, language }) => {
  const zh = language === 'zh';
  const [catalogs, setCatalogs] = useState<ServiceCatalogItem[]>([]);
  const [policies, setPolicies] = useState<TicketSlaPolicy[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [key, setKey] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [requiresApproval, setRequiresApproval] = useState(false);
  const [assignmentGroupId, setAssignmentGroupId] = useState('');
  const [approvalGroupId, setApprovalGroupId] = useState('');
  const [deliveryInstructions, setDeliveryInstructions] = useState('');
  const [acceptanceCriteria, setAcceptanceCriteria] = useState('');
  const [slaPolicyId, setSlaPolicyId] = useState('');
  const [fields, setFields] = useState<Array<ServiceRequestField & { optionsText?: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [catalogRows, policyRows] = await Promise.all([getServiceCatalog(), getTicketSlaPolicies()]);
      setCatalogs(catalogRows);
      setPolicies(policyRows.filter((policy) => policy.active !== false));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '服务目录读取失败' : 'Unable to load service catalog'));
    } finally {
      setLoading(false);
    }
  }, [zh]);

  useEffect(() => { if (open) void refresh(); }, [open, refresh]);

  useEffect(() => {
    if (!selectedId) return;
    const item = catalogs.find((candidate) => candidate.id === selectedId);
    if (!item) return;
    setKey(item.key); setName(item.name); setDescription(item.description || '');
    setRequiresApproval(Boolean(item.requires_approval));
    setAssignmentGroupId(item.assignment_group_id || ''); setApprovalGroupId(item.approval_group_id || '');
    setDeliveryInstructions(item.fulfillment_instructions || ''); setAcceptanceCriteria(item.acceptance_criteria || '');
    setSlaPolicyId(item.sla_policy_version_id || '');
    setFields((item.request_schema?.fields || []).map((field) => ({ ...field, optionsText: field.options?.join(', ') || '' })));
    setError('');
  }, [selectedId, catalogs]);

  if (!open) return null;

  const startNew = () => {
    setSelectedId(''); setKey(''); setName(''); setDescription(''); setRequiresApproval(false);
    setAssignmentGroupId(''); setApprovalGroupId(''); setDeliveryInstructions(''); setAcceptanceCriteria('');
    setSlaPolicyId(''); setFields([]); setError('');
  };
  const updateField = (index: number, patch: Partial<ServiceRequestField & { optionsText?: string }>) => setFields((current) => current.map((field, fieldIndex) => fieldIndex === index ? { ...field, ...patch } : field));
  const addField = () => setFields((current) => [...current, { key: '', label: '', type: 'text', required: false, options: [], optionsText: '' }]);
  const removeField = (index: number) => setFields((current) => current.filter((_, fieldIndex) => fieldIndex !== index));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (saving) return;
    if (!name.trim() || (!selectedId && !key.trim())) { setError(zh ? '请填写服务编号和名称。' : 'Enter a service key and name.'); return; }
    const fulfillmentGroup = groups.find((group) => group.id === assignmentGroupId);
    if (!fulfillmentGroup) { setError(zh ? '请选择履约责任组。' : 'Select a fulfillment group.'); return; }
    if (fulfillmentGroup.member_count === 0) { setError(zh ? '履约责任组没有有效成员，请先添加成员。' : 'The fulfillment group has no active members. Add a member first.'); return; }
    if (requiresApproval && !approvalGroupId) { setError(zh ? '该服务需要审批，请选择审批组。' : 'Choose an approval group for this service.'); return; }
    if (requiresApproval && groups.find((group) => group.id === approvalGroupId)?.member_count === 0) { setError(zh ? '审批组没有有效成员，请先添加成员。' : 'The approval group has no active members. Add a member first.'); return; }
    const normalizedFields = fields.map((field) => ({
      key: field.key.trim(), label: field.label.trim(), type: field.type, required: Boolean(field.required),
      ...(field.type === 'select' ? { options: (field.optionsText || field.options?.join(',') || '').split(',').map((item) => item.trim()).filter(Boolean) } : {}),
    }));
    if (normalizedFields.some((field) => !field.key || !field.label)) { setError(zh ? '每个申请字段都需要填写字段键和名称。' : 'Each request field needs a key and label.'); return; }
    const duplicateKey = normalizedFields.find((field, index) => normalizedFields.some((other, otherIndex) => otherIndex !== index && other.key === field.key));
    if (duplicateKey) { setError(zh ? `申请字段键“${duplicateKey.key}”重复。` : `Duplicate request field key: ${duplicateKey.key}`); return; }
    if (normalizedFields.some((field) => field.type === 'select' && !field.options?.length)) { setError(zh ? '下拉字段至少需要一个选项。' : 'Each select field needs at least one option.'); return; }
    setSaving(true); setError('');
    try {
      let catalogId = selectedId;
      if (!catalogId) {
        const item = await createServiceCatalogItem({ key: key.trim(), name: name.trim(), description: description.trim() });
        catalogId = item.id;
        setSelectedId(catalogId);
      }
      await createServiceCatalogVersion(catalogId, {
        request_schema: { fields: normalizedFields }, requires_approval: requiresApproval,
        assignment_group_id: assignmentGroupId, approval_group_id: approvalGroupId,
        fulfillment_instructions: deliveryInstructions.trim(), acceptance_criteria: acceptanceCriteria.trim(),
        sla_policy_version_id: slaPolicyId,
      });
      await refresh();
      setSelectedId(catalogId);
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? '保存服务目录失败' : 'Unable to save service catalog'));
    } finally { setSaving(false); }
  };

  const groupOptions = groups.filter((group) => group.active !== false);
  const policyOptions = policies.filter((policy) => policy.source_type === 'service_request');
  const fieldTypeLabels = { text: zh ? '单行文本' : 'Short text', textarea: zh ? '多行文本' : 'Long text', number: zh ? '数字' : 'Number', select: zh ? '下拉选项' : 'Select', boolean: zh ? '是 / 否' : 'Yes / No' };
  const fieldTypeOptions = fieldTypes.map((type) => ({ value: type, label: fieldTypeLabels[type] }));

  return (
    <TicketDialog
      title={zh ? '服务目录管理' : 'Service catalog'}
      description={zh ? '已发布版本不可修改；调整申请字段或履约要求时发布新版本。' : 'Published versions are immutable. Publish a new version to change request fields or fulfillment requirements.'}
      onClose={onClose}
      closeDisabled={saving}
      language={language}
      widthClassName="max-w-6xl"
      className="!max-h-[94vh]"
      actions={<>
        <ActionButton onClick={onClose} disabled={saving}>{zh ? '关闭' : 'Close'}</ActionButton>
        <ActionButton type="submit" form="ticket-service-catalog-form" variant="primary" disabled={saving || loading || !name.trim() || (!selectedId && !key.trim())} icon={saving ? LoaderCircle : FilePlus2} iconClassName={saving ? 'animate-spin' : undefined}>{selectedId ? (zh ? '发布新版本' : 'Publish version') : (zh ? '创建服务' : 'Create service')}</ActionButton>
      </>}
      bodyClassName="!flex !min-h-0 !flex-col !overflow-hidden !p-0"
    >
      <div className="grid min-h-0 flex-1 gap-4 overflow-auto p-4 lg:grid-cols-[220px_minmax(0,1fr)] sm:p-5">
        <aside className="min-w-0 space-y-2">
          <ActionButton onClick={startNew} className="w-full justify-center" icon={Plus}>{zh ? '新建服务' : 'New service'}</ActionButton>
          {loading ? <p role="status" className="flex items-center justify-center gap-2 py-6 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]"><LoaderCircle size={13} className="animate-spin" />{zh ? '正在读取目录…' : 'Loading catalog…'}</p> : catalogs.length ? (
            <div className="divide-y divide-[var(--ui-border)]">
              {catalogs.map((item) => <button key={item.id} type="button" aria-pressed={selectedId === item.id} onClick={() => setSelectedId(item.id)} className={`block w-full min-w-0 rounded-lg px-3 py-2 text-left ${selectedId === item.id ? 'bg-[var(--ui-accent-subtle)] ring-1 ring-inset ring-[var(--ui-accent)]' : 'hover:bg-[var(--ui-surface-muted)]'}`}><span className="block truncate text-[var(--ui-text-body)] font-semibold text-[var(--ui-fg)]">{item.name}</span><span className="mt-0.5 block truncate font-mono text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{item.key} · v{item.current_version ?? item.version}</span></button>)}
            </div>
          ) : <TicketEmptyState compact title={zh ? '暂无服务目录' : 'No catalog items yet'} description={zh ? '创建服务后，申请人可按发布版本提交服务申请。' : 'Create a service to make a published request form available.'} />}
        </aside>

        <form id="ticket-service-catalog-form" onSubmit={submit} className="min-w-0 space-y-3">
          <FormSection title={zh ? '服务信息' : 'Service details'} contentClassName="grid gap-3 sm:grid-cols-2">
            {!selectedId && <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '服务编号' : 'Service key'}<input required value={key} onChange={(event) => setKey(event.target.value)} maxLength={80} disabled={saving} className={ticketInputClass} /></label>}
            <label className={`block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)] ${selectedId ? 'sm:col-span-2' : ''}`}>{zh ? '服务名称' : 'Service name'}<input required value={name} onChange={(event) => setName(event.target.value)} maxLength={160} disabled={saving} className={ticketInputClass} /></label>
            <TextField label={zh ? '服务说明' : 'Description'} value={description} onChange={setDescription} multiline rows={2} disabled={saving} className="sm:col-span-2" />
          </FormSection>

          <FormSection title={zh ? '申请表单字段' : 'Request form fields'} description={zh ? '按申请人需要提供的信息设置字段。' : 'Add only the information needed to fulfill the request.'}>
            <div className="mb-2 flex justify-end">
              <ActionButton size="sm" onClick={addField} disabled={saving} icon={Plus}>{zh ? '添加字段' : 'Add field'}</ActionButton>
            </div>
            {fields.length ? <div className="divide-y divide-[var(--ui-border)]">
              {fields.map((field, index) => <div key={index} className="grid min-w-0 gap-2 py-3 first:pt-0 sm:grid-cols-[minmax(90px,.8fr)_minmax(100px,1fr)_130px_auto]">
                <TextField label={zh ? '字段键' : 'Field key'} value={field.key} onChange={(value) => updateField(index, { key: value })} disabled={saving} />
                <TextField label={zh ? '显示名称' : 'Label'} value={field.label} onChange={(value) => updateField(index, { label: value })} disabled={saving} />
                <SelectField label={zh ? '字段类型' : 'Field type'} value={field.type} onChange={(value) => { if (fieldTypes.includes(value as ServiceCatalogFieldType)) updateField(index, { type: value as ServiceCatalogFieldType }); }} options={fieldTypeOptions} language={zh ? 'zh' : 'en'} disabled={saving} />
                <div className="flex items-center justify-end sm:pt-5"><ActionIconButton icon={Trash2} label={`${zh ? '删除字段' : 'Remove field'} ${field.label || field.key || index + 1}`} disabled={saving} onClick={() => removeField(index)} /></div>
                {field.type === 'select' && <TextField label={zh ? '选项（逗号分隔）' : 'Options (comma separated)'} value={field.optionsText || ''} onChange={(value) => updateField(index, { optionsText: value })} disabled={saving} className="sm:col-span-3" />}
                <label className="flex items-center gap-2 text-[var(--ui-text-label)] text-[var(--ui-fg-muted)]"><input type="checkbox" checked={Boolean(field.required)} onChange={(event) => updateField(index, { required: event.target.checked })} disabled={saving} className="accent-[var(--ui-accent)]" />{zh ? '必填' : 'Required'}</label>
              </div>)}
            </div> : <p className="py-2 text-[var(--ui-text-caption)] text-[var(--ui-fg-muted)]">{zh ? '无需额外信息时可留空。' : 'Leave empty if no additional information is needed.'}</p>}
          </FormSection>

          <FormSection title={zh ? '履约与审批' : 'Fulfillment and approval'} contentClassName="grid gap-3 sm:grid-cols-2">
            <label className="flex items-start gap-2 text-[var(--ui-text-body)] text-[var(--ui-fg)] sm:col-span-2"><input type="checkbox" checked={requiresApproval} onChange={(event) => setRequiresApproval(event.target.checked)} disabled={saving} className="mt-0.5 accent-[var(--ui-accent)]" /><span>{zh ? '提交后需要审批' : 'Require approval'}</span></label>
            <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '履约责任组' : 'Fulfillment group'}<select required value={assignmentGroupId} onChange={(event) => setAssignmentGroupId(event.target.value)} disabled={saving} className={ticketInputClass}><option value="">{zh ? '请选择履约责任组' : 'Select a fulfillment group'}</option>{groupOptions.map((group) => <option key={group.id} value={group.id} disabled={group.member_count === 0}>{group.name}{group.member_count === 0 ? (zh ? '（无有效成员）' : ' (no active members)') : ''}</option>)}</select></label>
            {requiresApproval && <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '审批组' : 'Approval group'}<select required value={approvalGroupId} onChange={(event) => setApprovalGroupId(event.target.value)} disabled={saving} className={ticketInputClass}><option value="">{zh ? '请选择审批组' : 'Select an approval group'}</option>{groupOptions.map((group) => <option key={group.id} value={group.id} disabled={group.member_count === 0}>{group.name}{group.member_count === 0 ? (zh ? '（无有效成员）' : ' (no active members)') : ''}</option>)}</select></label>}
            <label className="block text-[var(--ui-text-label)] font-medium text-[var(--ui-fg-muted)]">{zh ? '时限策略' : 'SLA target'}<select value={slaPolicyId} onChange={(event) => setSlaPolicyId(event.target.value)} disabled={saving} className={ticketInputClass}><option value="">{zh ? '未配置' : 'Not configured'}</option>{policyOptions.map((policy) => <option key={`${policy.id}-${policy.version}`} value={policy.version_id}>{policy.name} · {policy.priority} · v{policy.version}</option>)}</select></label>
            <TextField label={zh ? '履约说明' : 'Fulfillment instructions'} value={deliveryInstructions} onChange={setDeliveryInstructions} multiline rows={2} disabled={saving} />
            <TextField label={zh ? '验收标准' : 'Acceptance criteria'} value={acceptanceCriteria} onChange={setAcceptanceCriteria} multiline rows={2} disabled={saving} />
          </FormSection>

          {error && <p role="alert" className="rounded-lg border border-[var(--ui-danger)] bg-[var(--ui-danger-subtle)] px-3 py-2 text-[var(--ui-text-body)] text-[var(--ui-danger)]">{error}</p>}
        </form>
      </div>
    </TicketDialog>
  );
};

export default ServiceCatalogManager;
