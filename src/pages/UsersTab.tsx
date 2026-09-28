import React from 'react';
import { Plus, Mail, Pencil, Phone, UserRound, Users } from 'lucide-react';
import { motion } from 'motion/react';
import type { User } from '../types';
import { primaryActionBtnClass } from '../components/shared';
import PageHero from '../components/PageHero';
import { DataTable } from '../components/DataTable';
import { validateUserField } from '../utils/userValidation';
import { useEscapeClose } from '../hooks/useEscapeClose';
import { ActionIconButton } from '../components/ui/ActionIconButton';
import { IconInputField } from '../components/ui/IconInputField';
import { PasswordInputField } from '../components/ui/PasswordInputField';
import { TableActionCell, TableActionHeader } from '../components/ui/TableActionColumn';

type UserFormState = {
  username: string;
  password: string;
  role: string;
  role_profile: string;
  group_name: string;
  change_groups: string[];
  display_name: string;
  phone: string;
  email: string;
};

const CHANGE_GROUP_OPTIONS = [
  { key: 'requester', zh: '申请组', en: 'Requester' },
  { key: 'initial_reviewer', zh: '初审组', en: 'Initial Review' },
  { key: 'final_approver', zh: '终审组', en: 'Final Approval' },
  { key: 'implementer', zh: '实施组', en: 'Implementer' },
] as const;

const ROLE_PROFILE_OPTIONS = [
  { key: '', zh: '沿用基础角色', en: 'Use base role' },
  { key: 'Platform Viewer', zh: '平台查看者', en: 'Platform Viewer' },
  { key: 'Template Developer', zh: '模板开发者', en: 'Template Developer' },
  { key: 'Platform Maintainer', zh: '平台维护者', en: 'Platform Maintainer' },
  { key: 'Playbook Author', zh: 'Playbook 作者', en: 'Playbook Author' },
  { key: 'Release Manager', zh: '审核发布者', en: 'Release Manager' },
  { key: 'Automation Operator', zh: '自动化操作员', en: 'Automation Operator' },
  { key: 'Scheduler Administrator', zh: '调度管理员', en: 'Scheduler Administrator' },
  { key: 'System Administrator', zh: '系统管理员', en: 'System Administrator' },
] as const;

interface UsersTabProps {
  users: User[];
  showAddUserModal: boolean;
  setShowAddUserModal: (v: boolean) => void;
  showEditUserModal: boolean;
  setShowEditUserModal: (v: boolean) => void;
  editingUser: User | null;
  setEditingUser: (u: User | null) => void;
  newUserForm: UserFormState;
  setNewUserForm: (v: UserFormState) => void;
  editUserForm: UserFormState;
  setEditUserForm: (v: UserFormState) => void;
  showNewUserPwd: boolean;
  setShowNewUserPwd: React.Dispatch<React.SetStateAction<boolean>>;
  showEditUserPwd: boolean;
  setShowEditUserPwd: React.Dispatch<React.SetStateAction<boolean>>;
  handleAddUser: () => void;
  handleEditUser: () => void;
  language: string;
  t: (key: string) => string;
}

