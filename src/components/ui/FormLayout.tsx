import React from 'react';
import { X } from 'lucide-react';

interface FormSectionProps {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
}

export const FormSection: React.FC<FormSectionProps> = ({ title, description, children, className = '', contentClassName = '' }) => (
  <section className={`nx-form-section ${className}`.trim()}>
    <header className="nx-form-section-heading">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </header>
    <div className={`nx-form-section-content ${contentClassName}`.trim()}>{children}</div>
  </section>
);

interface FormActionBarProps {
  children: React.ReactNode;
  className?: string;
  sticky?: boolean;
}

export const FormActionBar: React.FC<FormActionBarProps> = ({ children, className = '', sticky = false }) => (
  <div className={`nx-form-action-bar ${sticky ? 'is-sticky' : ''} ${className}`.trim()}>{children}</div>
);

interface FormDialogShellProps {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  actions: React.ReactNode;
  onClose?: () => void;
  closeDisabled?: boolean;
  language?: string;
  widthClassName?: string;
  className?: string;
  bodyClassName?: string;
}

/** Shared header, independently scrolling form body, and persistent footer for CRUD dialogs. */
export const FormDialogShell: React.FC<FormDialogShellProps> = ({
  title,
  description,
  children,
  actions,
  onClose,
  closeDisabled = false,
  language = 'zh',
  widthClassName = 'max-w-3xl',
  className = '',
  bodyClassName = '',
}) => {
  const titleId = React.useId();
  return (
  <section role="dialog" aria-modal="true" aria-labelledby={titleId} className={`nx-form-dialog-shell ${widthClassName} ${className}`.trim()}>
    <header className="nx-form-dialog-header">
      <div className="min-w-0">
        <h2 id={titleId}>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {onClose && (
        <button type="button" onClick={onClose} disabled={closeDisabled} aria-label={language === 'zh' ? '关闭' : 'Close'} className="nx-form-dialog-close disabled:cursor-not-allowed disabled:opacity-40"><X size={16} /></button>
      )}
    </header>
    <div className={`nx-form-dialog-body ${bodyClassName}`.trim()}>{children}</div>
    <footer className="nx-form-dialog-footer">{actions}</footer>
  </section>
  );
};

interface FormPageShellProps {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  footer?: React.ReactNode;
}

export const FormPageShell: React.FC<FormPageShellProps> = ({ title, description, actions, children, className = '', footer }) => (
  <div className={`nx-form-page-shell ${className}`.trim()}>
    <header className="nx-form-page-header">
      <div className="min-w-0">
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </header>
    <div className="nx-form-page-content">{children}</div>
    {footer && <FormActionBar sticky>{footer}</FormActionBar>}
  </div>
);
