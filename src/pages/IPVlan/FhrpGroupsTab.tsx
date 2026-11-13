import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertCircle, Link2, Plus, RefreshCw, Search, ShieldCheck, Trash2, Unlink, Users, X,
} from 'lucide-react';
import PageHero from '../../components/PageHero';
import Pagination from '../../components/Pagination';
import { ActionButton, ActionIconButton } from '../../components/ui/ActionIconButton';
import { ApiError, apiRequest, createClientRequestId } from '../../api/http';
import {
  addFhrpGroupMember,
  attachFhrpGroupVip,
  createFhrpGroup,
  deleteFhrpGroup,
  detachFhrpGroupVip,
  getFhrpGroup,
  getFhrpGroupCurrent,
  listFhrpGroups,
  removeFhrpGroupMember,
  searchFhrpVipOptions,
  updateFhrpGroup,
  type IpamFhrpGroupCreateInput,
  type IpamFhrpGroupDetail,
  type IpamFhrpGroupSummary,
  type IpamFhrpCurrentObservation,
  type IpamFhrpCollectionState,
  type IpamFhrpGroupType,
  type IpamFhrpProtocol,
  type IpamFhrpStatus,
  type IpamFhrpVipSearchResult,
} from '../../api/ipam';
import { useEscapeClose } from '../../hooks/useEscapeClose';
import { useFocusTrap } from '../../hooks/useFocusTrap';

interface FhrpGroupsTabProps {
  language: string;
  t: (key: string) => string;
}

interface AddressSpaceOption {
  id: string;
  name: string;
  kind: 'global' | 'vrf';
  vrf_id?: string | null;
  vrf_name?: string | null;
  status?: string;
}

interface DeviceOption {
  id: string;
  hostname?: string;
  name?: string;
  device_name?: string;
  ip_address?: string;
  management_ip?: string;
  status?: string;
}

