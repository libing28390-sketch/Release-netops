import React from 'react';
import { Plus, Eye, EyeOff, Users } from 'lucide-react';
import { motion } from 'motion/react';
import type { User } from '../types';
import { primaryActionBtnClass } from '../components/shared';
import PageHero from '../components/PageHero';
import { validateUserField } from '../utils/userValidation';

type UserFormState = {
  username: string;
  password: string;
  role: string;
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
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-black/[0.01] border-b border-black/5">
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('username')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '真实姓名' : 'Display Name'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('role')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '所属分组' : 'Group'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{isZh ? '职责组' : 'Responsibilities'}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('status')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40">{t('lastLogin')}</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-black/40 text-right">{t('actions')}</th>
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
                <td className="px-6 py-4">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-sm font-medium text-black/80">{user.display_name || <span className="text-black/25 text-xs">{isZh ? '未填写' : 'Not set'}</span>}</span>
                    {(user.phone || user.email) && (
                      <span className="text-[11px] text-black/40 font-mono">
                        {[user.phone, user.email].filter(Boolean).join(' · ')}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-6 py-4 text-xs">{user.role}</td>
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
                <td className="px-6 py-4 text-right">
                  <button
                    onClick={() => {
                      setEditingUser(user);
                      setEditUserForm({
                        username: user.username,
                        password: '',
                        role: user.role,
                        group_name: user.group_name || '',
                        change_groups: [...(user.change_groups || [])],
                        display_name: user.display_name || '',
                        phone: user.phone || '',
                        email: user.email || '',
                      });
                      setShowEditUserModal(true);
                    }}
                    className="text-[10px] font-bold uppercase text-black/40 hover:text-black"
                  >{t('edit')}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {showAddUserModal && (
        <div className="fixed inset-0 bg-black/20 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <motion.div
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="bg-white w-full max-w-md rounded-3xl shadow-2xl border border-black/5 overflow-hidden"
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
                  <div className="relative">
                    <input
                      type={showNewUserPwd ? 'text' : 'password'}
                      title={t('password')}
                      value={newUserForm.password}
                      onChange={(e) => setNewUserForm({ ...newUserForm, password: e.target.value })}
                      className={`${inputClass(fieldError('password', newUserForm.password))} pr-12`}
                      placeholder="••••••••"
                    />
                    <button type="button" onClick={() => setShowNewUserPwd(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60 transition-colors">
                      {showNewUserPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
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
                <div className="grid grid-cols-3 gap-3">
                  <div className="space-y-2">
                    <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '真实姓名' : 'Display Name'}</label>
                    <input
                      type="text"
                      title={isZh ? '真实姓名' : 'Display Name'}
                      value={newUserForm.display_name}
                      onChange={(e) => setNewUserForm({ ...newUserForm, display_name: e.target.value })}
                      className={inputClass(fieldError('display_name', newUserForm.display_name))}
                      placeholder={isZh ? '如：李兵' : 'e.g. Li Bing'}
                    />
                    {fieldError('display_name', newUserForm.display_name) && <p className="text-[10px] text-red-500">{fieldError('display_name', newUserForm.display_name)}</p>}
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '手机号' : 'Phone'}</label>
                    <input
                      type="tel"
                      title={isZh ? '手机号' : 'Phone'}
                      value={newUserForm.phone}
                      onChange={(e) => setNewUserForm({ ...newUserForm, phone: e.target.value })}
                      className={inputClass(fieldError('phone', newUserForm.phone))}
                      placeholder="138xxxx8888"
                    />
                    {fieldError('phone', newUserForm.phone) && <p className="text-[10px] text-red-500">{fieldError('phone', newUserForm.phone)}</p>}
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '邮箱' : 'Email'}</label>
                    <input
                      type="email"
                      title={isZh ? '邮箱' : 'Email'}
                      value={newUserForm.email}
                      onChange={(e) => setNewUserForm({ ...newUserForm, email: e.target.value })}
                      className={inputClass(fieldError('email', newUserForm.email))}
                      placeholder="li@example.com"
                    />
                    {fieldError('email', newUserForm.email) && <p className="text-[10px] text-red-500">{fieldError('email', newUserForm.email)}</p>}
                  </div>
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
            className="bg-white w-full max-w-md rounded-3xl shadow-2xl border border-black/5 overflow-hidden"
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
                  <div className="relative">
                    <input
                      type={showEditUserPwd ? 'text' : 'password'}
                      title={t('password')}
                      value={editUserForm.password}
                      onChange={(e) => setEditUserForm({ ...editUserForm, password: e.target.value })}
                      className="w-full px-4 pr-12 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all"
                      placeholder="••••••••"
                    />
                    <button type="button" onClick={() => setShowEditUserPwd(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-black/30 hover:text-black/60 transition-colors">
                      {showEditUserPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
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
                <div className="grid grid-cols-3 gap-3">
                  <div className="space-y-2">
                    <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '真实姓名' : 'Display Name'}</label>
                    <input
                      type="text"
                      title={isZh ? '真实姓名' : 'Display Name'}
                      value={editUserForm.display_name}
                      onChange={(e) => setEditUserForm({ ...editUserForm, display_name: e.target.value })}
                      className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all"
                      placeholder={isZh ? '如：李兵' : 'e.g. Li Bing'}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '手机号' : 'Phone'}</label>
                    <input
                      type="tel"
                      title={isZh ? '手机号' : 'Phone'}
                      value={editUserForm.phone}
                      onChange={(e) => setEditUserForm({ ...editUserForm, phone: e.target.value })}
                      className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all"
                      placeholder="138xxxx8888"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-semibold uppercase tracking-wider text-black/40 ml-1">{isZh ? '邮箱' : 'Email'}</label>
                    <input
                      type="email"
                      title={isZh ? '邮箱' : 'Email'}
                      value={editUserForm.email}
                      onChange={(e) => setEditUserForm({ ...editUserForm, email: e.target.value })}
                      className="w-full px-4 py-3 rounded-xl border border-black/10 focus:border-black focus:ring-4 focus:ring-black/5 outline-none transition-all"
                      placeholder="li@example.com"
                    />
                  </div>
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
