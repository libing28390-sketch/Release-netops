export type LocatorRunStage = 'queued' | 'running' | 'legacy';

interface LocatorRunEnvelope<T> {
  id?: string;
  status?: string;
  result?: T;
  error_message?: string;
  error_code?: string;
}

interface LocatorErrorEnvelope {
  detail?: unknown;
}

interface LocateByRunOptions<T> {
  ip: string;
  token: string;
  forceRefresh?: boolean;
  legacyResultPath?: string;
  onStage?: (stage: LocatorRunStage) => void;
  pollIntervalMs?: number;
  timeoutMs?: number;
}

function detailMessage(payload: LocatorErrorEnvelope, fallback: string): string {
  if (typeof payload.detail === 'string') return payload.detail;
  if (payload.detail && typeof payload.detail === 'object' && 'message' in payload.detail) {
    const message = (payload.detail as { message?: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return fallback;
}

async function readJson<T>(response: Response): Promise<T> {
  return response.json() as Promise<T>;
}

async function wait(milliseconds: number): Promise<void> {
  await new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}

function shouldUseLegacy(response: Response, detail: string): boolean {
  return response.status === 404 || (
    response.status === 503 && detail.includes('IP 定位 V2 未启用')
  );
}

/**
 * Start the durable V2 locator run and poll until a terminal result. Older
 * deployments and explicitly disabled V2 installations retain the legacy
 * endpoint. Other V2 failures are surfaced rather than bypassing the queue.
 */
export async function locateIpWithRun<T>({
  ip,
  token,
  forceRefresh = false,
  legacyResultPath = '/api/ip-locator/locate',
  onStage,
  pollIntervalMs = 800,
  timeoutMs = 190_000,
}: LocateByRunOptions<T>): Promise<T> {
  const headers = {
    'Content-Type': 'application/json',
    Authorization: 'Bearer ' + token,
  };
  const body = JSON.stringify({ ip, force_refresh: forceRefresh });
  const startedAt = Date.now();
  const createResponse = await fetch('/api/ip-locator/runs', {
    method: 'POST',
    headers,
    body,
  });

  if (!createResponse.ok) {
    const payload = await createResponse.json().catch(() => ({})) as LocatorErrorEnvelope;
    const detail = detailMessage(payload, 'HTTP ' + createResponse.status);
    if (shouldUseLegacy(createResponse, detail)) {
      onStage?.('legacy');
      const legacyResponse = await fetch(legacyResultPath, { method: 'POST', headers, body });
      if (!legacyResponse.ok) {
        const legacyPayload = await legacyResponse.json().catch(() => ({})) as LocatorErrorEnvelope;
        throw new Error(detailMessage(legacyPayload, 'HTTP ' + legacyResponse.status));
      }
      return readJson<T>(legacyResponse);
    }
    throw new Error(detail);
  }

  const initial = await readJson<LocatorRunEnvelope<T>>(createResponse);
  if (!initial.id) throw new Error('定位任务响应缺少任务 ID');
  let run = initial;
  while (run.status === 'queued' || run.status === 'running') {
    onStage?.(run.status);
    if (Date.now() - startedAt >= timeoutMs) {
      await fetch('/api/ip-locator/runs/' + encodeURIComponent(initial.id) + '/cancel', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + token },
      }).catch(() => undefined);
      throw new Error('定位任务等待超时；任务已请求取消');
    }
    await wait(pollIntervalMs);
    const response = await fetch('/api/ip-locator/runs/' + encodeURIComponent(initial.id), {
      headers: { Authorization: 'Bearer ' + token },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({})) as LocatorErrorEnvelope;
      throw new Error(detailMessage(payload, 'HTTP ' + response.status));
    }
    run = await readJson<LocatorRunEnvelope<T>>(response);
  }

  if (run.result) return run.result;
  if (run.status === 'cancelled') throw new Error('定位任务已取消');
  throw new Error(run.error_message || run.error_code || '定位任务结束：' + (run.status || '未知状态'));
}