interface GroupPage {
  items: IpamFhrpGroupSummary[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

type DialogState = 'create' | 'edit' | 'member' | 'vip' | null;
type ConfirmAction =
  | { kind: 'delete-group'; group: IpamFhrpGroupDetail }
  | { kind: 'remove-member'; memberId: string; label: string }
  | { kind: 'detach-vip'; vipId: string; address: string }
  | null;

interface GroupFormState {
  address_space_id: string;
  group_type: IpamFhrpGroupType;
  protocol: IpamFhrpProtocol;
  group_id: string;
  address_family: 4 | 6;
  display_name: string;
  status: IpamFhrpStatus;
}

interface MemberFormState {
  device_id: string;
  interface_name: string;
  role: string;
  priority: string;
  status: IpamFhrpStatus;
}

const EMPTY_GROUP_FORM: GroupFormState = {
  address_space_id: '',
  group_type: 'fhrp',
  protocol: 'vrrp',
  group_id: '',
  address_family: 4,
  display_name: '',
  status: 'active',
};

const EMPTY_MEMBER_FORM: MemberFormState = {
  device_id: '',
  interface_name: '',
  role: '',
  priority: '',
  status: 'active',
};

const unwrapItems = <T,>(payload: unknown): T[] => {
  if (Array.isArray(payload)) return payload as T[];
  if (!payload || typeof payload !== 'object') return [];
  const record = payload as { items?: unknown; data?: unknown };
  if (Array.isArray(record.items)) return record.items as T[];
  if (Array.isArray(record.data)) return record.data as T[];
  if (record.data && typeof record.data === 'object') return unwrapItems<T>(record.data);
  return [];
};

const errorMessage = (error: unknown, zh: boolean, fallback: string): string => {
  if (error instanceof ApiError) {
    if (error.status === 401) return zh ? '登录已过期，请重新登录后重试。' : 'Your session expired. Sign in and retry.';
    if (error.status === 403) return zh ? '当前账号没有执行此操作的权限。' : 'You do not have permission to perform this action.';
    if (error.status === 404) return zh ? '记录已不存在或当前账号不可见，请刷新列表。' : 'The record no longer exists or is outside your scope. Refresh the list.';
    if (error.status === 409) return zh
      ? `数据已变化或关联条件冲突，请刷新后重试。${error.message ? ` ${error.message}` : ''}`
      : `The data changed or the relationship conflicts. Refresh and retry.${error.message ? ` ${error.message}` : ''}`;
    return error.message || fallback;
  }
  return error instanceof Error && error.message ? error.message : fallback;
};

const addressSpaceLabel = (space: AddressSpaceOption, zh: boolean): string => (
  space.kind === 'vrf'
    ? `${space.name || space.id} · ${space.vrf_name || space.vrf_id || 'VRF'}`
    : `${space.name || space.id} · ${zh ? '全局' : 'Global'}`
);

const deviceLabel = (device: DeviceOption): string => {
  const name = device.hostname || device.name || device.device_name || device.id;
  const address = device.management_ip || device.ip_address;
  return address && address !== name ? `${name} · ${address}` : name;
};

const protocolLabel = (protocol: IpamFhrpProtocol, zh: boolean): string => {
  if (protocol === 'hsrp') return 'HSRP';
  if (protocol === 'vrrp') return 'VRRP';
  return zh ? 'Anycast' : 'Anycast';
};

const collectionStatusLabel = (status: string, zh: boolean): string => {
  const labels: Record<string, [string, string]> = {
    complete: ['完整采集', 'Complete'],
    failed: ['采集失败', 'Failed'],
    partial: ['部分采集', 'Partial'],
    unsupported: ['暂不支持', 'Unsupported'],
    skipped: ['已跳过', 'Skipped'],
    in_progress: ['采集中', 'In progress'],
  };
  const normalized = String(status || '').trim().toLowerCase();
  return labels[normalized]?.[zh ? 0 : 1] || normalized || (zh ? '未采集' : 'Not collected');
};

const collectionErrorLabel = (errorCode: string, zh: boolean): string => {
  const labels: Record<string, [string, string]> = {
    platform_unsupported: ['当前采集器尚不支持此设备平台。', 'The current collector does not support this device platform.'],
    credential_resolution_failed: ['未能解析设备 SSH 凭据。', 'The device SSH credentials could not be resolved.'],
    ssh_not_configured: ['设备尚未配置可用的 SSH 连接参数。', 'No usable SSH connection settings are configured for the device.'],
    ssh_banner_unavailable: [
      'SSH 协议 Banner 未收到：设备在执行查询命令前关闭了连接。',
      'The SSH protocol banner was not received; the connection closed before the query command ran.',
    ],
    ssh_algorithm_mismatch: [
      'SSH 算法协商失败：检查双方支持的密钥交换、主机密钥和加密算法。',
      'SSH algorithm negotiation failed; check key-exchange, host-key, and cipher compatibility.',
    ],
    cli_command_unsupported: ['设备不支持当前 FHRP 查询命令。', 'The device does not support the current FHRP query command.'],
    cli_output_incomplete: ['命令输出不完整，未能确认当前快照。', 'The command output was incomplete, so the current snapshot could not be confirmed.'],
    cli_collection_failed: ['FHRP 命令采集失败，未生成新的成功快照。', 'FHRP command collection failed; no new successful snapshot was produced.'],
  };
  const normalized = String(errorCode || '').trim().toLowerCase();
  return labels[normalized]?.[zh ? 0 : 1] || normalized;
};

const formatTime = (value: string, language: string): string => {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', { hour12: false });
};

const idempotencyFingerprint = (operation: string, payload: unknown): string => (
  `${operation}:${JSON.stringify(payload)}`
);

const FhrpGroupsTab: React.FC<FhrpGroupsTabProps> = ({ language }) => {
  const zh = language === 'zh';
  const [addressSpaces, setAddressSpaces] = useState<AddressSpaceOption[]>([]);
  const [addressSpacesLoading, setAddressSpacesLoading] = useState(true);
  const [addressSpacesError, setAddressSpacesError] = useState('');
  const [selectedSpaceId, setSelectedSpaceId] = useState('');
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [groups, setGroups] = useState<GroupPage>({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1 });
  const [groupsLoading, setGroupsLoading] = useState(true);
  const [groupsError, setGroupsError] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [groupDetail, setGroupDetail] = useState<IpamFhrpGroupDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [currentObservations, setCurrentObservations] = useState<IpamFhrpCurrentObservation[]>([]);
  const [collectionStates, setCollectionStates] = useState<IpamFhrpCollectionState[]>([]);
  const [currentLoading, setCurrentLoading] = useState(false);
  const [currentError, setCurrentError] = useState('');
  const [dialog, setDialog] = useState<DialogState>(null);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [groupForm, setGroupForm] = useState<GroupFormState>(EMPTY_GROUP_FORM);
  const [memberForm, setMemberForm] = useState<MemberFormState>(EMPTY_MEMBER_FORM);
  const [devices, setDevices] = useState<DeviceOption[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [devicesError, setDevicesError] = useState('');
  const [vipQuery, setVipQuery] = useState('');
  const [vipOptions, setVipOptions] = useState<IpamFhrpVipSearchResult[]>([]);
  const [vipSearchLoading, setVipSearchLoading] = useState(false);
  const [vipSearchError, setVipSearchError] = useState('');
  const [formError, setFormError] = useState('');
  const [mutationError, setMutationError] = useState('');
  const [saving, setSaving] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const pendingRequest = useRef<{ fingerprint: string; key: string } | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);
  const confirmDialogRef = useRef<HTMLElement | null>(null);
  const vipSearchController = useRef<AbortController | null>(null);
  const groupListRequest = useRef(0);
  const detailRequest = useRef(0);

  const activeAddressSpaces = useMemo(
    () => addressSpaces.filter((space) => (space.status || 'active').toLowerCase() === 'active'),
    [addressSpaces],
  );

  const closeDialog = useCallback(() => {
    if (saving) return;
    setDialog(null);
    setFormError('');
  }, [saving]);
  useEscapeClose(Boolean(dialog), closeDialog);
  useEscapeClose(Boolean(confirmAction), () => { if (!saving) setConfirmAction(null); });
  useFocusTrap(dialogRef, Boolean(dialog), 'input, select, button');
  useFocusTrap(confirmDialogRef, Boolean(confirmAction), 'button');

  const getIdempotencyKey = (operation: string, payload: unknown): string => {
    const fingerprint = idempotencyFingerprint(operation, payload);
    if (!pendingRequest.current || pendingRequest.current.fingerprint !== fingerprint) {
      pendingRequest.current = { fingerprint, key: createClientRequestId('ipam-fhrp') };
    }
    return pendingRequest.current.key;
  };

  const clearIdempotencyKey = () => { pendingRequest.current = null; };

  useEffect(() => {
    const controller = new AbortController();
    setAddressSpacesLoading(true);
    setAddressSpacesError('');
    apiRequest<unknown>('/api/ipam/address-spaces', { signal: controller.signal })
      .then((payload) => {
        const rows = unwrapItems<AddressSpaceOption>(payload).filter(
          (space) => space.id && (space.kind === 'global' || space.kind === 'vrf'),
        );
        setAddressSpaces(rows);
        if (selectedSpaceId && !rows.some((space) => space.id === selectedSpaceId)) setSelectedSpaceId('');
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setAddressSpaces([]);
        setAddressSpacesError(errorMessage(error, zh, zh ? '加载地址空间失败。' : 'Failed to load address spaces.'));
      })
      .finally(() => { if (!controller.signal.aborted) setAddressSpacesLoading(false); });
    return () => controller.abort();
    // selectedSpaceId is intentionally not a dependency: lookup refresh must not loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshToken, zh]);

  const reloadGroups = useCallback(() => setRefreshToken((token) => token + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const requestId = ++groupListRequest.current;
    setGroupsLoading(true);
    setGroupsError('');
    listFhrpGroups({
      addressSpaceId: selectedSpaceId,
      search,
      page,
      pageSize,
      signal: controller.signal,
    })
      .then((payload) => {
        if (requestId !== groupListRequest.current) return;
        setGroups({
          items: Array.isArray(payload.items) ? payload.items : [],
          total: Number(payload.total || 0),
          page: Number(payload.page || page),
          page_size: Number(payload.page_size || pageSize),
          total_pages: Number(payload.total_pages || 1),
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestId !== groupListRequest.current) return;
        setGroups({ items: [], total: 0, page, page_size: pageSize, total_pages: 1 });
        setGroupsError(errorMessage(error, zh, zh ? '加载 FHRP 组失败。' : 'Failed to load FHRP groups.'));
      })
      .finally(() => {
        if (!controller.signal.aborted && requestId === groupListRequest.current) setGroupsLoading(false);
      });
    return () => controller.abort();
  }, [page, pageSize, refreshToken, search, selectedSpaceId, zh]);

  useEffect(() => {
    if (!selectedGroupId) {
      setGroupDetail(null);
      setDetailError('');
      setDetailLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    const requestId = ++detailRequest.current;
    setGroupDetail(null);
    setDetailLoading(true);
    setDetailError('');
    getFhrpGroup(selectedGroupId, controller.signal)
      .then((detail) => {
        if (requestId === detailRequest.current) setGroupDetail(detail);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestId !== detailRequest.current) return;
        setDetailError(errorMessage(error, zh, zh ? '加载组详情失败。' : 'Failed to load group details.'));
      })
      .finally(() => {
        if (!controller.signal.aborted && requestId === detailRequest.current) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [selectedGroupId, refreshToken, zh]);

  useEffect(() => {
    if (!selectedGroupId) {
      setCurrentObservations([]);
      setCollectionStates([]);
      setCurrentLoading(false);
      setCurrentError('');
      return undefined;
    }
    const controller = new AbortController();
    setCurrentObservations([]);
    setCollectionStates([]);
    setCurrentLoading(true);
    setCurrentError('');
    getFhrpGroupCurrent(selectedGroupId, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setCurrentObservations(Array.isArray(payload.items) ? payload.items : []);
        setCollectionStates(Array.isArray(payload.collection_states) ? payload.collection_states : []);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setCurrentObservations([]);
        setCollectionStates([]);
        setCurrentError(errorMessage(error, zh, zh ? '加载当前运行观察失败。' : 'Failed to load current runtime observations.'));
      })
      .finally(() => { if (!controller.signal.aborted) setCurrentLoading(false); });
    return () => controller.abort();
  }, [selectedGroupId, refreshToken, zh]);

  useEffect(() => {
    if (dialog !== 'member') return undefined;
    const controller = new AbortController();
    setDevicesLoading(true);
    setDevicesError('');
    apiRequest<unknown>('/api/devices?mode=light', { signal: controller.signal })
      .then((payload) => setDevices(unwrapItems<DeviceOption>(payload).filter((device) => device.id)))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setDevices([]);
        setDevicesError(errorMessage(error, zh, zh ? '加载设备选项失败。' : 'Failed to load devices.'));
      })
      .finally(() => { if (!controller.signal.aborted) setDevicesLoading(false); });
    return () => controller.abort();
  }, [dialog, zh]);

  useEffect(() => () => vipSearchController.current?.abort(), []);

  const refreshGroupDetail = () => {
    setRefreshToken((token) => token + 1);
  };

  const openCreate = () => {
    pendingRequest.current = null;
    setGroupForm({ ...EMPTY_GROUP_FORM, address_space_id: selectedSpaceId || activeAddressSpaces[0]?.id || '' });
    setMutationError('');
    setFormError('');
    setDialog('create');
  };

  const openEdit = () => {
    if (!groupDetail) return;
    pendingRequest.current = null;
    setGroupForm({
      address_space_id: groupDetail.address_space_id,
      group_type: groupDetail.group_type,
      protocol: groupDetail.protocol,
      group_id: groupDetail.group_id,
      address_family: groupDetail.address_family,
      display_name: groupDetail.display_name,
      status: groupDetail.status,
    });
    setMutationError('');
    setFormError('');
    setDialog('edit');
  };

  const openAddMember = () => {
    setMemberForm(EMPTY_MEMBER_FORM);
    setFormError('');
    setMutationError('');
    setDialog('member');
  };

  const openAttachVip = () => {
    vipSearchController.current?.abort();
    setVipQuery('');
    setVipOptions([]);
    setVipSearchLoading(false);
    setVipSearchError('');
    setFormError('');
    setMutationError('');
    setDialog('vip');
  };

  const handleSearch = (event: React.FormEvent) => {
    event.preventDefault();
    setSearch(searchDraft.trim());
    setPage(1);
  };

  const changeSpace = (value: string) => {
    setSelectedSpaceId(value);
    setPage(1);
    setSelectedGroupId('');
    setGroupDetail(null);
  };

  const submitGroup = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');
    if (!groupForm.address_space_id || !groupForm.group_id.trim()) {
      setFormError(zh ? '请选择地址空间并填写组标识。' : 'Select an address space and enter a group ID.');
      return;
    }
    const payload: IpamFhrpGroupCreateInput = {
      address_space_id: groupForm.address_space_id,
      group_type: groupForm.group_type,
      protocol: groupForm.group_type === 'anycast' ? 'anycast' : groupForm.protocol,
      group_id: groupForm.group_id.trim(),
      address_family: groupForm.address_family,
      display_name: groupForm.display_name.trim(),
      status: groupForm.status,
    };
    setSaving(true);
    try {
      if (dialog === 'create') {
        const result = await createFhrpGroup(payload, getIdempotencyKey('group.create', payload));
        setSelectedGroupId(result.id);
        clearIdempotencyKey();
      } else if (dialog === 'edit' && groupDetail) {
        const updatePayload = {
          expected_revision: groupDetail.revision,
          group_id: payload.group_id,
          display_name: payload.display_name,
          status: payload.status,
        };
        const result = await updateFhrpGroup(
          groupDetail.id,
          updatePayload,
          getIdempotencyKey('group.update', updatePayload),
        );
        setSelectedGroupId(result.id);
        clearIdempotencyKey();
      }
      setDialog(null);
      setFormError('');
      setRefreshToken((token) => token + 1);
    } catch (error) {
      setFormError(errorMessage(error, zh, zh ? '保存 FHRP 组失败。' : 'Failed to save the group.'));
    } finally {
      setSaving(false);
    }
  };

  const submitMember = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!groupDetail) return;
    setFormError('');
    if (!memberForm.device_id || !memberForm.interface_name.trim()) {
      setFormError(zh ? '请选择设备并填写接口名称。' : 'Select a device and enter an interface name.');
      return;
    }
    const priority = memberForm.priority.trim() ? Number(memberForm.priority) : undefined;
    if (priority !== undefined && (!Number.isInteger(priority) || priority < 0 || priority > 255)) {
      setFormError(zh ? '优先级必须为 0–255 的整数。' : 'Priority must be an integer from 0 to 255.');
      return;
    }
    const payload = {
      expected_revision: groupDetail.revision,
      device_id: memberForm.device_id,
      interface_name: memberForm.interface_name.trim(),
      role: memberForm.role.trim() || undefined,
      priority,
      status: memberForm.status,
    };
    setSaving(true);
    try {
      await addFhrpGroupMember(groupDetail.id, payload, getIdempotencyKey('member.add', payload));
      clearIdempotencyKey();
      setDialog(null);
      setRefreshToken((token) => token + 1);
    } catch (error) {
      setFormError(errorMessage(error, zh, zh ? '添加成员失败。' : 'Failed to add the member.'));
    } finally {
      setSaving(false);
    }
  };

  const searchVips = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!vipQuery.trim()) {
      setVipSearchError(zh ? '输入 VIP 地址或描述后再搜索。' : 'Enter a VIP address or description to search.');
      return;
    }
    vipSearchController.current?.abort();
    const controller = new AbortController();
    vipSearchController.current = controller;
    setVipSearchLoading(true);
    setVipSearchError('');
    try {
      const payload = await searchFhrpVipOptions(vipQuery.trim(), controller.signal);
      setVipOptions(Array.isArray(payload.items) ? payload.items : []);
    } catch (error) {
      if (controller.signal.aborted) return;
      setVipOptions([]);
      setVipSearchError(errorMessage(error, zh, zh ? '搜索 VIP 失败。' : 'Failed to search VIPs.'));
    } finally {
      if (!controller.signal.aborted) setVipSearchLoading(false);
    }
  };

