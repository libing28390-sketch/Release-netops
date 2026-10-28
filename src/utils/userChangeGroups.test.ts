import { describe, expect, it } from 'vitest';
import { normalizeUserChangeGroups } from './userChangeGroups';

describe('user change-group assignment', () => {
  it('keeps final approval as a workflow responsibility without changing the base role', () => {
    expect(normalizeUserChangeGroups(['final_approver', 'implementer'], 'Administrator'))
      .toEqual(['final_approver', 'implementer']);
  });

  it('does not allow ordinary users to hold initial or final review responsibilities', () => {
    expect(normalizeUserChangeGroups(
      ['requester', 'initial_reviewer', 'final_approver', 'implementer'],
      'Viewer',
    )).toEqual(['requester', 'implementer']);
  });

  it('drops unknown and duplicate responsibilities', () => {
    expect(normalizeUserChangeGroups(['requester', 'requester', 'owner'], 'Administrator'))
      .toEqual(['requester']);
  });
});
