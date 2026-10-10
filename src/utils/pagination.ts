import { authHeaders } from '../api/http';

export async function fetchAllPaginatedItems<T>(
  endpoint: string,
  params: URLSearchParams,
  pageSize = 100,
  options: { itemsKey?: string } = {},
): Promise<T[]> {
  const allItems: T[] = [];
  let page = 1;
  let total = Number.POSITIVE_INFINITY;

  while (true) {
    const requestParams = new URLSearchParams(params);
    requestParams.set('page', String(page));
    requestParams.set('page_size', String(pageSize));

    const resp = await fetch(`${endpoint}?${requestParams.toString()}`, { headers: authHeaders() });
    if (!resp.ok) {
      throw new Error(`Failed to fetch paginated items from ${endpoint} (HTTP ${resp.status})`);
    }

    const payload = await resp.json();
    // List APIs use three common shapes: `{items,total}`,
    // `{data:{items,total}}`, and `{success:true,data:[...],total}`.
    // Normalize them here so callers can reuse the same all-pages loader
    // without dropping the server-reported total.
    const data = payload?.data && typeof payload.data === 'object' && !Array.isArray(payload.data)
      ? payload.data
      : payload;
    const itemsKey = options.itemsKey || 'items';
    const items = Array.isArray(payload?.data)
      ? payload.data
      : Array.isArray(data?.[itemsKey])
        ? data[itemsKey]
        : [];
    allItems.push(...items);

    const reportedTotal = typeof data?.total === 'number' ? data.total : payload?.total;
    if (typeof reportedTotal === 'number' && Number.isFinite(reportedTotal)) {
      total = Math.max(0, reportedTotal);
    }

    if (items.length === 0) {
      if (Number.isFinite(total) && allItems.length < total) {
        throw new Error(`Paginated export ended at ${allItems.length} of ${total} rows from ${endpoint}`);
      }
      break;
    }

    // Prefer the server's total over a short page. Some adapters can return
    // partial pages while still having additional matches at later offsets.
    if (allItems.length >= total || (total === Number.POSITIVE_INFINITY && items.length < pageSize)) break;

    page += 1;
  }

  return allItems;
}