  const eligibleVips = useMemo(() => {
    if (!groupDetail) return [];
    const linkedIds = new Set(groupDetail.vips.map((vip) => vip.vip_id));
    return vipOptions.filter((vip) => (
      vip.address_space_id === groupDetail.address_space_id
      && String(vip.vip_type || '').toLowerCase() === groupDetail.protocol
      && (String(vip.address || '').includes(':') ? 6 : 4) === groupDetail.address_family
      && String(vip.status || '').toLowerCase() === 'active'
      && !linkedIds.has(vip.id)
    ));
  }, [groupDetail, vipOptions]);

  const attachVip = async (vipId: string) => {
    if (!groupDetail) return;
    const payload = { expected_revision: groupDetail.revision, vip_id: vipId };
    setSaving(true);
    setFormError('');
    try {
      await attachFhrpGroupVip(
        groupDetail.id,
        payload,
        getIdempotencyKey('vip.attach', payload),
      );
      clearIdempotencyKey();
      setDialog(null);
      setRefreshToken((token) => token + 1);
    } catch (error) {
      setFormError(errorMessage(error, zh, zh ? '关联 VIP 失败。' : 'Failed to link the VIP.'));
    } finally {
      setSaving(false);
    }
  };

  const confirmMutation = async () => {
    if (!confirmAction || !groupDetail) return;
    setSaving(true);
    setMutationError('');
    try {
      if (confirmAction.kind === 'delete-group') {
        await deleteFhrpGroup(
          confirmAction.group.id,
          confirmAction.group.revision,
          getIdempotencyKey('group.delete', { id: confirmAction.group.id, revision: confirmAction.group.revision }),
        );
        clearIdempotencyKey();
        setSelectedGroupId('');
      } else if (confirmAction.kind === 'remove-member') {
        await removeFhrpGroupMember(
          groupDetail.id,
          confirmAction.memberId,
          groupDetail.revision,
          getIdempotencyKey('member.remove', { id: confirmAction.memberId, revision: groupDetail.revision }),
        );
        clearIdempotencyKey();
      } else {
        await detachFhrpGroupVip(
          groupDetail.id,
          confirmAction.vipId,
          groupDetail.revision,
          getIdempotencyKey('vip.detach', { id: confirmAction.vipId, revision: groupDetail.revision }),
        );
        clearIdempotencyKey();
      }
      setConfirmAction(null);
      setRefreshToken((token) => token + 1);
    } catch (error) {
      setMutationError(errorMessage(error, zh, zh ? '操作失败，请刷新后重试。' : 'The action failed. Refresh and retry.'));
    } finally {
      setSaving(false);
    }
  };

