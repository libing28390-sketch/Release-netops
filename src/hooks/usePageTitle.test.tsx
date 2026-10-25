import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePageTitle } from './usePageTitle';

const getTitle = (language: 'zh' | 'en') => renderHook(() => usePageTitle({
  activeTab: 'tickets',
  automationPage: '',
  configPage: '',
  inventorySubPage: '',
  changeOrderPage: '',
  ipamPage: '',
  cmdbPage: '',
  language,
  t: (key) => key,
})).result.current;

describe('usePageTitle tickets route', () => {
  it('names the combined incident and service request workspace', () => {
    expect(getTitle('zh')).toBe('故障与服务工单');
    expect(getTitle('en')).toBe('Incidents & service requests');
  });
});
