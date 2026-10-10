import React from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '../../lib/cn';
import { ActionIconButton } from './ActionIconButton';

export interface PasswordInputFieldProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /** Controlled visibility. When omitted, the field manages its own toggle. */
  visible?: boolean;
  /** Receives visibility changes when visibility is controlled by the caller. */
  onVisibilityChange?: (visible: boolean) => void;
  /** Extra classes for the wrapper, useful for width and layout. */
  wrapperClassName?: string;
  /** Localized accessible name and tooltip for the reveal control. */
  showPasswordLabel?: string;
  hidePasswordLabel?: string;
}

/** Shared password and secret input with consistent sizing and reveal control. */
export const PasswordInputField = React.forwardRef<HTMLInputElement, PasswordInputFieldProps>(
  (
    {
      visible,
      onVisibilityChange,
      wrapperClassName,
      className,
      disabled,
      id,
      showPasswordLabel = 'Show password',
      hidePasswordLabel = 'Hide password',
      ...inputProps
    },
    ref,
  ) => {
    const [internalVisible, setInternalVisible] = React.useState(false);
    const isVisible = visible ?? internalVisible;
    const label = isVisible ? hidePasswordLabel : showPasswordLabel;

    const toggleVisibility = () => {
      const nextVisible = !isVisible;
      if (visible === undefined) setInternalVisible(nextVisible);
      onVisibilityChange?.(nextVisible);
    };

    return (
      <div className={cn('nx-password-field', wrapperClassName)}>
        <input
          {...inputProps}
          ref={ref}
          id={id}
          disabled={disabled}
          type={isVisible ? 'text' : 'password'}
          className={cn('nx-password-input', className)}
        />
        <ActionIconButton
          icon={isVisible ? EyeOff : Eye}
          label={label}
          tooltip={label}
          aria-controls={id}
          aria-pressed={isVisible}
          disabled={disabled}
          onClick={toggleVisibility}
          size="xs"
          className="nx-password-field__toggle"
        />
      </div>
    );
  },
);

PasswordInputField.displayName = 'PasswordInputField';

export default PasswordInputField;