  const groupName = (group: IpamFhrpGroupSummary | IpamFhrpGroupDetail) => (
    group.display_name.trim() || `${protocolLabel(group.protocol, zh)} ${group.group_id}`
  );

  const dialogTitle = dialog === 'create'
    ? (zh ? '新增 FHRP / Anycast 组' : 'Add FHRP / Anycast group')
    : dialog === 'edit'
      ? (zh ? '编辑组信息' : 'Edit group')
      : dialog === 'member'
        ? (zh ? '添加组成员' : 'Add group member')
        : (zh ? '关联正式 VIP' : 'Link a formal VIP');

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden" style={{ background: 'var(--ui-surface)' }}>
      <PageHero
        icon={ShieldCheck}
        title={zh ? 'FHRP 与 Anycast' : 'FHRP and Anycast'}
        subtitle={zh ? '明确管理冗余组、成员接口和正式 VIP 关系' : 'Manage explicit redundancy groups, member interfaces and formal VIP links'}
        eyebrow={zh ? 'IP 地址管理' : 'IPAM'}
        actions={(
          <>
            <ActionButton icon={RefreshCw} variant="default" onClick={reloadGroups} disabled={groupsLoading || addressSpacesLoading}>
              {zh ? '刷新' : 'Refresh'}
            </ActionButton>
            <ActionButton icon={Plus} variant="primary" onClick={openCreate} disabled={addressSpacesLoading || activeAddressSpaces.length === 0}>
              {zh ? '新增组' : 'Add group'}
            </ActionButton>
          </>
        )}
        extras={(
          <form onSubmit={handleSearch} className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-300">
              {zh ? '地址空间' : 'Address space'}
              <select
                aria-label={zh ? '筛选地址空间' : 'Filter address space'}
                value={selectedSpaceId}
                onChange={(event) => changeSpace(event.target.value)}
                disabled={addressSpacesLoading || Boolean(addressSpacesError)}
                className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none focus:border-cyan-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
                <option value="">{zh ? '全部地址空间' : 'All address spaces'}</option>
                {activeAddressSpaces.map((space) => (
                  <option key={space.id} value={space.id}>{addressSpaceLabel(space, zh)}</option>
                ))}
              </select>
            </label>
            <label className="flex min-w-0 flex-[2] flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-300">
              {zh ? '搜索组标识或名称' : 'Search group ID or name'}
              <span className="flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 focus-within:border-cyan-500 dark:border-slate-700 dark:bg-slate-900">
                <Search size={15} className="shrink-0 text-slate-400" />
                <input
                  aria-label={zh ? '搜索组标识或名称' : 'Search group ID or name'}
                  value={searchDraft}
                  onChange={(event) => setSearchDraft(event.target.value)}
                  placeholder={zh ? '组标识 / 显示名称' : 'Group ID / display name'}
                  className="min-w-0 flex-1 border-0 bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100"
                />
              </span>
            </label>
            <ActionButton type="submit" icon={Search} variant="default">
              {zh ? '搜索' : 'Search'}
            </ActionButton>
          </form>
        )}
      />

      <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-6">
        {addressSpacesError && (
          <div role="alert" className="mb-4 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
            <AlertCircle size={17} className="mt-0.5 shrink-0" />
            <span>{addressSpacesError}</span>
          </div>
        )}
        {!addressSpacesLoading && !addressSpacesError && activeAddressSpaces.length === 0 && (
          <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
            <div className="font-semibold">{zh ? '还没有可用地址空间' : 'No active address spaces are available'}</div>
            <p className="mt-1 text-xs opacity-80">
              {zh ? '请先在“网段”中创建全局地址空间，或为 VRF 建立明确映射；本页不会替你推断默认空间。' : 'Create an explicit Global space or map a VRF from Prefixes first. This page will not infer a default space.'}
            </p>
          </div>
        )}
        {groupsError && (
          <div role="alert" className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
            <span className="flex items-start gap-2"><AlertCircle size={17} className="mt-0.5 shrink-0" />{groupsError}</span>
            <ActionButton onClick={reloadGroups} variant="default">{zh ? '重试' : 'Retry'}</ActionButton>
          </div>
        )}
        {mutationError && (
          <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">{mutationError}</div>
        )}

