// Client for `POST /api/specs/{spec_id}/derive` (ADR 0007 D4) with a
// `(specId, value)` cache. Python is the ONLY parser of the calc — this module
// never inspects the equation text; it just ships it to the server and types
// the reply.
//
// This is TRANSPORT, not state (8-S1 rule 3): the cache below only de-dupes
// POSTs for the calc editor's debounced draft previews (transient, single-
// component). Anything COMMITTED renders from the store — `useDerivedSync`
// lands committed derivations in `state.derived` via `ingestDerived`, and the
// canvas reads `state.derivedByNode`; nothing renders from this map.

import type { EngineErrorItem } from '../../api';
import type { SpecInput } from '../../types';

export type DeriveOutcome =
  | { ok: true; inputs: SpecInput[] }
  | { ok: false; errors: EngineErrorItem[] };

// -- response type guards (no `as` casts; the wire shape is checked) ---------

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isSpecInput(v: unknown): v is SpecInput {
  if (!isRecord(v)) return false;
  return (
    typeof v.name === 'string' &&
    typeof v.type === 'string' &&
    typeof v.kind === 'string' &&
    typeof v.required === 'boolean'
  );
}

function isErrorItem(v: unknown): v is EngineErrorItem {
  return isRecord(v) && typeof v.code === 'string' && typeof v.message === 'string';
}

function parseOutcome(status: number, body: unknown): DeriveOutcome {
  if (status === 200 && isRecord(body) && Array.isArray(body.inputs)) {
    const inputs = body.inputs.filter(isSpecInput);
    if (inputs.length === body.inputs.length) return { ok: true, inputs };
  }
  if (status === 422 && isRecord(body) && Array.isArray(body.errors)) {
    const errors = body.errors.filter(isErrorItem);
    if (errors.length > 0) return { ok: false, errors };
  }
  const message =
    isRecord(body) && typeof body.message === 'string'
      ? body.message
      : `derive endpoint responded ${status}`;
  return { ok: false, errors: [{ code: 'Error', message }] };
}

// -- the cache ---------------------------------------------------------------

// Settled outcomes, readable synchronously (the canvas hook renders from this).
const resolved = new Map<string, DeriveOutcome>();
// De-duplicates concurrent requests for the same (specId, value).
const inFlight = new Map<string, Promise<DeriveOutcome>>();

// Editing generates one entry per debounce tick; bound so a long session can't
// grow the maps without limit. Eviction is whole-map — entries are tiny and a
// refetch is one cheap POST.
const MAX_CACHE = 512;

const keyOf = (specId: string, value: string): string => `${specId}\u0000${value}`;

/** The settled outcome for `(specId, value)`, if derivation already ran. */
export function cachedDerive(specId: string, value: string): DeriveOutcome | undefined {
  return resolved.get(keyOf(specId, value));
}

/**
 * Derive the input sockets `value` implies for dynamic spec `specId`.
 * Never rejects: transport failures come back as an `ok: false` outcome so
 * callers render one shape. Results are cached by `(specId, value)`.
 */
export function deriveInputs(specId: string, value: string): Promise<DeriveOutcome> {
  const key = keyOf(specId, value);
  const settled = resolved.get(key);
  if (settled) return Promise.resolve(settled);
  const pending = inFlight.get(key);
  if (pending) return pending;

  const request = (async (): Promise<DeriveOutcome> => {
    try {
      const res = await fetch(`/api/specs/${encodeURIComponent(specId)}/derive`, {
        method: 'POST',
        headers: { accept: 'application/json', 'content-type': 'application/json' },
        body: JSON.stringify({ value }),
      });
      const body: unknown = await res.json().catch(() => ({}));
      const outcome = parseOutcome(res.status, body);
      // Cache only real server verdicts; a transport blip below must not stick.
      if (resolved.size >= MAX_CACHE) resolved.clear();
      resolved.set(key, outcome);
      return outcome;
    } catch {
      return {
        ok: false,
        errors: [{ code: 'Error', message: 'Could not reach the server to derive sockets.' }],
      };
    } finally {
      inFlight.delete(key);
    }
  })();

  inFlight.set(key, request);
  return request;
}
