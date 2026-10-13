import React, { useRef } from 'react';
import { TableExportMenu } from './ui/TableExportMenu';
import { TableActionHeader } from './ui/TableActionColumn';
import { TableExportContext } from './ui/TableExportContext';
import type { TableExportDataSource } from './ui/TableExportMenu';

export type DataTableDensity = 'comfortable' | 'compact';

interface DataTableFrameProps {
  children: React.ReactNode;
  className?: string;
  density?: DataTableDensity;
}

interface DataTableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  density?: DataTableDensity;
  /** Preserve custom table styles when a page opts into the shared export menu. */
  unstyled?: boolean;
  exportConfig?: {
    filename: string;
    language?: 'zh' | 'en';
    disabled?: boolean;
    /** Provide all filtered rows when the visible DOM contains only one page. */
    exportData?: TableExportDataSource;
  };
}

/** Shared table primitives for list pages. Business-specific cells remain in the page. */
export const DataTableFrame: React.FC<DataTableFrameProps> = ({ children, className = '', density = 'comfortable' }) => (
  <div className={`nx-data-table-frame ${density === 'compact' ? 'nx-data-table-frame--compact' : ''} ${className}`.trim()}>
    {children}
  </div>
);

function containsActionHeader(children: React.ReactNode): boolean {
  let found = false;
  React.Children.forEach(children, (child) => {
    if (!React.isValidElement<{ children?: React.ReactNode }>(child)) return;
    if (child.type === TableActionHeader) {
      found = true;
      return;
    }
    if (child.props.children && containsActionHeader(child.props.children)) found = true;
  });
  return found;
}

function appendExportToLastHeaderCell(children: React.ReactNode, exportMenu: React.ReactNode): React.ReactNode {
  let foundHeaderRow = false;
  let hasExported = false;

  const visitHeaderRows = (rows: React.ReactNode): React.ReactNode => React.Children.map(rows, (row) => {
    if (!React.isValidElement<{ children?: React.ReactNode }>(row)) return row;
    if (row.type === React.Fragment) {
      return React.cloneElement(row, undefined, visitHeaderRows(row.props.children));
    }
    if (row.type !== 'tr' || foundHeaderRow) return row;

    foundHeaderRow = true;
    const cells = React.Children.toArray(row.props.children);
    let lastHeaderCell = -1;
    cells.forEach((cell, index) => {
      if (React.isValidElement(cell) && cell.type === 'th') lastHeaderCell = index;
    });
    return React.cloneElement(row, undefined, cells.map((cell, index) => {
      if (index !== lastHeaderCell || !React.isValidElement<{ children?: React.ReactNode }>(cell)) return cell;
      hasExported = true;
      return React.cloneElement(cell, undefined,
        <div className="flex w-full items-center justify-between gap-2">
          <span className="min-w-0">{cell.props.children}</span>
          {exportMenu}
        </div>,
      );
    }));
  });

  const visit = (nodes: React.ReactNode): React.ReactNode => React.Children.map(nodes, (child) => {
    if (!React.isValidElement<{ children?: React.ReactNode }>(child)) return child;
    if (child.type === 'thead') {
      return React.cloneElement(child, undefined, visitHeaderRows(child.props.children));
    }
    if (child.type === React.Fragment) return React.cloneElement(child, undefined, visit(child.props.children));
    return child;
  });

  const result = visit(children);
  return hasExported ? result : children;
}

export const DataTable: React.FC<DataTableProps> = ({ children, className = '', density, exportConfig, unstyled = false, ...props }) => {
  const tableRef = useRef<HTMLTableElement>(null);
  const table = (
    <table
      {...props}
      ref={tableRef}
      className={`${unstyled ? '' : 'nx-data-table'} ${density === 'compact' ? 'nx-data-table--compact' : ''} ${className}`.trim()}
    >
      {children}
    </table>
  );

  if (!exportConfig) return table;

  const exportMenu = (
    <TableExportMenu
      tableRef={tableRef}
      filename={exportConfig.filename}
      language={exportConfig.language}
      disabled={exportConfig.disabled}
      exportData={exportConfig.exportData}
    />
  );
  const hasActionHeader = containsActionHeader(children);
  const tableChildren = hasActionHeader ? children : appendExportToLastHeaderCell(children, exportMenu);

  return (
    <div className="nx-exportable-data-table w-full overflow-x-auto">
      {hasActionHeader ? (
        <TableExportContext.Provider value={exportMenu}>
          {React.cloneElement(table, undefined, tableChildren)}
        </TableExportContext.Provider>
      ) : React.cloneElement(table, undefined, tableChildren)}
    </div>
  );
};

