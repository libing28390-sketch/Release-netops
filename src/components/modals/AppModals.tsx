import React from 'react';
import ProfileModal from '../ProfileModal';
import type { ProfileFormState } from '../ProfileModal';
import TestConnectionResultModal from '../TestConnectionResultModal';
import ImportInventoryModal from '../ImportInventoryModal';
import ConfigDiffModal from '../ConfigDiffModal';
import HistoricalConfigModal from '../HistoricalConfigModal';
import ScheduleTaskModal from '../ScheduleTaskModal';
import RemediationModal from '../RemediationModal';
import DeleteConfirmModal from '../DeleteConfirmModal';
import DeviceFormModal from '../DeviceFormModal';
import DeviceDetailModal from '../DeviceDetailModal';
import SnmpTestResultModal from '../SnmpTestResultModal';
import AuditEventDetailModal from '../AuditEventDetailModal';
import ComplianceFindingDetailModal from '../ComplianceFindingDetailModal';
import JobOutputModal from '../JobOutputModal';
import { User as UserIcon } from 'lucide-react';

/** All global modals extracted from App.tsx to reduce its line count. */
export const AppModals: React.FC<any> = (props) => {
  // Destructure everything from props so existing JSX works unchanged.
  const {
    // ProfileModal
    showProfileModal, language, resolvedTheme, currentUser, currentUserRecord,
    currentUserLastLogin, profileAvatarPreview, avatarPresets, profileForm,
    showProfilePwd, notificationChannels, notifyTestLoading, renderAvatarContent,
    setShowProfileModal, handleSaveProfile, handleProfileAvatarChange,
    setProfileAvatarPreview, setProfileForm, setShowProfilePwd, setNotificationChannels,
    setNotifyTestLoading, showToast, setCurrentUser,
    // TestConnectionResultModal
    showTestResult, isTestingConnection, connectionTestMode, connectionTestDevice,
    selectedDevice, testResult, setShowTestResult, handleTestConnection,
    // ImportInventoryModal
    showImportModal, t, setShowImportModal,
    // ConfigDiffModal
    showDiff, currentDiff, setShowDiff, runTask,
    // HistoricalConfigModal
    showConfigModal, viewingConfig, setShowConfigModal, handleRollbackConfig,
    // ScheduleTaskModal
    showScheduleModal, schedulingTask, scheduleForm, setScheduleForm, setShowScheduleModal, handleScheduleTask,
    // RemediationModal
    showRemediationModal, remediatingDevice, setShowRemediationModal, confirmRemediation,
    // DeleteConfirmModal
    showDeleteModal, isDeletingSelected, selectedDeviceIds, setShowDeleteModal,
    setDeviceToDelete, setIsDeletingSelected, confirmDeleteDevice,
    // DeviceFormModal (add)
    showAddModal, addForm, showAddDevicePwd, setAddForm, setShowAddDevicePwd, setShowAddModal, handleAddDevice,
    // DeviceFormModal (edit)
    showEditModal, editingDevice, editForm, showEditDevicePwd, setEditForm, setShowEditDevicePwd, setShowEditModal, handleSaveEdit,
    // Lifecycle confirm
    showLifecycleConfirm, lifecycleConfirmChecked, setLifecycleConfirmChecked, setShowLifecycleConfirm,
    // DeviceDetailModal
    showDetailsModal, viewingDevice, viewingDeviceAlerts, deviceDetailLoading, deviceConnectionChecks,
    connectionTestingDeviceId, deviceTrendRangeHours, setDeviceTrendRangeHours, deviceHealthTrend, deviceHealthTrendLoading,
    deviceOperationalData, deviceOperationalDataLoading, loadDeviceOperationalData,
    handleSnmpTest, snmpTestingId, handleSnmpSyncNow, snmpSyncingId,
    setSelectedDevice, setShowDetailsModal,
    // SnmpTestResultModal
    showSnmpTestResult, snmpTestResult, setShowSnmpTestResult,
    // AuditEventDetailModal
    selectedAuditEvent, setSelectedAuditEvent,
    // ComplianceFindingDetailModal
    selectedFinding, setSelectedFinding, updateComplianceFinding,
    // JobOutputModal
    selectedJob, setSelectedJob, copyTextWithFallback,
    // Navigate helper
    navigate,
  } = props;

  // Local helper for setActiveTab (navigation-based)
  const setActiveTab = (tab: string) => {
    navigate('/' + tab);
  };

  return (
    <>
      <ProfileModal
        open={showProfileModal}
        language={language}
        resolvedTheme={resolvedTheme}
        currentRole={currentUser.role || currentUserRecord?.role || 'Administrator'}
        currentUserLastLogin={currentUserLastLogin}
        profileAvatarPreview={profileAvatarPreview}
        avatarPresets={avatarPresets}
        profileForm={profileForm}
        showProfilePwd={showProfilePwd}
        notificationChannels={notificationChannels}
        notifyTestLoading={notifyTestLoading}
        renderAvatarContent={renderAvatarContent}
        onClose={() => setShowProfileModal(false)}
        onSave={handleSaveProfile}
        onAvatarFileChange={handleProfileAvatarChange}
        onClearAvatar={() => setProfileAvatarPreview('')}
        onSelectAvatarPreset={setProfileAvatarPreview}
        onProfileFormChange={setProfileForm}
        onToggleProfilePassword={() => setShowProfilePwd((value) => !value)}
        mfaEnabled={!!(currentUser?.mfa_enabled || currentUserRecord?.mfa_enabled)}
        onMfaStatusChange={(enabled) => {
          if (setCurrentUser) {
            setCurrentUser((prev: any) => ({ ...prev, mfa_enabled: enabled }));
          }
        }}
        onNotificationChannelToggle={(channel) => setNotificationChannels((prev) => ({ ...prev, [channel]: { ...prev[channel], enabled: !prev[channel].enabled } }))}
        onNotificationWebhookChange={(channel, value) => setNotificationChannels((prev) => ({ ...prev, [channel]: { ...prev[channel], webhook_url: value } }))}
        onNotificationSecretChange={(value) => setNotificationChannels((prev) => ({ ...prev, dingtalk: { ...prev.dingtalk, secret: value } }))}
        onTestNotificationChannel={async (channel) => {
          const profileUserId = currentUser.id ?? currentUserRecord?.id;
          if (!profileUserId) return;
          const currentChannel = notificationChannels[channel];
          setNotifyTestLoading(channel);
          try {
            const response = await fetch(`/api/users/${profileUserId}/notify-test`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('sessionToken') || ''}`,
              },
              body: JSON.stringify({
                platform: channel,
                webhook_url: currentChannel.webhook_url,
                secret: channel === 'dingtalk' ? notificationChannels.dingtalk.secret : '',
              }),
            });
            const data = await response.json();
            if (response.ok) showToast(`${channel === 'feishu' ? '飞书' : channel === 'dingtalk' ? '钉钉' : '企业微信'} 测试消息已发送 ✓`, 'success');
            else showToast(`发送失败: ${data.detail || data.error}`, 'error');
          } catch {
            showToast('连接错误', 'error');
          } finally {
            setNotifyTestLoading('');
          }
        }}
      />

      {/* Test Connection Result Modal */}
      {showTestResult && (
        <TestConnectionResultModal
          open={showTestResult}
          language={language}
          isTestingConnection={isTestingConnection}
          connectionTestMode={connectionTestMode}
          connectionTestDevice={connectionTestDevice}
          selectedDevice={selectedDevice}
          testResult={testResult}
          onClose={() => setShowTestResult(false)}
          onRetry={handleTestConnection}
        />
      )}

      <ImportInventoryModal
        open={showImportModal}
        language={language}
        t={t}
        onClose={() => setShowImportModal(false)}
        onImport={() => {
          alert('Import feature simulation: Data processed successfully.');
          setShowImportModal(false);
        }}
      />

      <ConfigDiffModal
        open={showDiff}
        language={language}
        t={t}
        selectedDevice={selectedDevice}
        currentDiff={currentDiff}
        onClose={() => setShowDiff(false)}
        onCommit={() => {
          void runTask('VLAN Update');
        }}
      />

      <HistoricalConfigModal
        open={showConfigModal}
        language={language}
        t={t}
        selectedDevice={selectedDevice}
        viewingConfig={viewingConfig}
        onClose={() => setShowConfigModal(false)}
        onRollback={() => {
          if (!selectedDevice || !viewingConfig) return;
          void handleRollbackConfig(selectedDevice, viewingConfig);
        }}
      />

      <ScheduleTaskModal
        open={showScheduleModal}
        language={language}
        t={t}
        selectedDevice={selectedDevice}
        schedulingTask={schedulingTask}
        scheduleForm={scheduleForm}
        onScheduleFormChange={setScheduleForm}
        onClose={() => setShowScheduleModal(false)}
        onSubmit={handleScheduleTask}
      />

      <RemediationModal
        open={showRemediationModal}
        language={language}
        t={t}
        device={remediatingDevice}
        onClose={() => setShowRemediationModal(false)}
        onConfirm={confirmRemediation}
      />

      <DeleteConfirmModal
        open={showDeleteModal}
        language={language}
        isDeletingSelected={isDeletingSelected}
        selectedDeviceCount={selectedDeviceIds.length}
        onClose={() => {
          setShowDeleteModal(false);
          setDeviceToDelete(null);
          setIsDeletingSelected(false);
        }}
        onConfirm={() => {
          void confirmDeleteDevice();
        }}
      />

      {/* Edit Device Modal */}
      {/* Add Device Modal */}
      {showAddModal && (
        <DeviceFormModal
          mode="add"
          language={language}
          form={addForm}
          passwordVisible={showAddDevicePwd}
          onFormChange={setAddForm}
          onTogglePasswordVisibility={() => setShowAddDevicePwd((value) => !value)}
          onClose={() => setShowAddModal(false)}
          onSubmit={handleAddDevice}
        />
      )}

      {showEditModal && editingDevice && (
        <DeviceFormModal
          mode="edit"
          language={language}
          form={editForm}
          passwordVisible={showEditDevicePwd}
          onFormChange={setEditForm}
          onTogglePasswordVisibility={() => setShowEditDevicePwd((value) => !value)}
          onClose={() => setShowEditModal(false)}
          onSubmit={handleSaveEdit}
        />
      )}

      {/* Lifecycle → Production Confirmation Modal */}
      {showLifecycleConfirm && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center gap-3 border-b border-black/5 bg-amber-50 p-5 rounded-t-2xl">
              <div className="rounded-lg bg-amber-100 p-2 text-amber-600">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              </div>
              <h3 className="text-base font-semibold text-black">
                {language === 'zh' ? '投产确认' : 'Production Confirmation'}
              </h3>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-sm text-black/70 leading-relaxed">
                {language === 'zh'
                  ? '您正在将设备状态设置为「已投产」。请确认该设备的默认口令已完成上手（密码已从出厂默认修改为正式口令）。'
                  : 'You are setting this device to "Production". Please confirm that the default credentials have been changed from factory defaults to production passwords.'}
              </p>
              <label className="flex items-start gap-2.5 cursor-pointer select-none group">
                <input
                  type="checkbox"
                  checked={lifecycleConfirmChecked}
                  onChange={(e) => setLifecycleConfirmChecked(e.target.checked)}
                  className="mt-0.5 rounded border-black/20 text-[#00bceb] focus:ring-[#00bceb] focus:ring-offset-0"
                />
                <span className="text-sm font-medium text-black/80 group-hover:text-black">
                  {language === 'zh'
                    ? '我确认该设备默认口令已上手，密码已修改为正式口令'
                    : 'I confirm the default credentials have been changed to production passwords'}
                </span>
              </label>
            </div>
            <div className="flex gap-3 border-t border-black/5 bg-black/[0.01] p-5 rounded-b-2xl">
              <button
                onClick={() => { setShowLifecycleConfirm(null); setLifecycleConfirmChecked(false); }}
                className="flex-1 rounded-xl border border-black/10 px-4 py-2.5 text-xs font-bold uppercase tracking-widest transition-all hover:bg-black/5"
              >
                {language === 'zh' ? '取消' : 'Cancel'}
              </button>
              <button
                disabled={!lifecycleConfirmChecked}
                onClick={() => {
                  if (showLifecycleConfirm === 'add') {
                    handleAddDevice();
                  } else {
                    handleSaveEdit();
                  }
                }}
                className={`flex-1 rounded-xl px-4 py-2.5 text-xs font-bold uppercase tracking-widest text-white shadow-lg transition-all
                  ${lifecycleConfirmChecked
                    ? 'bg-amber-500 shadow-amber-500/20 hover:bg-amber-600 cursor-pointer'
                    : 'bg-black/20 shadow-none cursor-not-allowed'}`}
              >
                {language === 'zh' ? '确认投产' : 'Confirm Production'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Device Details Modal */}
      {showDetailsModal && viewingDevice && (
        <DeviceDetailModal
          language={language}
          t={t}
          viewingDevice={viewingDevice}
          viewingDeviceAlerts={viewingDeviceAlerts}
          deviceDetailLoading={deviceDetailLoading}
          viewingDeviceConnectionSummary={viewingDevice.id ? deviceConnectionChecks[viewingDevice.id] : null}
          connectionTestingDeviceId={connectionTestingDeviceId}
          onClose={() => setShowDetailsModal(false)}
          deviceTrendRangeHours={deviceTrendRangeHours}
          onDeviceTrendRangeHoursChange={setDeviceTrendRangeHours}
          deviceHealthTrend={deviceHealthTrend}
          deviceHealthTrendLoading={deviceHealthTrendLoading}
          deviceOperationalData={deviceOperationalData}
          deviceOperationalDataLoading={deviceOperationalDataLoading}
          onLoadOperationalData={loadDeviceOperationalData}
          onTestConnection={handleTestConnection}
          isTestingConnection={isTestingConnection}
          onSnmpTest={handleSnmpTest}
          snmpTestingId={snmpTestingId}
          onSnmpSyncNow={handleSnmpSyncNow}
          snmpSyncingId={snmpSyncingId}
          onGoToAutomation={(device) => {
            setSelectedDevice(device);
            setActiveTab('automation');
            setShowDetailsModal(false);
          }}
        />
      )}

      {/* SNMP Test Result Modal */}
      {showSnmpTestResult && (
        <SnmpTestResultModal
          open={showSnmpTestResult}
          language={language}
          result={snmpTestResult}
          onClose={() => setShowSnmpTestResult(false)}
        />
      )}

      <AuditEventDetailModal
        event={selectedAuditEvent as any}
        language={language}
        t={t}
        onClose={() => setSelectedAuditEvent(null)}
      />

      <ComplianceFindingDetailModal
        finding={selectedFinding as any}
        language={language}
        t={t}
        onClose={() => setSelectedFinding(null)}
        onStatusChange={(value) => setSelectedFinding((prev) => (prev ? { ...prev, status: value } : prev))}
        onOwnerChange={(value) => setSelectedFinding((prev) => (prev ? { ...prev, owner: value } : prev))}
        onNoteChange={(value) => setSelectedFinding((prev) => (prev ? { ...prev, note: value } : prev))}
        onSave={() => {
          if (!selectedFinding) return;
          void updateComplianceFinding(selectedFinding.id, {
            status: selectedFinding.status,
            owner: selectedFinding.owner,
            note: selectedFinding.note,
          });
        }}
      />

      <JobOutputModal
        job={selectedJob}
        t={t}
        onClose={() => setSelectedJob(null)}
        onCopy={async () => {
          const copied = await copyTextWithFallback(selectedJob?.output || '');
          showToast(t('copied'), copied ? 'success' : 'error');
        }}
      />
    </>
  );
};
