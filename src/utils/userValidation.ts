export type UserValidationField = 'username' | 'password' | 'display_name' | 'phone' | 'email' | 'group_name';

export type NewUserValidationForm = Record<UserValidationField, string> & { role: string };

const text = (isZh: boolean, zh: string, en: string) => (isZh ? zh : en);

export function validateUserField(field: UserValidationField, rawValue: string, isZh: boolean): string {
  const value = String(rawValue || '').trim();

  if (field === 'username') {
    if (!value) return text(isZh, '\u8bf7\u8f93\u5165\u7528\u6237\u540d', 'Username is required');
    if (!/^[A-Za-z][A-Za-z0-9._-]{2,31}$/.test(value)) {
      return text(isZh, '\u7528\u6237\u540d\u9700\u4ee5\u5b57\u6bcd\u5f00\u5934\uff0c\u957f\u5ea6 3-32 \u4f4d\uff0c\u53ea\u80fd\u5305\u542b\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u70b9\u3001\u4e0b\u5212\u7ebf\u6216\u8fde\u5b57\u7b26', 'Use 3-32 characters: start with a letter, then letters, digits, dot, underscore, or hyphen');
    }
  }

  if (field === 'password') {
    if (!value) return text(isZh, '\u8bf7\u8f93\u5165\u5bc6\u7801', 'Password is required');
    if (value.length < 10) return text(isZh, '\u5bc6\u7801\u81f3\u5c11 10 \u4f4d', 'Password must be at least 10 characters');
    if (!/[A-Z]/.test(value)) return text(isZh, '\u5bc6\u7801\u9700\u5305\u542b\u5927\u5199\u5b57\u6bcd', 'Password must contain an uppercase letter');
    if (!/[a-z]/.test(value)) return text(isZh, '\u5bc6\u7801\u9700\u5305\u542b\u5c0f\u5199\u5b57\u6bcd', 'Password must contain a lowercase letter');
    if (!/[0-9]/.test(value)) return text(isZh, '\u5bc6\u7801\u9700\u5305\u542b\u6570\u5b57', 'Password must contain a digit');
    if (!/[!@#$%^&*()_+\-=\[\]{}|;:\'",.<>?/\\`~]/.test(value)) return text(isZh, '\u5bc6\u7801\u9700\u5305\u542b\u7279\u6b8a\u5b57\u7b26', 'Password must contain a special character');
  }

  if (field === 'display_name') {
    if (!value) return text(isZh, '\u8bf7\u8f93\u5165\u771f\u5b9e\u59d3\u540d', 'Display name is required');
    if (!/^[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff .'-]{1,49}$/.test(value)) {
      return text(isZh, '\u59d3\u540d\u9700\u4e3a 2-50 \u4f4d\u4e2d\u6587\u6216\u82f1\u6587\u5b57\u7b26\uff0c\u4e0d\u80fd\u5305\u542b\u6570\u5b57', 'Use 2-50 Chinese or English characters');
    }
  }

  if (field === 'phone') {
    const digits = value.replace(/\D/g, '');
    if (!value) return text(isZh, '\u8bf7\u8f93\u5165\u7535\u8bdd\u53f7\u7801', 'Phone is required');
    if (!/^\+?[0-9][0-9\s().-]{6,24}$/.test(value) || digits.length < 7 || digits.length > 15) {
      return text(isZh, '\u8bf7\u8f93\u5165\u6709\u6548\u7535\u8bdd\uff0c\u53ef\u5305\u542b\u56fd\u5bb6\u533a\u53f7\uff0c\u6570\u5b57\u957f\u5ea6 7-15 \u4f4d', 'Enter a valid phone number with 7-15 digits and an optional country code');
    }
  }

  if (field === 'email') {
    if (!value) return text(isZh, '\u8bf7\u8f93\u5165\u90ae\u7bb1', 'Email is required');
    if (value.length > 254 || !/^\S+@\S+\.\S{2,}$/.test(value)) {
      return text(isZh, '\u8bf7\u8f93\u5165\u6709\u6548\u90ae\u7bb1\u5730\u5740', 'Enter a valid email address');
    }
  }

  if (field === 'group_name' && value.length > 100) {
    return text(isZh, '\u6240\u5c5e\u5206\u7ec4\u4e0d\u80fd\u8d85\u8fc7 100 \u4e2a\u5b57\u7b26', 'Group name must be 100 characters or fewer');
  }

  return '';
}

export function validateNewUserForm(form: NewUserValidationForm, isZh: boolean): Partial<Record<UserValidationField, string>> {
  const fields: UserValidationField[] = ['username', 'password', 'display_name', 'phone', 'email', 'group_name'];
  return fields.reduce<Partial<Record<UserValidationField, string>>>((errors, field) => {
    const error = validateUserField(field, form[field], isZh);
    if (error) errors[field] = error;
    return errors;
  }, {});
}
