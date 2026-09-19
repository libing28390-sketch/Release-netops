import React from 'react';
import { User as UserIcon } from 'lucide-react';

export type AvatarPreset = {
  id: string;
  emoji: string;
  label: string;
  bgClass: string;
};

export const avatarPresets: readonly AvatarPreset[] = [
  { id: 'preset:fox', emoji: '🦊', label: 'Fox', bgClass: 'bg-gradient-to-br from-orange-400 to-amber-600' },
  { id: 'preset:panda', emoji: '🐼', label: 'Panda', bgClass: 'bg-gradient-to-br from-slate-500 to-slate-700' },
  { id: 'preset:tiger', emoji: '🐯', label: 'Tiger', bgClass: 'bg-gradient-to-br from-amber-500 to-orange-600' },
  { id: 'preset:wolf', emoji: '🐺', label: 'Wolf', bgClass: 'bg-gradient-to-br from-zinc-500 to-zinc-700' },
  { id: 'preset:lion', emoji: '🦁', label: 'Lion', bgClass: 'bg-gradient-to-br from-yellow-500 to-amber-700' },
  { id: 'preset:koala', emoji: '🐨', label: 'Koala', bgClass: 'bg-gradient-to-br from-sky-400 to-blue-600' },
  { id: 'preset:owl', emoji: '🦉', label: 'Owl', bgClass: 'bg-gradient-to-br from-violet-500 to-indigo-700' },
  { id: 'preset:penguin', emoji: '🐧', label: 'Penguin', bgClass: 'bg-gradient-to-br from-cyan-500 to-blue-700' },
  { id: 'preset:rabbit', emoji: '🐰', label: 'Rabbit', bgClass: 'bg-gradient-to-br from-pink-400 to-fuchsia-600' },
  { id: 'preset:cat', emoji: '🐱', label: 'Cat', bgClass: 'bg-gradient-to-br from-rose-400 to-red-600' },
  { id: 'preset:dog', emoji: '🐶', label: 'Dog', bgClass: 'bg-gradient-to-br from-emerald-500 to-teal-700' },
  { id: 'preset:whale', emoji: '🐳', label: 'Whale', bgClass: 'bg-gradient-to-br from-cyan-400 to-indigo-600' },
] as const;

export const resolveAvatarPreset = (avatarValue?: string): AvatarPreset | undefined =>
  avatarPresets.find((preset) => preset.id === avatarValue);

export const renderAvatarContent = (avatarValue: string, fallbackIconSize: number) => {
  const preset = resolveAvatarPreset(avatarValue);
  if (preset) {
    const emojiSizeClass = fallbackIconSize <= 15 ? 'text-sm' : fallbackIconSize <= 18 ? 'text-base' : 'text-xl';
    return (
      <div className={`w-full h-full ${preset.bgClass} flex items-center justify-center`}>
        <span className={`${emojiSizeClass} leading-none`}>{preset.emoji}</span>
      </div>
    );
  }
  if (avatarValue?.startsWith('preset:')) {
    return <UserIcon size={fallbackIconSize} />;
  }
  if (avatarValue) {
    return <img src={avatarValue} alt="avatar" className="w-full h-full object-cover" />;
  }
  return <UserIcon size={fallbackIconSize} />;
};
