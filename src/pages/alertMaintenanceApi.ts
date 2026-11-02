import { apiRequest } from '../api/http';
import type { AlertMaintenanceListResponse, AlertMaintenanceWindow } from '../types';
import type { MaintenanceFormState } from './alertManagementShared';

export type CreateAlertMaintenanceWindowPayload = MaintenanceFormState & {
  created_by: string;
};

const MAINTENANCE_WINDOWS_ENDPOINT = '/api/alerts/maintenance-windows';

export const listAlertMaintenanceWindows = (params: URLSearchParams) =>
  apiRequest<AlertMaintenanceListResponse>(`${MAINTENANCE_WINDOWS_ENDPOINT}?${params.toString()}`);

export const createAlertMaintenanceWindow = (payload: CreateAlertMaintenanceWindowPayload) =>
  apiRequest<AlertMaintenanceWindow>(MAINTENANCE_WINDOWS_ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const cancelAlertMaintenanceWindow = (windowId: string, actorUsername: string) =>
  apiRequest<{ success: boolean }>(`${MAINTENANCE_WINDOWS_ENDPOINT}/${encodeURIComponent(windowId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ actor_username: actorUsername }),
  });

export const deleteAlertMaintenanceWindow = (windowId: string, actorUsername: string) =>
  apiRequest<{ success: boolean }>(
    `${MAINTENANCE_WINDOWS_ENDPOINT}/${encodeURIComponent(windowId)}?actor_username=${encodeURIComponent(actorUsername)}`,
    { method: 'DELETE' },
  );
