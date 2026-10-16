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

const ADMINISTRATOR_ROLE = 'Administrator';
const STANDARD_USER_ROLE = 'Viewer';
const CHANGE_REQUESTER_PROFILE = 'Change Requester';

const accountRoleFor = (role: string) => role === ADMINISTRATOR_ROLE ? ADMINISTRATOR_ROLE : STANDARD_USER_ROLE;
const accountProfileFor = (role: string) => role === ADMINISTRATOR_ROLE ? '' : CHANGE_REQUESTER_PROFILE;

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
  const openAddUserModal = () => {
    const role = accountRoleFor(newUserForm.role);
    setNewUserForm({ ...newUserForm, role, role_profile: accountProfileFor(role) });
    setShowAddUserModal(true);
  };
  const updateAccountRole = (form: UserFormState, setter: (v: UserFormState) => void, role: string) => {
    setter({ ...form, role, role_profile: accountProfileFor(role) });
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <PageHero
        icon={Users}
        title={t('userManagement')}
        subtitle={t('manageAccess')}
        actions={
          <button
            onClick={openAddUserModal}
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
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '所属分组' : 'Group'}</th>
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
                <td className="px-6 py-4 text-xs">{user.role === ADMINISTRATOR_ROLE ? (isZh ? '管理员' : 'Administrator') : (isZh ? '普通用户' : 'Standard User')}</td>
                <td className="px-6 py-4 text-xs text-black/60">{user.group_name || (isZh ? '未分组' : 'Ungrouped')}</td>
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
                      const role = accountRoleFor(user.role);
                      setEditUserForm({
                        username: user.username,
                        password: '',
                        role,
                        role_profile: accountProfileFor(role),
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
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '账号类型' : 'Account Type'}</label>
                  <select
                    title={isZh ? '账号类型' : 'Account Type'}
                    value={newUserForm.role}
                    onChange={(e) => updateAccountRole(newUserForm, setNewUserForm, e.target.value)}
                    className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all bg-white"
                  >
                    <option value={ADMINISTRATOR_ROLE}>{isZh ? '管理员' : 'Administrator'}</option>
                    <option value={STANDARD_USER_ROLE}>{isZh ? '普通用户' : 'Standard User'}</option>
                  </select>
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
                  <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '账号类型' : 'Account Type'}</label>
                  <select
                    title={isZh ? '账号类型' : 'Account Type'}
                    value={editUserForm.role}
                    onChange={(e) => updateAccountRole(editUserForm, setEditUserForm, e.target.value)}
                    className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all bg-white"
                  >
                    <option value={ADMINISTRATOR_ROLE}>{isZh ? '管理员' : 'Administrator'}</option>
                    <option value={STANDARD_USER_ROLE}>{isZh ? '普通用户' : 'Standard User'}</option>
                  </select>
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
