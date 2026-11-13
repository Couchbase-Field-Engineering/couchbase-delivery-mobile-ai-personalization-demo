import type { Catalog, ChatDoc, ContextDoc, OrderRequest, RecsDoc, Customer, Hub, SyncState } from '../types';

/**
 * The app's local database. Two implementations with the same contract:
 *
 * - `couchbase-lite` (cblDb.native.ts): the real thing. An on-device Couchbase
 *   Lite database (scope `dispatch`, same collections as the server) kept in
 *   sync by a continuous push/pull replicator against Sync Gateway. Everything
 *   renders from here, so the app works with no connectivity at all.
 * - `preview` (previewDb.ts): a browser/Expo Go stand-in for demos without a
 *   device build - an in-memory store that polls the backend's REST
 *   `/api/sync/pull` and pushes orders with `/api/sync/push`. Same document
 *   ids and shapes.
 */
export const SCOPE = 'dispatch';
export const COLLECTIONS = ['customers', 'hubs', 'recommendations', 'orders', 'assistant', 'context_cache', 'catalog'] as const;
export type CollectionName = (typeof COLLECTIONS)[number];

export const INTENTS = ['reorder', 'pricing', 'availability', 'delivery', 'returns', 'rewards', 'history', 'subscription', 'preferences', 'general'];

export type Snapshot = {
  /** The signed-in customer's profile (the Databricks row plus live state). */
  customer: Customer | null;
  /** Their home hub: hours, services, Express time and the pickup bay of every product. */
  hub: Hub | null;
  /** Smart cart, picks and price matches from the next-basket model. */
  recs: RecsDoc | null;
  orders: OrderRequest[];
  chat: ChatDoc | null;
  catalog: Catalog | null;
  /** Context cache docs by their id (ctx::<customer>::<intent> / ctx::<customer>::guide_<intent>). */
  contexts: Record<string, ContextDoc>;
};

export const EMPTY: Snapshot = { customer: null, hub: null, recs: null, orders: [], chat: null, catalog: null, contexts: {} };

export type SyncSession = {
  token: string;
  customerId: string;
  sg: { session_id: string; cookie_name: string; url: string | null; db: string } | null;
};

export interface LocalDb {
  readonly engine: SyncState['engine'];
  open(customerId: string): Promise<void>;
  read(): Promise<Snapshot>;
  saveRequest(req: OrderRequest): Promise<void>;
  startSync(session: SyncSession): Promise<void>;
  setPaused(paused: boolean): Promise<void>;
  onChange(cb: () => void): () => void;
  onSyncState(cb: (s: SyncState) => void): () => void;
  location(): string | null;
  close(): Promise<void>;
}

export const ids = {
  customer: (s: string) => `customer::${s}`,
  hub: (s: string) => `hub::${s}`,
  recs: (s: string) => `recs::${s}`,
  chat: (s: string) => `chat::${s}`,
  ctx: (customerId: string, k: string) => `ctx::${customerId}::${k}`,
  catalog: 'catalog::v1',
};

export type Doc = Record<string, unknown> & { _id?: string };

/** Build a Snapshot from a by-id getter and a per-collection lister. */
export async function buildSnapshot(
  customerId: string,
  get: (col: CollectionName, id: string) => Promise<Doc | null>,
  list: (col: CollectionName) => Promise<Doc[]>,
  orders: OrderRequest[],
): Promise<Snapshot> {
  const contexts: Record<string, ContextDoc> = {};
  for (const d of await list('context_cache')) {
    const c = d as unknown as ContextDoc & { _id?: string };
    const key = c._id ?? ids.ctx(customerId, c.personal ? c.intent : `guide_${c.intent}`);
    contexts[key] = c;
  }
  const customer = (await get('customers', ids.customer(customerId))) as unknown as Customer | null;
  // Only the home hub's channel replicates, so the collection holds one document.
  const hub = customer?.home_hub
    ? ((await get('hubs', ids.hub(customer.home_hub.hub_id))) as unknown as Hub | null)
    : (((await list('hubs'))[0] ?? null) as unknown as Hub | null);
  return {
    customer,
    hub,
    recs: (await get('recommendations', ids.recs(customerId))) as unknown as RecsDoc | null,
    chat: (await get('assistant', ids.chat(customerId))) as unknown as ChatDoc | null,
    catalog: (await get('catalog', ids.catalog)) as unknown as Catalog | null,
    contexts,
    orders: [...orders].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
  };
}

type Listener<T> = (v: T) => void;
export class Emitter<T> {
  private ls = new Set<Listener<T>>();
  on(l: Listener<T>) {
    this.ls.add(l);
    return () => {
      this.ls.delete(l);
    };
  }
  emit(v: T) {
    this.ls.forEach((l) => {
      try {
        l(v);
      } catch {
        /* listener errors never break sync */
      }
    });
  }
}
