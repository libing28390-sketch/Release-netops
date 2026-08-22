import { afterEach, describe, expect, it } from 'vitest';
import { cloneSelectionWithin, hasTextSelection, restoreSelection } from './selectionUtils';

describe('Copilot text selection helpers', () => {
  afterEach(() => {
    document.body.innerHTML = '';
    window.getSelection()?.removeAllRanges();
  });

  it('clones only a non-empty selection inside the message content', () => {
    document.body.innerHTML = '<div id="message">可以复制这段回答</div><div id="outside">其他内容</div>';
    const message = document.querySelector('#message') as HTMLElement;
    const text = message.firstChild as Text;
    const selection = window.getSelection();
    const range = document.createRange();
    range.setStart(text, 0);
    range.setEnd(text, 8);
    selection?.removeAllRanges();
    selection?.addRange(range);

    expect(hasTextSelection(selection)).toBe(true);
    expect(cloneSelectionWithin(selection, message)?.toString()).toBe('可以复制这段回答');
    expect(cloneSelectionWithin(selection, document.querySelector('#outside') as HTMLElement)).toBeNull();
  });

  it('restores a live range synchronously and rejects detached ranges', () => {
    document.body.innerHTML = '<div id="message">第一段文本</div>';
    const message = document.querySelector('#message') as HTMLElement;
    const text = message.firstChild as Text;
    const range = document.createRange();
    range.setStart(text, 0);
    range.setEnd(text, 5);

    expect(restoreSelection(range)).toBe(true);
    expect(window.getSelection()?.toString()).toBe('第一段文本');

    const detachedFragment = document.createDocumentFragment();
    const detachedText = document.createTextNode('脱离文档');
    detachedFragment.append(detachedText);
    const detachedRange = document.createRange();
    detachedRange.setStart(detachedText, 0);
    detachedRange.setEnd(detachedText, 4);
    expect(restoreSelection(detachedRange)).toBe(false);
  });
});
