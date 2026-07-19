import { useCallback, useState } from 'react';
import type { ProfileFormState } from '../components/ProfileModal';
import type { Language } from '../i18n.tsx';
import type { SessionUser, User as UserType } from '../types';

export interface NotificationChannelsState {
  feishu: { webhook_url: string; enabled: boolean; creator_username?: string };
  dingtalk: { webhook_url: string; enabled: boolean; secret: string; creator_username?: string };
  wechat: { webhook_url: string; enabled: boolean; creator_username?: string };
}

const EMPTY_PROFILE_FORM: ProfileFormState = {
  username: '',
  oldPassword: '',
  password: '',
  confirmPassword: '',
  fixedPin: '',
  displayName: '',
  phone: '',
  email: '',
};

const EMPTY_CHANNELS: NotificationChannelsState = {
  feishu: { webhook_url: '', enabled: false },
  dingtalk: { webhook_url: '', enabled: false, secret: '' },
  wechat: { webhook_url: '', enabled: false },
};

interface UseUserProfileArgs {
  currentUser: SessionUser;
  currentUserRecord?: UserType;
  currentAvatar: string;
  language: Language;
  t: (key: string) => string;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  setCurrentUser: React.Dispatch<React.SetStateAction<SessionUser>>;
  setUsers: React.Dispatch<React.SetStateAction<UserType[]>>;
  setShowNotifications: (open: boolean) => void;
  setShowUserMenu: (open: boolean) => void;
}

export const useUserProfile = ({
  currentUser,
  currentUserRecord,
  currentAvatar,
  language,
  t,
  showToast,
  setCurrentUser,
  setUsers,
  setShowNotifications,
  setShowUserMenu,
}: UseUserProfileArgs) => {
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showProfilePwd, setShowProfilePwd] = useState(false);
  const [profileForm, setProfileForm] = useState<ProfileFormState>(EMPTY_PROFILE_FORM);
  const [profileAvatarPreview, setProfileAvatarPreview] = useState('');
  const [notificationChannels, setNotificationChannels] = useState<NotificationChannelsState>(EMPTY_CHANNELS);
  const [notifyTestLoading, setNotifyTestLoading] = useState<string>('');

  const openProfileModal = useCallback(() => {
    setProfileForm({
      username: currentUser.username || currentUserRecord?.username || '',
      oldPassword: '',
      password: '',
      confirmPassword: '',
      // The backend never returns the bcrypt hash.  Keep this field empty so
      // a saved PIN can only be replaced intentionally, never echoed back.
      fixedPin: '',
      displayName: currentUserRecord?.display_name || '',
      phone: currentUserRecord?.phone || '',
      email: currentUserRecord?.email || '',
    });
    setProfileAvatarPreview(currentAvatar);
    setShowProfilePwd(false);
    setShowNotifications(false);
    setShowUserMenu(false);

    const savedChannels = currentUserRecord?.notification_channels as any;
    setNotificationChannels({
      feishu: {
        webhook_url: savedChannels?.feishu?.webhook_url || '',
        enabled: !!savedChannels?.feishu?.enabled,
        creator_username: savedChannels?.feishu?.creator_username || '',
      },
      dingtalk: {
        webhook_url: savedChannels?.dingtalk?.webhook_url || '',
        enabled: !!savedChannels?.dingtalk?.enabled,
        secret: savedChannels?.dingtalk?.secret || '',
        creator_username: savedChannels?.dingtalk?.creator_username || '',
      },
      wechat: {
        webhook_url: savedChannels?.wechat?.webhook_url || '',
        enabled: !!savedChannels?.wechat?.enabled,
        creator_username: savedChannels?.wechat?.creator_username || '',
      },
    });
    setNotifyTestLoading('');
    setShowProfileModal(true);
  }, [
    currentUser.username,
    currentUserRecord,
    currentAvatar,
    setShowNotifications,
    setShowUserMenu,
  ]);

  const handleProfileAvatarChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      showToast('Please select an image file', 'error');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      showToast('Image must be 2MB or smaller', 'error');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        setProfileAvatarPreview(reader.result);
      }
    };
    reader.readAsDataURL(file);
    event.target.value = '';
  }, [showToast]);

  const handleSaveProfile = useCallback(async () => {
    const profileUserId = currentUser.id ?? currentUserRecord?.id;
    if (!profileUserId) {
      showToast('Unable to identify current user', 'error');
      return;
    }
    if (!profileForm.username.trim()) {
      showToast(t('fillAllFields'), 'error');
      return;
    }
    if (profileForm.password && !profileForm.oldPassword) {
      showToast(language === 'zh' ? '修改密码请先输入当前密码' : 'Please enter current password', 'error');
      return;
    }
    if (profileForm.password && profileForm.password !== profileForm.confirmPassword) {
      showToast(language === 'zh' ? '两次输入的密码不一致' : 'Passwords do not match', 'error');
      return;
    }

    try {
      const payload: Record<string, any> = {
        username: profileForm.username.trim(),
        role: (currentUserRecord?.role || currentUser.role || 'Operator') as string,
        avatar_url: profileAvatarPreview,
        notification_channels: notificationChannels,
        fixedPin: profileForm.fixedPin,
        display_name: profileForm.displayName.trim(),
        phone: profileForm.phone.trim(),
        email: profileForm.email.trim(),
      };
      if (profileForm.password) {
        payload.password = profileForm.password;
        payload.old_password = profileForm.oldPassword;
      }

      const response = await fetch(`/api/users/${profileUserId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(localStorage.getItem('netops_token') ? { Authorization: `Bearer ${localStorage.getItem('netops_token')}` } : {}),
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (response.ok) {
        setCurrentUser((prev) => ({
          ...prev,
          username: data.username,
          role: data.role,
          avatar_url: data.avatar_url || '',
        }));
        setUsers((prev) => prev.map((u) => (String(u.id) === String(profileUserId) ? { ...u, ...data } : u)));
        setShowProfileModal(false);
        showToast('Profile updated', 'success');
      } else {
        showToast(`Error: ${data.detail || data.error}`, 'error');
      }
    } catch {
      showToast('Connection error', 'error');
    }
  }, [
    currentUser.id,
    currentUser.role,
    currentUserRecord,
    profileForm,
    profileAvatarPreview,
    notificationChannels,
    language,
    t,
    showToast,
    setCurrentUser,
    setUsers,
  ]);

  return {
    showProfileModal,
    setShowProfileModal,
    showProfilePwd,
    setShowProfilePwd,
    profileForm,
    setProfileForm,
    profileAvatarPreview,
    setProfileAvatarPreview,
    notificationChannels,
    setNotificationChannels,
    notifyTestLoading,
    setNotifyTestLoading,
    openProfileModal,
    handleProfileAvatarChange,
    handleSaveProfile,
  };
};
