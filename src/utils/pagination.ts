import { authHeaders } from '../api/http';

export async function fetchAllPaginatedItems<T>(endpoint: string, params: URLSearchParams, pageSize = 100): Promise<T[]> {
  const allItems: T[] = [];
  let page = 1;
  let total = Number.POSITIVE_INFINITY;

  while (true) {
    const requestParams = new URLSearchParams(params);
    requestParams.set('page', String(page));
    requestParams.set('page_size', String(pageSize));

    const resp = await fetch(`${endpoint}?${requestParams.toString()}`, { headers: authHeaders() });
    if (!resp.ok) {
      throw new Error(`Failed to fetch paginated items from ${endpoint}`);
    }

    const data = await resp.json();
    const items = Array.isArray(data.items) ? data.items : [];
    allItems.push(...items);

    if (typeof data.total === 'number') {
      total = data.total;
    }

    if (items.length < pageSize || allItems.length >= total) {
      break;
    }

    page += 1;
  }

  return allItems;
}
