import { useState, useCallback } from 'react';

import type { User } from '../types';

interface UseUserManagementProps {
  currentUser: { id?: string; username?: string; role?: string; avatar_url?: string };
  setCurrentUser: React.Dispatch<React.SetStateAction<any>>;
  language: string;
  showToast: (msg: string, type: string) => void;
}

const createEmptyUserForm = () => ({
  username: '', password: '', role: 'Operator', group_name: '', change_groups: [] as string[],
  display_name: '', phone: '', email: '',
});

export const useUserManagement = ({ currentUser, setCurrentUser, language, showToast }: UseUserManagementProps) => {
  const [users, setUsers] = useState<User[]>([]);
  const [showAddUserModal, setShowAddUserModal] = useState(false);
  const [showEditUserModal, setShowEditUserModal] = useState(false);
  const [showNewUserPwd, setShowNewUserPwd] = useState(false);
  const [showEditUserPwd, setShowEditUserPwd] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editUserForm, setEditUserForm] = useState(createEmptyUserForm);
  const [newUserForm, setNewUserForm] = useState(createEmptyUserForm);

  const handleAddUser = useCallback(async () => {
    if (!newUserForm.username.trim() || !newUserForm.password.trim()) {
      showToast(language === 'zh' ? '请填写用户名和密码' : 'Username and password are required', 'error');
      return;
    }
    try {
      const token = localStorage.getItem('netops_token');
      const response = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          ...newUserForm,
          actor_username: currentUser.username || 'admin',
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || response.statusText);
      setUsers((prev) => [...prev, data]);
      setShowAddUserModal(false);
      setNewUserForm(createEmptyUserForm());
      setShowNewUserPwd(false);
      showToast(language === 'zh' ? '用户已创建' : 'User created', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `创建用户失败: ${message}` : `Failed to create user: ${message}`, 'error');
    }
  }, [newUserForm, currentUser, language, showToast]);

  const handleEditUser = useCallback(async () => {
    if (!editingUser) return;
    if (!editUserForm.username.trim()) {
      showToast(language === 'zh' ? '请输入用户名' : 'Username is required', 'error');
      return;
    }
    try {
      const token = localStorage.getItem('netops_token');
      const response = await fetch(`/api/users/${editingUser.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          username: editUserForm.username.trim(),
          password: editUserForm.password,
          role: editUserForm.role,
          group_name: editUserForm.group_name,
          change_groups: editUserForm.change_groups,
          display_name: editUserForm.display_name,
          phone: editUserForm.phone,
          email: editUserForm.email,
          actor_username: currentUser.username || 'admin',
          actor_role: currentUser.role || 'Administrator',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || response.statusText);
      setUsers((prev) => prev.map((user) => (String(user.id) === String(editingUser.id) ? { ...user, ...data } : user)));
      if (String(currentUser.id) === String(editingUser.id)) {
        setCurrentUser((prev: any) => ({ ...prev, ...data }));
      }
      setShowEditUserModal(false);
      setEditingUser(null);
      setEditUserForm(createEmptyUserForm());
      setShowEditUserPwd(false);
      showToast(language === 'zh' ? '用户已更新' : 'User updated', 'success');
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      showToast(language === 'zh' ? `更新用户失败: ${message}` : `Failed to update user: ${message}`, 'error');
    }
  }, [editingUser, editUserForm, currentUser, setCurrentUser, language, showToast]);

  return {
    users, setUsers,
    showAddUserModal, setShowAddUserModal,
    showEditUserModal, setShowEditUserModal,
    showNewUserPwd, setShowNewUserPwd,
    showEditUserPwd, setShowEditUserPwd,
    editingUser, setEditingUser,
    editUserForm, setEditUserForm,
    newUserForm, setNewUserForm,
    createEmptyUserForm,
    handleAddUser,
    handleEditUser,
  };
};
