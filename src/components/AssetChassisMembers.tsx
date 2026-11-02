import React from 'react';

export interface AssetChassisMember {
  entity_index: number;
  serial_number: string;
  entity_name: string;
  entity_description: string;
  model: string;
  collected_at: string;
}

export function normalizeAssetChassisMembers(value: unknown): AssetChassisMember[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((entry): AssetChassisMember[] => {
    if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) return [];
    const row = entry as Record<string, unknown>;
    const entityIndex = row['entity_index'];
    const serialNumber = row['serial_number'];
    const entityName = row['entity_name'];
    const entityDescription = row['entity_description'];
    const model = row['model'];
    const collectedAt = row['collected_at'];

    if (typeof entityIndex !== 'number' || !Number.isSafeInteger(entityIndex) || entityIndex < 1) return [];
    if (
      typeof serialNumber !== 'string'
      || typeof entityName !== 'string'
      || typeof entityDescription !== 'string'
      || typeof model !== 'string'
      || typeof collectedAt !== 'string'
    ) return [];

    return [{
      entity_index: entityIndex,
      serial_number: serialNumber,
      entity_name: entityName,
      entity_description: entityDescription,
      model,
      collected_at: collectedAt,
    }];
  });
}

export function AssetChassisMembers({ members, zh }: { members?: AssetChassisMember[]; zh: boolean }) {
  if (!members?.length) return null;

  const title = members.length > 1
    ? (zh ? '堆叠/机箱序列号' : 'Stacking / chassis serial numbers')
    : (zh ? '机箱序列号' : 'Chassis serial number');

  return (
    <section
      aria-label={title}
      className="col-span-full min-w-0 rounded-lg border border-[var(--ui-border)] bg-[var(--ui-surface-muted)] p-3"
    >
      <h4 className="mb-2 text-xs font-semibold text-[var(--ui-fg)]">{title}</h4>
      <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
        {members.map(member => {
          const entityName = member.entity_name.trim();
          const fallbackName = zh
            ? '实体 ' + member.entity_index + ' · 成员归属待确认'
            : 'Entity ' + member.entity_index + ' · membership unconfirmed';
          const description = member.entity_description.trim();
          const model = member.model.trim();

          return (
            <article key={member.entity_index} className="min-w-0 rounded-md border border-[var(--ui-border)] bg-[var(--ui-surface)] p-2.5">
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-x-2 gap-y-1">
                <h5 className="min-w-0 break-words text-xs font-medium text-[var(--ui-fg)]">
                  {entityName || fallbackName}
                </h5>
                <span className="shrink-0 text-[10px] text-[var(--ui-fg-subtle)]">
                  {zh ? '实体索引 ' : 'Entity index '}{member.entity_index}
                </span>
              </div>
              <dl className="mt-2 space-y-1 text-[11px] leading-relaxed">
                <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-2">
                  <dt className="text-[var(--ui-fg-muted)]">{zh ? '序列号' : 'Serial number'}</dt>
                  <dd className="min-w-0 break-all font-mono text-[var(--ui-fg)]">{member.serial_number.trim() || '—'}</dd>
                </div>
                {model && (
                  <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-2">
                    <dt className="text-[var(--ui-fg-muted)]">{zh ? '型号' : 'Model'}</dt>
                    <dd className="min-w-0 break-words text-[var(--ui-fg)]">{model}</dd>
                  </div>
                )}
                {description && (
                  <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] gap-x-2">
                    <dt className="text-[var(--ui-fg-muted)]">{zh ? '描述' : 'Description'}</dt>
                    <dd className="min-w-0 break-words text-[var(--ui-fg)]">{description}</dd>
                  </div>
                )}
              </dl>
            </article>
          );
        })}
      </div>
    </section>
  );
}
