import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyTextWithFallback } from './clipboard';

describe('copyTextWithFallback', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    window.getSelection()?.removeAllRanges();
    vi.restoreAllMocks();
  });

  it('uses the async clipboard API when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    await expect(copyTextWithFallback('show version')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('show version');
  });

  it('falls back to execCommand and keeps the selected text', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: undefined,
    });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: execCommand,
    });
    document.body.innerHTML = '<div id="answer">保留这段选中内容</div>';
    const text = document.querySelector('#answer')?.firstChild as Text;
    const range = document.createRange();
    range.setStart(text, 0);
    range.setEnd(text, text.length);
    window.getSelection()?.addRange(range);

    await expect(copyTextWithFallback('保留这段选中内容')).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
    expect(window.getSelection()?.toString()).toBe('保留这段选中内容');
  });
});
