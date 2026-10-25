export const USER_CHANGE_GROUP_OPTIONS = [
  { key: 'requester', labelZh: '工单申请人', labelEn: 'Change requester' },
  { key: 'initial_reviewer', labelZh: '初审组', labelEn: 'Initial review' },
  { key: 'final_approver', labelZh: '终审组', labelEn: 'Final approval' },
  { key: 'implementer', labelZh: '实施人', labelEn: 'Implementer' },
] as const;

export type UserChangeGroup = typeof USER_CHANGE_GROUP_OPTIONS[number]['key'];

const ADMINISTRATOR_ROLE = 'Administrator';
const ADMIN_ONLY_CHANGE_GROUPS = new Set<UserChangeGroup>(['initial_reviewer', 'final_approver']);
const VALID_CHANGE_GROUPS = new Set<string>(USER_CHANGE_GROUP_OPTIONS.map((option) => option.key));

export const normalizeUserChangeGroups = (value: unknown, role: string): UserChangeGroup[] => {
  if (!Array.isArray(value)) return [];
  const groups = [...new Set(value.map((item) => String(item ?? '').trim()))]
    .filter((group): group is UserChangeGroup => VALID_CHANGE_GROUPS.has(group));
  return role === ADMINISTRATOR_ROLE
    ? groups
    : groups.filter((group) => !ADMIN_ONLY_CHANGE_GROUPS.has(group));
};

export const isAdminOnlyChangeGroup = (group: UserChangeGroup): boolean =>
  ADMIN_ONLY_CHANGE_GROUPS.has(group);