const UsersTab: React.FC<UsersTabProps> = ({
  users, showAddUserModal, setShowAddUserModal,
  showEditUserModal, setShowEditUserModal,
  editingUser, setEditingUser,
  newUserForm, setNewUserForm, editUserForm, setEditUserForm,
  showNewUserPwd, setShowNewUserPwd, showEditUserPwd, setShowEditUserPwd,
  handleAddUser, handleEditUser, language, t,
}) => {
  useEscapeClose(showAddUserModal, () => setShowAddUserModal(false));
  useEscapeClose(showEditUserModal && Boolean(editingUser), () => { setShowEditUserModal(false); setEditingUser(null); });
  const isZh = language === 'zh';
  const fieldError = (field: Parameters<typeof validateUserField>[0], value: string) => validateUserField(field, value, isZh);
  const inputClass = (error: string) => `w-full px-4 py-3 rounded-xl border ${error ? 'border-red-400 focus:border-red-500 focus:ring-red-100' : 'border-black/10 focus:border-black focus:ring-black/5'} focus:ring-4 outline-none transition-all`;
  const labelForGroup = (groupKey: string) => {
    const match = CHANGE_GROUP_OPTIONS.find((item) => item.key === groupKey);
    return match ? (isZh ? match.zh : match.en) : groupKey;
  };
  const toggleChangeGroup = (form: UserFormState, nextKey: string, setter: (v: UserFormState) => void) => {
    const exists = form.change_groups.includes(nextKey);
    setter({
      ...form,
      change_groups: exists
        ? form.change_groups.filter((item) => item !== nextKey)
        : [...form.change_groups, nextKey],
    });
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Users}
        title={t('userManagement')}
        subtitle={t('manageAccess')}
        actions={
          <button
            onClick={() => setShowAddUserModal(true)}
            className={primaryActionBtnClass}
          >
            <Plus size={18} />
            {t('addUser')}
          </button>
        }
      />

      <div className="flex-1 overflow-auto px-6 py-5 space-y-8">

      <div className="bg-white rounded-2xl border border-black/5 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
        <DataTable className="text-left" exportConfig={{ filename: 'users', language: isZh ? 'zh' : 'en', disabled: users.length === 0 }}>
          <thead>
            <tr className="bg-black/[0.01] border-b border-black/5">
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('username')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '真实姓名' : 'Display Name'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '手机号' : 'Phone'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '邮箱' : 'Email'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('role')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '资源角色' : 'Resource Role'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '所属分组' : 'Group'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '职责组' : 'Responsibilities'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('status')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('lastLogin')}</th>
              <TableActionHeader className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('actions')}</TableActionHeader>
            </tr>
          </thead>
          <tbody>
            {users.map(user => (
              <tr key={user.id} className="border-b border-black/5 hover:bg-black/[0.01] transition-colors">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 bg-black/5 rounded-full flex items-center justify-center text-xs font-bold">
                      {user.username.substring(0, 2).toUpperCase()}
                    </div>
                    <span className="text-sm font-medium">{user.username}</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm font-medium text-black/80">{user.display_name || <span className="text-black/25 text-xs">{isZh ? '未填写' : 'Not set'}</span>}</td>
                <td className="px-6 py-4 text-xs font-mono text-black/60">{user.phone || '—'}</td>
                <td className="px-6 py-4 text-xs font-mono text-black/60">{user.email || '—'}</td>
                <td className="px-6 py-4 text-xs">{user.role}</td>
                <td className="px-6 py-4 text-xs text-black/60">{user.role_profile || (isZh ? '沿用基础角色' : 'Base role')}</td>
                <td className="px-6 py-4 text-xs text-black/60">{user.group_name || (isZh ? '未分组' : 'Ungrouped')}</td>
                <td className="px-6 py-4">
                  <div className="flex flex-wrap gap-1.5">
                    {(user.change_groups || []).length > 0 ? (
                      (user.change_groups || []).map(groupKey => (
                        <span key={groupKey} className="inline-flex items-center rounded-full bg-cyan-50 px-2 py-1 text-[10px] font-semibold text-cyan-700 ring-1 ring-cyan-200/70">
                          {labelForGroup(groupKey)}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-black/35">{isZh ? '未配置' : 'Not set'}</span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4">
                  <span className="text-[10px] font-bold uppercase px-2 py-1 rounded bg-emerald-100 text-emerald-700">
                    {user.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-xs text-black/40">{user.lastLogin}</td>
                <TableActionCell className="px-6 py-4" label={isZh ? `${user.username} 的操作` : `Actions for ${user.username}`}>
                  <ActionIconButton
                    icon={Pencil}
                    label={isZh ? `编辑 ${user.username}` : `Edit ${user.username}`}
                    tooltip={t('edit')}
                    onClick={() => {
                      setEditingUser(user);
                      setEditUserForm({
                        username: user.username,
                        password: '',
                        role: user.role,
                        role_profile: user.role_profile || '',
                        group_name: user.group_name || '',
                        change_groups: [...(user.change_groups || [])],
                        display_name: user.display_name || '',
                        phone: user.phone || '',
                        email: user.email || '',
                      });
                      setShowEditUserModal(true);
                    }}
                  />
                </TableActionCell>
              </tr>
            ))}
          </tbody>
        </DataTable>
        </div>
      </div>

      {showAddUserModal && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="bg-white w-full max-w-xl rounded-3xl shadow-2xl border border-black/5 overflow-hidden"
          >
            <div className="p-8">
              <h3 className="text-xl font-medium mb-6">{t('addNewUser')}</h3>
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{t('username')}</label>
                  <input
                    type="text"
                    title={t('username')}
                    value={newUserForm.username}
                    onChange={(e) => setNewUserForm({ ...newUserForm, username: e.target.value })}
                    className={inputClass(fieldError('username', newUserForm.username))}
                    placeholder="e.g. jdoe"
                  />
                  {fieldError('username', newUserForm.username) && <p className="text-[10px] text-red-500">{fieldError('username', newUserForm.username)}</p>}
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{t('password')}</label>
                  <div>
                    <PasswordInputField
                      visible={showNewUserPwd}
                      onVisibilityChange={setShowNewUserPwd}
                      showPasswordLabel={isZh ? '显示密码' : 'Show password'}
                      hidePasswordLabel={isZh ? '隐藏密码' : 'Hide password'}
                      title={t('password')}
                      value={newUserForm.password}
                      onChange={(e) => setNewUserForm({ ...newUserForm, password: e.target.value })}
                      className={inputClass(fieldError('password', newUserForm.password))}
                      placeholder="••••••••"
                    />
                  </div>
                  {fieldError('password', newUserForm.password) && <p className="text-[10px] text-red-500">{fieldError('password', newUserForm.password)}</p>}
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{t('role')}</label>
                  <select
                    title={t('role')}
                    value={newUserForm.role}
                    onChange={(e) => setNewUserForm({ ...newUserForm, role: e.target.value })}
                    className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all bg-white"
                  >
                    <option value="Administrator">Administrator</option>
                    <option value="Operator">Operator</option>
                    <option value="Viewer">Viewer</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '资源角色' : 'Resource Role'}</label>
                  <select title={isZh ? '资源角色' : 'Resource Role'} value={newUserForm.role_profile} onChange={(e) => setNewUserForm({ ...newUserForm, role_profile: e.target.value })} className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all bg-white">
                    {ROLE_PROFILE_OPTIONS.map((option) => <option key={option.key} value={option.key}>{isZh ? option.zh : option.en}</option>)}
                  </select>
                  <p className="text-[10px] text-black/35">{isZh ? '资源角色会收窄基础角色的动作权限，并保留 Site/设备组范围限制。' : 'A resource role narrows action permissions and keeps Site/device-group scope limits.'}</p>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '所属分组' : 'User Group'}</label>
                  <input
                    type="text"
                    title={isZh ? '所属分组' : 'User Group'}
                    value={newUserForm.group_name}
                    onChange={(e) => setNewUserForm({ ...newUserForm, group_name: e.target.value })}
                    className={inputClass(fieldError('group_name', newUserForm.group_name))}
                    placeholder={isZh ? '例如：核心网络组 / 变更平台主管组' : 'e.g. Core Network Team'}
                  />
                  {fieldError('group_name', newUserForm.group_name) && <p className="text-[10px] text-red-500">{fieldError('group_name', newUserForm.group_name)}</p>}
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <IconInputField
                    id="new-user-display-name"
                    label={isZh ? '真实姓名 / 昵称' : 'Display Name'}
                    icon={UserRound}
                    value={newUserForm.display_name}
                    onChange={(e) => setNewUserForm({ ...newUserForm, display_name: e.target.value })}
                    placeholder={isZh ? '如：韩梅梅' : 'e.g. Han Meimei'}
                    autoComplete="name"
                    error={fieldError('display_name', newUserForm.display_name)}
                  />
                  <IconInputField
                    id="new-user-phone"
                    label={isZh ? '手机号码' : 'Phone'}
                    icon={Phone}
                    type="tel"
                    value={newUserForm.phone}
                    onChange={(e) => setNewUserForm({ ...newUserForm, phone: e.target.value })}
                    placeholder={isZh ? '如：138xxxx8888' : 'e.g. 138xxxx8888'}
                    autoComplete="tel"
                    error={fieldError('phone', newUserForm.phone)}
                  />
                  <IconInputField
                    id="new-user-email"
                    label={isZh ? '电子邮箱' : 'Email'}
                    icon={Mail}
                    type="email"
                    value={newUserForm.email}
                    onChange={(e) => setNewUserForm({ ...newUserForm, email: e.target.value })}
                    placeholder={isZh ? '如：han.meimei@example.com' : 'e.g. han.meimei@example.com'}
                    autoComplete="email"
                    error={fieldError('email', newUserForm.email)}
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '工单职责组' : 'Change Duties'}</label>
                  <div className="grid grid-cols-2 gap-2">
                    {CHANGE_GROUP_OPTIONS.map((option) => {
                      const checked = newUserForm.change_groups.includes(option.key);
                      return (
                        <label key={option.key} className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs transition-all ${checked ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-black/10 bg-white text-black/55 hover:border-black/20'}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleChangeGroup(newUserForm, option.key, setNewUserForm)}
                            className="rounded border-black/20 text-cyan-500 focus:ring-cyan-400"
                          />
                          <span>{isZh ? option.zh : option.en}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>
              <div className="flex gap-3 mt-8">
                <button
                  onClick={() => setShowAddUserModal(false)}
                  className="flex-1 px-4 py-3 rounded-xl border border-black/10 font-medium hover:bg-black/5 transition-all"
                >
                  {t('cancel')}
                </button>
                <button
                  onClick={handleAddUser}
                  className="flex-1 px-4 py-3 rounded-xl bg-black text-white font-medium hover:bg-black/80 transition-all shadow-lg shadow-black/20"
                >
                  {t('create')}
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}

      {showEditUserModal && editingUser && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="bg-white w-full max-w-xl rounded-3xl shadow-2xl border border-black/5 overflow-hidden"
          >
            <div className="p-8">
              <h3 className="text-xl font-medium mb-6">编辑用户</h3>
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{t('username')}</label>
                  <input
                    type="text"
                    title={t('username')}
                    value={editUserForm.username}
                    onChange={(e) => setEditUserForm({ ...editUserForm, username: e.target.value })}
                    className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{t('password')} <span className="text-black/30 normal-case font-normal">（留空则不修改）</span></label>
                  <div>
                    <PasswordInputField
                      visible={showEditUserPwd}
                      onVisibilityChange={setShowEditUserPwd}
                      showPasswordLabel={isZh ? '显示密码' : 'Show password'}
                      hidePasswordLabel={isZh ? '隐藏密码' : 'Hide password'}
                      title={t('password')}
                      value={editUserForm.password}
                      onChange={(e) => setEditUserForm({ ...editUserForm, password: e.target.value })}
                      className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all"
                      placeholder="••••••••"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{t('role')}</label>
                  <select
                    title={t('role')}
                    value={editUserForm.role}
                    onChange={(e) => setEditUserForm({ ...editUserForm, role: e.target.value })}
                    className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all bg-white"
                  >
                    <option value="Administrator">Administrator</option>
                    <option value="Operator">Operator</option>
                    <option value="Viewer">Viewer</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '资源角色' : 'Resource Role'}</label>
                  <select title={isZh ? '资源角色' : 'Resource Role'} value={editUserForm.role_profile} onChange={(e) => setEditUserForm({ ...editUserForm, role_profile: e.target.value })} className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all bg-white">
                    {ROLE_PROFILE_OPTIONS.map((option) => <option key={option.key} value={option.key}>{isZh ? option.zh : option.en}</option>)}
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '所属分组' : 'User Group'}</label>
                  <input
                    type="text"
                    title={isZh ? '所属分组' : 'User Group'}
                    value={editUserForm.group_name}
                    onChange={(e) => setEditUserForm({ ...editUserForm, group_name: e.target.value })}
                    className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all"
                    placeholder={isZh ? '例如：核心网络组 / 变更平台主管组' : 'e.g. Core Network Team'}
                  />
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <IconInputField
                    id="edit-user-display-name"
                    label={isZh ? '真实姓名 / 昵称' : 'Display Name'}
                    icon={UserRound}
                    value={editUserForm.display_name}
                    onChange={(e) => setEditUserForm({ ...editUserForm, display_name: e.target.value })}
                    placeholder={isZh ? '如：韩梅梅' : 'e.g. Han Meimei'}
                    autoComplete="name"
                  />
                  <IconInputField
                    id="edit-user-phone"
                    label={isZh ? '手机号码' : 'Phone'}
                    icon={Phone}
                    type="tel"
                    value={editUserForm.phone}
                    onChange={(e) => setEditUserForm({ ...editUserForm, phone: e.target.value })}
                    placeholder={isZh ? '如：138xxxx8888' : 'e.g. 138xxxx8888'}
                    autoComplete="tel"
                  />
                  <IconInputField
                    id="edit-user-email"
                    label={isZh ? '电子邮箱' : 'Email'}
                    icon={Mail}
                    type="email"
                    value={editUserForm.email}
                    onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })}
                    placeholder={isZh ? '如：han.meimei@example.com' : 'e.g. han.meimei@example.com'}
                    autoComplete="email"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '工单职责组' : 'Change Duties'}</label>
                  <div className="grid grid-cols-2 gap-2">
                    {CHANGE_GROUP_OPTIONS.map((option) => {
                      const checked = editUserForm.change_groups.includes(option.key);
                      return (
                        <label key={option.key} className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs transition-all ${checked ? 'border-cyan-300 bg-cyan-50 text-cyan-700' : 'border-black/10 bg-white text-black/55 hover:border-black/20'}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleChangeGroup(editUserForm, option.key, setEditUserForm)}
                            className="rounded border-black/20 text-cyan-500 focus:ring-cyan-400"
                          />
                          <span>{isZh ? option.zh : option.en}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>
              <div className="flex gap-3 mt-8">
                <button
                  onClick={() => { setShowEditUserModal(false); setEditingUser(null); }}
                  className="flex-1 px-4 py-3 rounded-xl border border-black/10 font-medium hover:bg-black/5 transition-all"
                >
                  {t('cancel')}
                </button>
                <button
                  onClick={handleEditUser}
                  className="flex-1 px-4 py-3 rounded-xl bg-black text-white font-medium hover:bg-black/80 transition-all shadow-lg shadow-black/20"
                >
                  保存
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      )}
      </div>
    </div>
  );
};

export default UsersTab;
