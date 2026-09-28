import React from 'react';
import { cn } from '../../lib/cn';
import { ActionIconGroup, type ActionIconGroupProps } from './ActionIconButton';
import { TableExportContext } from './TableExportContext';

export interface TableActionHeaderProps extends React.ThHTMLAttributes<HTMLTableCellElement> {}

/** Right-aligned heading for a table's row-action column. */
export const TableActionHeader: React.FC<TableActionHeaderProps> = ({ children, className, ...props }) => {
  const exportMenu = React.useContext(TableExportContext);
  return (
    <th
      {...props}
      scope={props.scope ?? 'col'}
      className={cn('nx-action-column-header', className)}
    >
      {exportMenu ? <div className="flex items-center justify-end gap-2">{children}{exportMenu}</div> : children}
    </th>
  );
};

export interface TableActionCellProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  /** Accessible group name, such as "Actions for Environment". */
  label?: string;
}

/** Table cell that keeps its icon actions aligned and spaced consistently. */
export const TableActionCell: React.FC<TableActionCellProps> = ({
  children,
  className,
  label,
  ...props
}) => {
  const onlyChild = React.isValidElement(children) ? children : null;
  const existingGroup = React.isValidElement<ActionIconGroupProps>(onlyChild)
    && onlyChild.type === ActionIconGroup
    ? onlyChild
    : null;

  return (
    <td {...props} className={cn('nx-action-column-cell', className)}>
      <ActionIconGroup
        label={label ?? existingGroup?.props.label}
        className={existingGroup?.props.className}
      >
        {existingGroup ? existingGroup.props.children : children}
      </ActionIconGroup>
    </td>
  );
};
