import type { ApiEnvelope } from "./types.js";
import type { RequestControls } from "./client.js";

export interface PaginatedEnvelope<TData> extends ApiEnvelope<TData> {
  readonly next_cursor?: string | null;
}

export interface CursorPageRequest extends RequestControls {
  readonly cursor?: string;
  readonly limit?: number;
}

export interface CursorPaginationOptions extends RequestControls {
  readonly startCursor?: string;
  readonly pageLimit?: number;
  readonly maxItems?: number;
}

export type CursorPageLoader<TItem> = (
  input: CursorPageRequest,
) => Promise<PaginatedEnvelope<readonly TItem[]>>;

export async function* iterateCursorItems<TItem>(
  loadPage: CursorPageLoader<TItem>,
  options: CursorPaginationOptions = {},
): AsyncGenerator<TItem, void, void> {
  let cursor = options.startCursor;
  let yielded = 0;

  for (;;) {
    const page = await loadPage(cursorPageRequest(cursor, options.pageLimit, options));
    for (const item of page.data) {
      if (options.maxItems !== undefined && yielded >= options.maxItems) {
        return;
      }
      yield item;
      yielded += 1;
    }

    cursor = page.next_cursor ?? undefined;
    if (!cursor || page.data.length === 0) {
      return;
    }
  }
}

export async function collectCursorItems<TItem>(
  loadPage: CursorPageLoader<TItem>,
  options: CursorPaginationOptions = {},
): Promise<readonly TItem[]> {
  const items: TItem[] = [];
  for await (const item of iterateCursorItems(loadPage, options)) {
    items.push(item);
  }
  return items;
}

export function cursorPageRequest(
  cursor?: string,
  limit?: number,
  controls: RequestControls = {},
): CursorPageRequest {
  return {
    ...(cursor ? { cursor } : {}),
    ...(limit !== undefined ? { limit } : {}),
    ...(controls.headers !== undefined ? { headers: controls.headers } : {}),
    ...(controls.signal !== undefined ? { signal: controls.signal } : {}),
  };
}
