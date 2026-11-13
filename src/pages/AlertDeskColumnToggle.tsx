import React from 'react';
import { ColumnSettingsButton } from '../components/ui/TableListControls';
import {
  ALERT_DESK_COLUMN_DEFS,
  type AlertDeskColumnKey,
  type AlertDeskColumnVisibility,
  defaultAlertDeskColumnVisibility,
} from './alertDeskColumns';

interface AlertDeskColumnToggleProps {
  columns: AlertDeskColumnVisibility;
  onChange: (key: AlertDeskColumnKey, visible: boolean) => void;
  language: string;
}

const AlertDeskColumnToggle: React.FC<AlertDeskColumnToggleProps> = ({ columns, onChange, language }) => {
  const defaultColumns = defaultAlertDeskColumnVisibility();
  const visibleKeys = ALERT_DESK_COLUMN_DEFS.filter(({ key }) => columns[key]).map(({ key }) => key);
  const lastVisibleDefaultKey = visibleKeys.length === 1 && defaultColumns[visibleKeys[0]]
    ? visibleKeys[0]
    : undefined;
  const defaultVisibleKeys = ALERT_DESK_COLUMN_DEFS
    .filter(({ key }) => defaultColumns[key])
    .map(({ key }) => key);

  const applyVisibleKeys = (nextVisibleKeys: string[]) => {
    const nextVisibleSet = new Set(nextVisibleKeys);
    const addedKeys = ALERT_DESK_COLUMN_DEFS.filter(({ key }) => nextVisibleSet.has(key) && !columns[key]);
    const removedKeys = ALERT_DESK_COLUMN_DEFS.filter(({ key }) => !nextVisibleSet.has(key) && columns[key]);
    addedKeys.forEach(({ key }) => onChange(key, true));
    removedKeys.forEach(({ key }) => onChange(key, false));
  };

  return (
    <ColumnSettingsButton
      columns={[
        ...ALERT_DESK_COLUMN_DEFS.map(({ key, zh, en }) => ({
          key,
          label: language === 'zh' ? zh : en,
          required: key === lastVisibleDefaultKey,
        })),
        { key: 'actions', label: language === 'zh' ? '操作' : 'Actions', required: true, isAction: true },
      ]}
      visibleKeys={[...visibleKeys, 'actions']}
      defaultVisibleKeys={[...defaultVisibleKeys, 'actions']}
      onApply={applyVisibleKeys}
      language={language}
      label={language === 'zh' ? '列设置' : 'Columns'}
    />
  );
};

export default AlertDeskColumnToggle;
