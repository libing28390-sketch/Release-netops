import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Mail } from 'lucide-react';
import { IconInputField } from './IconInputField';

afterEach(cleanup);

describe('IconInputField', () => {
  it('connects its label to the input and uses the shared field treatment', () => {
    render(
      <IconInputField
        id="user-email"
        label="电子邮箱"
        icon={Mail}
        type="email"
        value="admin@example.com"
        onChange={vi.fn()}
      />,
    );

    const input = screen.getByLabelText('电子邮箱');
    expect(input.getAttribute('type')).toBe('email');
    expect(input.classList.contains('rounded-xl')).toBe(true);
    expect(input.classList.contains('focus:border-cyan-500')).toBe(true);
    expect(input.getAttribute('aria-invalid')).toBe('false');
  });

  it('announces validation errors through invalid state and described text', () => {
    const onChange = vi.fn();
    render(
      <IconInputField
        id="user-email"
        label="电子邮箱"
        icon={Mail}
        type="email"
        value="invalid"
        onChange={onChange}
        error="请输入有效邮箱地址"
      />,
    );

    const input = screen.getByLabelText('电子邮箱');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.getAttribute('aria-describedby')).toBe('user-email-error');
    expect(screen.getByText('请输入有效邮箱地址').id).toBe('user-email-error');
    fireEvent.change(input, { target: { value: 'valid@example.com' } });
    expect(onChange).toHaveBeenCalledOnce();
  });
});