        <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
          <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-700">
              <div className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-100">
                <Activity size={16} className="text-cyan-600" />
                {zh ? '正式冗余组' : 'Formal redundancy groups'}
              </div>
              <span className="text-xs text-slate-500 dark:text-slate-400">{zh ? `共 ${groups.total} 组` : `${groups.total} groups`}</span>
            </div>
            {groupsLoading && (
              <div role="status" className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">{zh ? '正在加载组列表…' : 'Loading groups…'}</div>
            )}
            {!groupsLoading && !groupsError && groups.items.length === 0 && (
              <div className="p-8 text-center">
                <Users size={28} className="mx-auto text-slate-300 dark:text-slate-600" />
                <div className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">
                  {search ? (zh ? '没有匹配的组' : 'No groups match this search') : (zh ? '当前范围没有正式组' : 'No formal groups in this scope')}
                </div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{zh ? '新建组后，可明确登记成员接口并关联已有正式 VIP。' : 'Create a group, register member interfaces and link existing formal VIPs.'}</p>
              </div>
            )}
            {!groupsLoading && groups.items.length > 0 && (
              <div className="overflow-x-auto">
                <table className="nx-table w-full min-w-[690px] text-left text-sm">
                  <thead>
                    <tr>
                      <th>{zh ? '组' : 'Group'}</th>
                      <th>{zh ? '类型' : 'Type'}</th>
                      <th>{zh ? '地址空间' : 'Address space'}</th>
                      <th>{zh ? '地址族' : 'Family'}</th>
                      <th>{zh ? '状态' : 'Status'}</th>
                      <th>{zh ? '版本' : 'Revision'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.items.map((group) => {
                      const selected = selectedGroupId === group.id;
                      return (
                        <tr key={group.id} className={selected ? 'bg-cyan-50/70 dark:bg-cyan-950/20' : ''}>
                          <td className="max-w-[220px]">
                            <button
                              type="button"
                              onClick={() => setSelectedGroupId(group.id)}
                              className="block max-w-full text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-500"
                              aria-current={selected ? 'true' : undefined}
                            >
                              <span className="block truncate font-semibold text-slate-800 dark:text-slate-100">{groupName(group)}</span>
                              <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{group.group_id}</span>
                            </button>
                          </td>
                          <td>
                            <span className="inline-flex rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                              {group.group_type === 'anycast' ? 'Anycast' : protocolLabel(group.protocol, zh)}
                            </span>
                          </td>
                          <td className="max-w-[190px] truncate text-xs text-slate-600 dark:text-slate-300">{group.address_space_name || group.address_space_id}</td>
                          <td className="whitespace-nowrap text-xs text-slate-600 dark:text-slate-300">IPv{group.address_family}</td>
                          <td>
                            <span className={group.status === 'active'
                              ? 'inline-flex rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
                              : 'inline-flex rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300'}>
                              {group.status === 'active' ? (zh ? '启用' : 'Active') : (zh ? '停用' : 'Disabled')}
                            </span>
                          </td>
                          <td className="text-xs text-slate-500 dark:text-slate-400">{group.revision}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <Pagination
              currentPage={page}
              totalItems={groups.total}
              onPageChange={setPage}
              itemsPerPage={pageSize}
              onItemsPerPageChange={(size) => { setPageSize(size); setPage(1); }}
              language={language}
              itemLabel={zh ? '组' : 'groups'}
            />
          </section>

          <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
            {!selectedGroupId && (
              <div className="flex min-h-[260px] flex-col items-center justify-center p-8 text-center">
                <ShieldCheck size={28} className="text-slate-300 dark:text-slate-600" />
                <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">{zh ? '选择一个组查看详细关系' : 'Select a group to inspect its relationships'}</p>
                <p className="mt-1 max-w-sm text-xs text-slate-500 dark:text-slate-400">{zh ? '列表只返回组摘要；成员与 VIP 仅在打开详情时按权限加载。' : 'The list returns group summaries. Members and VIPs load on demand and follow access scope.'}</p>
              </div>
            )}
            {selectedGroupId && detailLoading && (
              <div role="status" className="p-8 text-center text-sm text-slate-500 dark:text-slate-400">{zh ? '正在加载关系详情…' : 'Loading relationship details…'}</div>
            )}
            {selectedGroupId && detailError && !detailLoading && (
              <div role="alert" className="p-5 text-sm text-red-700 dark:text-red-300">
                <p>{detailError}</p>
                <ActionButton className="mt-3" onClick={refreshGroupDetail}>{zh ? '重试' : 'Retry'}</ActionButton>
              </div>
            )}
            {groupDetail && !detailLoading && !detailError && (
              <>
                <div className="border-b border-slate-200 p-4 dark:border-slate-700">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                        {groupDetail.group_type === 'anycast' ? 'Anycast' : protocolLabel(groupDetail.protocol, zh)} · IPv{groupDetail.address_family}
                      </div>
                      <h2 className="mt-1 truncate text-base font-semibold text-slate-900 dark:text-white">{groupName(groupDetail)}</h2>
                      <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">
                        {groupDetail.address_space_name || groupDetail.address_space_id} · {zh ? '版本' : 'Revision'} {groupDetail.revision}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <ActionButton onClick={openEdit} variant="default">{zh ? '编辑' : 'Edit'}</ActionButton>
                      <ActionButton
                        onClick={() => setConfirmAction({ kind: 'delete-group', group: groupDetail })}
                        variant="danger"
                      >
                        <Trash2 size={15} />{zh ? '删除' : 'Delete'}
                      </ActionButton>
                    </div>
                  </div>
                  {groupDetail.group_type === 'anycast' && (
                    <p className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs text-cyan-900 dark:border-cyan-900 dark:bg-cyan-950/30 dark:text-cyan-100">
                      {zh ? 'Anycast 共享由这一条正式 VIP 和多条成员接口关系表示；不会为每台设备重复创建 VIP。' : 'Anycast sharing is represented by one formal VIP and multiple member interfaces; a VIP is not duplicated per device.'}
                    </p>
                  )}
                </div>

                <div className="border-b border-slate-200 p-4 dark:border-slate-700">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{zh ? '成员接口' : 'Member interfaces'}</h3>
                      <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">{zh ? '设备与接口必须明确登记；采集到的相同 IP/MAC 不会自动认领成员。' : 'Register each device and interface explicitly; matching IP/MAC observations do not auto-claim members.'}</p>
                    </div>
                    <ActionButton icon={Plus} onClick={openAddMember} variant="default">{zh ? '添加成员' : 'Add member'}</ActionButton>
                  </div>
                  {groupDetail.members.length === 0 ? (
                    <p className="rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">{zh ? '当前账号可见范围内没有成员。' : 'No members are visible in the current access scope.'}</p>
                  ) : (
                    <div className="space-y-2">
                      {groupDetail.members.map((member) => (
                        <div key={member.id} className="flex min-w-0 items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/70">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">{member.device_name}</div>
                            <div className="truncate text-xs text-slate-500 dark:text-slate-400">{member.interface_name}{member.role ? ` · ${member.role}` : ''}{member.priority !== null ? ` · ${zh ? '优先级' : 'Priority'} ${member.priority}` : ''}</div>
                          </div>
                          <ActionIconButton
                            icon={Unlink}
                            label={zh ? '移除成员' : 'Remove member'}
                            variant="danger"
                            onClick={() => setConfirmAction({ kind: 'remove-member', memberId: member.id, label: `${member.device_name} · ${member.interface_name}` })}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="p-4">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{zh ? '正式 VIP' : 'Formal VIPs'}</h3>
                      <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">{zh ? '只关联已有正式 VIP；不会从运行观察自动建账。' : 'Link existing formal VIPs only; runtime observations never create ledger entries.'}</p>
                    </div>
                    <ActionButton
                      icon={Link2}
                      onClick={openAttachVip}
                      variant="default"
                      disabled={groupDetail.group_type === 'anycast' && groupDetail.vips.length > 0}
                    >
                      {zh ? '关联 VIP' : 'Link VIP'}
                    </ActionButton>
                  </div>
                  {groupDetail.vips.length === 0 ? (
                    <p className="rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">{zh ? '当前账号可见范围内没有关联 VIP。' : 'No VIP links are visible in the current access scope.'}</p>
                  ) : (
                    <div className="space-y-2">
                      {groupDetail.vips.map((vip) => (
                        <div key={vip.vip_id} className="flex min-w-0 items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/70">
                          <div className="min-w-0">
                            <div className="truncate font-mono text-sm font-semibold text-slate-800 dark:text-slate-100">{vip.address}</div>
                            <div className="truncate text-xs text-slate-500 dark:text-slate-400">{protocolLabel(groupDetail.protocol, zh)} · {vip.status} · rev {vip.revision}</div>
                          </div>
                          <ActionIconButton
                            icon={Unlink}
                            label={zh ? '解除 VIP 关联' : 'Unlink VIP'}
                            variant="danger"
                            onClick={() => setConfirmAction({ kind: 'detach-vip', vipId: vip.vip_id, address: vip.address })}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {groupDetail.group_type === 'fhrp' && (
                  <div className="border-t border-slate-200 p-4 dark:border-slate-700">
                    <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{zh ? '当前运行观察' : 'Current runtime observations'}</h3>
                        <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">{zh ? '仅显示当前快照；未知或不匹配范围不会自动关联或登记 VIP。此操作只重载已保存结果，不发起设备连接。' : 'Shows only the current snapshot. Unknown or mismatched scope never auto-links or registers a VIP. Reloading does not start a device session.'}</p>
                      </div>
                      <ActionButton icon={RefreshCw} onClick={refreshGroupDetail} variant="default" disabled={currentLoading}>
                        {currentLoading ? (zh ? '重载中…' : 'Reloading…') : (zh ? '重载快照' : 'Reload snapshot')}
                      </ActionButton>
                    </div>
                    {currentError && <p role="alert" className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">{currentError}</p>}
                    {collectionStates.length > 0 && (
                      <div className="mb-3 flex flex-wrap gap-2">
                        {collectionStates.map((state) => (
                          <div key={`${state.device_id}:${state.protocol}`} className="rounded-lg bg-slate-50 px-3 py-2 text-xs dark:bg-slate-800/70">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <span className="font-medium text-slate-700 dark:text-slate-200">{state.device_name}</span>
                              <span className={state.latest_status === 'complete'
                                ? 'font-medium text-emerald-700 dark:text-emerald-300'
                                : state.latest_status === 'failed'
                                  ? 'font-medium text-red-700 dark:text-red-300'
                                  : 'font-medium text-amber-700 dark:text-amber-300'}>
                                {collectionStatusLabel(state.latest_status, zh)}
                              </span>
                              <span className="text-slate-500 dark:text-slate-400">
                                {state.last_success_at
                                  ? `${zh ? '最近成功' : 'Last success'} ${formatTime(state.last_success_at, language)}`
                                  : (zh ? '暂无成功快照' : 'No successful snapshot')}
                              </span>
                            </div>
                            {state.last_attempt_at && (
                              <div className="mt-1 text-slate-500 dark:text-slate-400">
                                {zh ? '最近尝试' : 'Last attempt'} {formatTime(state.last_attempt_at, language)}
                                <span className="mx-1">·</span>
                                {zh ? '代次' : 'Generation'} {state.latest_attempt_generation}
                              </div>
                            )}
                            {state.last_error_code && (
                              <div role="note" className="mt-1 text-red-700 dark:text-red-300">
                                {collectionErrorLabel(state.last_error_code, zh)}
                                <code className="ml-1 rounded bg-red-100 px-1 py-0.5 text-[10px] dark:bg-red-950/60">{state.last_error_code}</code>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {currentLoading && currentObservations.length === 0 && !currentError && (
                      <p role="status" className="rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">{zh ? '正在加载当前观察…' : 'Loading current observations…'}</p>
                    )}
                    {!currentLoading && currentObservations.length === 0 && !currentError && (
                      <p className="rounded-lg bg-slate-50 px-3 py-3 text-xs text-slate-500 dark:bg-slate-800/70 dark:text-slate-400">
                        {collectionStates.length > 0 && collectionStates.every((state) => state.latest_status === 'complete' && state.current_row_count === 0)
                          ? (zh ? '最新完整采集未发现该组的运行观察。' : 'The latest complete collection found no runtime rows for this group.')
                          : (zh ? '尚无可用的当前采集观察；等待下一次采集或检查设备覆盖状态。' : 'No current collection is available yet. Wait for the next collection or review device coverage.')}
                      </p>
                    )}
                    {!currentLoading && currentObservations.length > 0 && (
                      <div className="overflow-x-auto">
                        <table className="nx-table w-full min-w-[740px] text-left text-xs">
                          <thead><tr>
                            <th>{zh ? '设备 / 接口' : 'Device / interface'}</th>
                            <th>{zh ? 'VIP 观察' : 'Observed VIP'}</th>
                            <th>{zh ? '运行状态' : 'Runtime state'}</th>
                            <th>{zh ? '优先级' : 'Priority'}</th>
                            <th>{zh ? '范围' : 'Scope'}</th>
                            <th>{zh ? '最近成功' : 'Last success'}</th>
                          </tr></thead>
                          <tbody>
                            {currentObservations.map((observation) => (
                              <tr key={observation.id}>
                                <td>
                                  <div className="font-medium text-slate-800 dark:text-slate-100">{observation.source_device_name}</div>
                                  <div className="text-slate-500 dark:text-slate-400">{observation.interface_name}</div>
                                </td>
                                <td>
                                  <div className="font-mono font-semibold text-slate-800 dark:text-slate-100">{observation.virtual_ip || '—'}</div>
                                  <div className="font-mono text-slate-500 dark:text-slate-400">{observation.virtual_mac || '—'}</div>
                                </td>
                                <td>
                                  <div className="font-medium text-slate-700 dark:text-slate-200">{observation.state || '—'}</div>
                                  {!observation.coverage_complete && <div className="text-amber-700 dark:text-amber-300">{observation.collection_status || (zh ? '覆盖不完整' : 'Coverage incomplete')}</div>}
                                </td>
                                <td className="text-slate-700 dark:text-slate-200">{observation.priority ?? '—'}</td>
                                <td>
                                  {observation.group_scope_status === 'resolved'
                                    ? <span className="text-emerald-700 dark:text-emerald-300">{observation.address_space_name || (zh ? '已匹配' : 'Matched')}</span>
                                    : observation.group_scope_status === 'scope_mismatch'
                                      ? <span className="text-amber-700 dark:text-amber-300">{zh ? '地址空间不匹配' : 'Address space mismatch'}</span>
                                      : <span className="text-amber-700 dark:text-amber-300">{zh ? '范围待确认' : 'Scope pending'}</span>}
                                </td>
                                <td className="whitespace-nowrap text-slate-500 dark:text-slate-400">{formatTime(observation.last_success_at, language)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>

      {dialog && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-3 sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDialog(); }}>
          <section ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="fhrp-dialog-title" className="max-h-[92vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-2xl focus:outline-none dark:border-slate-700 dark:bg-slate-900">
            <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4 dark:border-slate-700 dark:bg-slate-900">
              <div className="min-w-0">
                <h2 id="fhrp-dialog-title" className="text-base font-semibold text-slate-900 dark:text-white">{dialogTitle}</h2>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {dialog === 'vip'
                    ? (zh ? '按地址或描述搜索，并仅选择空间、协议和地址族匹配的已有 VIP。' : 'Search by address or description. Only existing VIPs with matching space, protocol and family are eligible.')
                    : dialog === 'member'
                      ? (zh ? '接口必须已登记在所选设备下。' : 'The interface must already belong to the selected device.')
                      : (zh ? '组身份仅在选定地址空间内有效。' : 'The group identity is scoped to the selected address space.')}
                </p>
              </div>
              <ActionIconButton icon={X} label={zh ? '关闭' : 'Close'} onClick={closeDialog} disabled={saving} />
            </header>

            {(dialog === 'create' || dialog === 'edit') && (
              <form onSubmit={submitGroup} className="space-y-4 p-5">
                {dialog === 'create' && (
                  <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    {zh ? '地址空间' : 'Address space'}
                    <select required value={groupForm.address_space_id} onChange={(event) => setGroupForm((form) => ({ ...form, address_space_id: event.target.value }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950">
                      <option value="">{zh ? '请选择明确的地址空间' : 'Select an explicit address space'}</option>
                      {activeAddressSpaces.map((space) => <option key={space.id} value={space.id}>{addressSpaceLabel(space, zh)}</option>)}
                    </select>
                  </label>
                )}
                {dialog === 'create' && (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                      {zh ? '组类型' : 'Group type'}
                      <select value={groupForm.group_type} onChange={(event) => {
                        const groupType = event.target.value as IpamFhrpGroupType;
                        setGroupForm((form) => ({ ...form, group_type: groupType, protocol: groupType === 'anycast' ? 'anycast' : 'vrrp' }));
                      }} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950">
                        <option value="fhrp">FHRP</option>
                        <option value="anycast">Anycast</option>
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                      {zh ? '协议' : 'Protocol'}
                      <select disabled={groupForm.group_type === 'anycast'} value={groupForm.protocol} onChange={(event) => setGroupForm((form) => ({ ...form, protocol: event.target.value as IpamFhrpProtocol }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950">
                        <option value="hsrp">HSRP</option>
                        <option value="vrrp">VRRP</option>
                        {groupForm.group_type === 'anycast' && <option value="anycast">Anycast</option>}
                      </select>
                    </label>
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    {zh ? '本地组标识' : 'Local group ID'}
                    <input required maxLength={100} value={groupForm.group_id} onChange={(event) => setGroupForm((form) => ({ ...form, group_id: event.target.value }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder={groupForm.group_type === 'anycast' ? 'fabric-edge-a' : '10'} />
                  </label>
                  {dialog === 'create' && (
                    <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                      {zh ? '地址族' : 'Address family'}
                      <select value={groupForm.address_family} onChange={(event) => setGroupForm((form) => ({ ...form, address_family: Number(event.target.value) as 4 | 6 }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950">
                        <option value={4}>IPv4</option>
                        <option value={6}>IPv6</option>
                      </select>
                    </label>
                  )}
                </div>
                <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                  {zh ? '显示名称' : 'Display name'}
                  <input maxLength={200} value={groupForm.display_name} onChange={(event) => setGroupForm((form) => ({ ...form, display_name: event.target.value }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950" />
                </label>
                <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                  {zh ? '状态' : 'Status'}
                  <select value={groupForm.status} onChange={(event) => setGroupForm((form) => ({ ...form, status: event.target.value as IpamFhrpStatus }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950">
                    <option value="active">{zh ? '启用' : 'Active'}</option>
                    <option value="disabled">{zh ? '停用' : 'Disabled'}</option>
                  </select>
                </label>
                {formError && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">{formError}</p>}
                <footer className="flex justify-end gap-2 border-t border-slate-200 pt-4 dark:border-slate-700">
                  <ActionButton onClick={closeDialog} disabled={saving}>{zh ? '取消' : 'Cancel'}</ActionButton>
                  <ActionButton type="submit" variant="primary" disabled={saving || (dialog === 'create' && activeAddressSpaces.length === 0)}>{saving ? (zh ? '保存中…' : 'Saving…') : (zh ? '保存' : 'Save')}</ActionButton>
                </footer>
              </form>
            )}

            {dialog === 'member' && (
              <form onSubmit={submitMember} className="space-y-4 p-5">
                <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                  {zh ? '设备' : 'Device'}
                  <select required value={memberForm.device_id} onChange={(event) => setMemberForm((form) => ({ ...form, device_id: event.target.value }))} disabled={devicesLoading || Boolean(devicesError)} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm disabled:opacity-60 dark:border-slate-700 dark:bg-slate-950">
                    <option value="">{devicesLoading ? (zh ? '加载设备…' : 'Loading devices…') : (zh ? '请选择设备' : 'Select a device')}</option>
                    {devices.map((device) => <option key={device.id} value={device.id}>{deviceLabel(device)}</option>)}
                  </select>
                </label>
                {devicesError && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{devicesError}</p>}
                <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                  {zh ? '接口名称' : 'Interface name'}
                  <input required maxLength={200} value={memberForm.interface_name} onChange={(event) => setMemberForm((form) => ({ ...form, interface_name: event.target.value }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder="GigabitEthernet0/1" />
                  <span className="text-[11px] font-normal text-slate-500 dark:text-slate-400">{zh ? '后端会核对该接口属于所选设备。' : 'The server verifies that this interface belongs to the selected device.'}</span>
                </label>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    {zh ? '角色（可选）' : 'Role (optional)'}
                    <input maxLength={80} value={memberForm.role} onChange={(event) => setMemberForm((form) => ({ ...form, role: event.target.value }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder={zh ? '主用 / 备用' : 'master / backup'} />
                  </label>
                  <label className="flex flex-col gap-1 text-sm font-medium text-slate-700 dark:text-slate-200">
                    {zh ? '优先级（可选）' : 'Priority (optional)'}
                    <input type="number" min={0} max={255} step={1} value={memberForm.priority} onChange={(event) => setMemberForm((form) => ({ ...form, priority: event.target.value }))} className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950" />
                  </label>
                </div>
                {formError && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">{formError}</p>}
                <footer className="flex justify-end gap-2 border-t border-slate-200 pt-4 dark:border-slate-700">
                  <ActionButton onClick={closeDialog} disabled={saving}>{zh ? '取消' : 'Cancel'}</ActionButton>
                  <ActionButton type="submit" variant="primary" disabled={saving || devicesLoading || Boolean(devicesError)}>{saving ? (zh ? '添加中…' : 'Adding…') : (zh ? '添加成员' : 'Add member')}</ActionButton>
                </footer>
              </form>
            )}

            {dialog === 'vip' && groupDetail && (
              <div className="space-y-4 p-5">
                <form onSubmit={searchVips} className="flex flex-col gap-2 sm:flex-row">
                  <label className="sr-only" htmlFor="fhrp-vip-search">{zh ? '搜索 VIP 地址或描述' : 'Search VIP address or description'}</label>
                  <input id="fhrp-vip-search" value={vipQuery} onChange={(event) => setVipQuery(event.target.value)} className="h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950" placeholder={zh ? '输入 VIP 地址或描述' : 'Enter a VIP address or description'} />
                  <ActionButton type="submit" icon={Search} disabled={vipSearchLoading}>{vipSearchLoading ? (zh ? '搜索中…' : 'Searching…') : (zh ? '搜索已有 VIP' : 'Search VIPs')}</ActionButton>
                </form>
                {vipSearchError && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{vipSearchError}</p>}
                {!vipSearchLoading && vipQuery.trim() && vipOptions.length === 0 && !vipSearchError && <p className="text-sm text-slate-500 dark:text-slate-400">{zh ? '没有匹配的 VIP。' : 'No VIPs matched.'}</p>}
                {!vipSearchLoading && vipOptions.length > 0 && eligibleVips.length === 0 && (
                  <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                    {zh ? '搜索结果中没有符合当前组地址空间、协议和地址族的未关联 VIP。' : 'No search result is unlinked and compatible with this group’s space, protocol and address family.'}
                  </p>
                )}
                {eligibleVips.length > 0 && (
                  <div className="max-h-64 space-y-2 overflow-auto">
                    {eligibleVips.map((vip) => (
                      <div key={vip.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
                        <div className="min-w-0">
                          <div className="truncate font-mono text-sm font-semibold text-slate-800 dark:text-slate-100">{vip.address}</div>
                          <div className="truncate text-xs text-slate-500 dark:text-slate-400">{vip.address_space_name || vip.address_space_id} · {vip.vip_type}</div>
                        </div>
                        <ActionButton onClick={() => void attachVip(vip.id)} variant="primary" disabled={saving}>{zh ? '关联' : 'Link'}</ActionButton>
                      </div>
                    ))}
                  </div>
                )}
                {formError && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">{formError}</p>}
                <footer className="flex justify-end border-t border-slate-200 pt-4 dark:border-slate-700">
                  <ActionButton onClick={closeDialog} disabled={saving}>{zh ? '关闭' : 'Close'}</ActionButton>
                </footer>
              </div>
            )}
          </section>
        </div>
      )}

      {confirmAction && (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-4">
          <section ref={confirmDialogRef} tabIndex={-1} role="alertdialog" aria-modal="true" aria-labelledby="fhrp-confirm-title" aria-describedby="fhrp-confirm-description" className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl focus:outline-none dark:border-slate-700 dark:bg-slate-900">
            <h2 id="fhrp-confirm-title" className="text-base font-semibold text-slate-900 dark:text-white">{zh ? '确认此操作？' : 'Confirm this action?'}</h2>
            <p id="fhrp-confirm-description" className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {confirmAction.kind === 'delete-group'
                ? (zh ? `删除组“${groupName(confirmAction.group)}”？只允许删除没有成员和 VIP 关联的组。` : `Delete “${groupName(confirmAction.group)}”? A group can be deleted only after its members and VIP links are removed.`)
                : confirmAction.kind === 'remove-member'
                  ? (zh ? `从当前组移除 ${confirmAction.label}？` : `Remove ${confirmAction.label} from this group?`)
                  : (zh ? `解除 VIP ${confirmAction.address} 与当前组的关联？` : `Unlink VIP ${confirmAction.address} from this group?`)}
            </p>
            {mutationError && <p role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">{mutationError}</p>}
            <footer className="mt-5 flex justify-end gap-2">
              <ActionButton onClick={() => { setConfirmAction(null); setMutationError(''); }} disabled={saving}>{zh ? '取消' : 'Cancel'}</ActionButton>
              <ActionButton onClick={() => void confirmMutation()} variant="danger" disabled={saving}>{saving ? (zh ? '处理中…' : 'Working…') : (zh ? '确认' : 'Confirm')}</ActionButton>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
};

export default FhrpGroupsTab;
