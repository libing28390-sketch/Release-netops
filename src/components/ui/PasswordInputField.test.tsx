import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PasswordInputField } from './PasswordInputField';

afterEach(cleanup);

describe('PasswordInputField', () => {
  it('uses the shared password style and toggles visibility with an accessible control', () => {
    render(
      <>
        <label htmlFor="account-password">密码</label>
        <PasswordInputField id="account-password" showPasswordLabel="显示密码" hidePasswordLabel="隐藏密码" />
      </>,
    );

    const input = screen.getByLabelText('密码');
    expect(input.getAttribute('type')).toBe('password');
    expect(input.classList.contains('nx-password-input')).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: '显示密码' }));
    expect(input.getAttribute('type')).toBe('text');
    expect(screen.getByRole('button', { name: '隐藏密码' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('reports controlled visibility changes without taking ownership of the state', () => {
    const onVisibilityChange = vi.fn();
    render(
      <>
        <label htmlFor="fixed-pin">安全码</label>
        <PasswordInputField
          id="fixed-pin"
          visible={false}
          onVisibilityChange={onVisibilityChange}
          showPasswordLabel="显示密码"
          hidePasswordLabel="隐藏密码"
        />
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: '显示密码' }));
    expect(onVisibilityChange).toHaveBeenCalledWith(true);
    expect(screen.getByLabelText('安全码').getAttribute('type')).toBe('password');
  });
});
