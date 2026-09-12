import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '../../lib/cn';

export type ActionIconButtonVariant = 'default' | 'accent' | 'danger' | 'success';
export type ActionIconButtonSize = 'xs' | 'sm' | 'md';
export type ActionButtonVariant = 'default' | 'accent' | 'danger' | 'success' | 'primary';
export type ActionButtonSize = 'sm' | 'md';

export interface ActionIconButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  /** The action icon rendered inside the button. */
  icon: LucideIcon;
  /** Accessible action name. It is also used as the default tooltip. */
  label: string;
  /** Optional tooltip text when it should differ from the accessible name. */
  tooltip?: string;
  /** Visual intent. Destructive actions should use `danger`. */
  variant?: ActionIconButtonVariant;
  /** Dense table action (`sm`) or regular toolbar action (`md`). */
  size?: ActionIconButtonSize;
  /** Extra classes for the icon, for example `animate-spin`. */
  iconClassName?: string;
  /** Override the default 16px/18px icon size when the action needs it. */
  iconSize?: number;
  /** Lucide stroke width; defaults to the shared 1.8px treatment. */
  strokeWidth?: number;
}

/**
 * Shared icon-only action control used by tables, cards, and toolbars.
 *
 * Keep labels on the control instead of relying on an icon's visual meaning so
 * keyboard and screen-reader users get the same action affordance.
 */
export const ActionIconButton = React.forwardRef<HTMLButtonElement, ActionIconButtonProps>(
  (
    {
      icon: Icon,
      label,
      tooltip,
      variant = 'default',
      size = 'sm',
      iconClassName,
      iconSize,
      strokeWidth = 1.8,
      className,
      title,
      type = 'button',
      ...buttonProps
    },
    ref,
  ) => (
    <button
      {...buttonProps}
      ref={ref}
      type={type}
      aria-label={label}
      title={title ?? tooltip ?? label}
      data-action-icon="true"
      className={cn(
        'nx-action-icon',
        `nx-action-icon--${size}`,
        `nx-action-icon--${variant}`,
        className,
      )}
    >
      <Icon
        size={iconSize ?? (size === 'xs' ? 14 : size === 'sm' ? 16 : 18)}
        strokeWidth={strokeWidth}
        aria-hidden="true"
        className={iconClassName}
      />
    </button>
  ),
);

ActionIconButton.displayName = 'ActionIconButton';

export interface ActionIconGroupProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Optional accessible name for a group of related actions. */
  label?: string;
}

/** Right-aligned, consistently spaced action group for table rows. */
export const ActionIconGroup: React.FC<ActionIconGroupProps> = ({
  children,
  className,
  label,
  ...props
}) => (
  <div
    {...props}
    role={label ? 'group' : undefined}
    aria-label={label}
    className={cn('nx-action-group', className)}
  >
    {children}
  </div>
);

export default ActionIconButton;

export interface ActionButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Optional Lucide icon displayed before the button label. */
  icon?: LucideIcon;
  /** Visual intent for the labelled action. */
  variant?: ActionButtonVariant;
  /** Compact table/control action or regular toolbar action. */
  size?: ActionButtonSize;
  /** Extra classes for the icon, for example `animate-spin`. */
  iconClassName?: string;
}

export interface ActionLinkProps
  extends React.AnchorHTMLAttributes<HTMLAnchorElement> {
  /** Optional Lucide icon displayed before the link label. */
  icon?: LucideIcon;
  /** Visual intent for the labelled link action. */
  variant?: ActionButtonVariant;
  /** Compact table/control action or regular toolbar action. */
  size?: ActionButtonSize;
  /** Extra classes for the icon, for example `animate-spin`. */
  iconClassName?: string;
}

/** Shared labelled action control for toolbars and modal footers. */
export const ActionButton = React.forwardRef<HTMLButtonElement, ActionButtonProps>(
  (
    {
      icon: Icon,
      variant = 'default',
      size = 'sm',
      iconClassName,
      className,
      type = 'button',
      children,
      ...buttonProps
    },
    ref,
  ) => (
    <button
      {...buttonProps}
      ref={ref}
      type={type}
      className={cn(
        'nx-action-button',
        `nx-action-button--${size}`,
        `nx-action-button--${variant}`,
        className,
      )}
    >
      {Icon && <Icon size={size === 'sm' ? 16 : 18} strokeWidth={1.8} aria-hidden="true" className={iconClassName} />}
      {children}
    </button>
  ),
);

ActionButton.displayName = 'ActionButton';

/** Shared labelled link control for downloads and external actions. */
export const ActionLink = React.forwardRef<HTMLAnchorElement, ActionLinkProps>(
  (
    {
      icon: Icon,
      variant = 'default',
      size = 'sm',
      iconClassName,
      className,
      children,
      ...linkProps
    },
    ref,
  ) => (
    <a
      {...linkProps}
      ref={ref}
      className={cn(
        'nx-action-button',
        `nx-action-button--${size}`,
        `nx-action-button--${variant}`,
        className,
      )}
    >
      {Icon && <Icon size={size === 'sm' ? 16 : 18} strokeWidth={1.8} aria-hidden="true" className={iconClassName} />}
      {children}
    </a>
  ),
);

ActionLink.displayName = 'ActionLink';
