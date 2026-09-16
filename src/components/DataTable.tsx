import React from 'react';

export type DataTableDensity = 'comfortable' | 'compact';

interface DataTableFrameProps {
  children: React.ReactNode;
  className?: string;
  density?: DataTableDensity;
}

interface DataTableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  density?: DataTableDensity;
}

/** Shared table primitives for list pages. Business-specific cells remain in the page. */
export const DataTableFrame: React.FC<DataTableFrameProps> = ({ children, className = '', density = 'comfortable' }) => (
  <div className={`nx-data-table-frame ${density === 'compact' ? 'nx-data-table-frame--compact' : ''} ${className}`.trim()}>
    {children}
  </div>
);

export const DataTable: React.FC<DataTableProps> = ({ children, className = '', density, ...props }) => (
  <table {...props} className={`nx-data-table ${density === 'compact' ? 'nx-data-table--compact' : ''} ${className}`.trim()}>
    {children}
  </table>
);

