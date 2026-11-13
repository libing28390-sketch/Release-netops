import React, { useId } from 'react';
import type { User } from '../../types';
import { ActionButton } from '../ui/ActionIconButton';
import { TicketDialog, ticketInputClass, ticketLabelClass } from './TicketUI';

interface Props {
  title: string;
  language: string;
  search: string;
  onSearchChange: (value: string) => void;
  groups: Record<string, User[]>;
  selectedId: string;
  onSelect: (id: string) => void;
  onClose: () => void;
  onConfirm: () => void;
  emptyMessage: string;
}

/** The same candidate list and confirm interaction serves both review stages. */
export const TicketReviewerDialog: React.FC<Props> = ({ title, language, search, onSearchChange, groups, selectedId, onSelect, onClose, onConfirm, emptyMessage }) => {
  const zh = language === 'zh';
  const inputId = useId();
  return <TicketDialog title={title} language={language} onClose={onClose} widthClassName="max-w-md" initialFocusSelector="input[type=search]" actions={<><ActionButton onClick={onClose}>{zh ? '取消' : 'Cancel'}</ActionButton><ActionButton variant="primary" disabled={!selectedId} onClick={onConfirm}>{zh ? '确定' : 'Confirm'}</ActionButton></>}>
    <label htmlFor={inputId} className={ticketLabelClass}>{zh ? '搜索审核人' : 'Search reviewers'}</label>
    <input id={inputId} type="search" value={search} onChange={(event) => onSearchChange(event.target.value)} placeholder={zh ? '姓名、用户名或拼音' : 'Name or username'} className={ticketInputClass} />
    <div role="radiogroup" aria-label={title} className="mt-4 max-h-72 overflow-y-auto rounded-lg border border-[var(--ui-border)]">
      {Object.keys(groups).length === 0 ? <p className="px-4 py-7 text-center text-xs leading-5 text-[var(--ui-fg-muted)]">{emptyMessage}</p> : Object.entries(groups).map(([group, candidates]) => <div key={group}>
        <div className="bg-[var(--ui-surface-muted)] px-3 py-2 text-xs font-medium text-[var(--ui-fg-muted)]">{group}</div>
        {candidates.map((candidate) => <label key={candidate.id} className={`flex cursor-pointer items-center gap-3 border-t border-[var(--ui-border)] px-3 py-3 text-[13px] hover:bg-[var(--ui-surface-muted)] ${selectedId === String(candidate.id) ? 'bg-[var(--ui-accent-subtle)]' : ''}`}>
          <input type="radio" name={inputId} aria-label={candidate.display_name ? `${candidate.display_name} (${candidate.username})` : candidate.username} checked={selectedId === String(candidate.id)} onChange={() => onSelect(String(candidate.id))} className="h-4 w-4 shrink-0 accent-[var(--ui-accent)]" />
          <span className="min-w-0"><span className="block truncate font-medium text-[var(--ui-fg)]">{candidate.display_name || candidate.username}</span>{candidate.display_name && <span className="mt-0.5 block text-xs text-[var(--ui-fg-muted)]">{candidate.username}</span>}</span>
        </label>)}
      </div>)}
    </div>
  </TicketDialog>;
};
