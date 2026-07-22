// Render a run output value readably. Values arrive JSON-safe; non-JSON returns
// degrade to a tagged {"$repr","$type"} preview (server/serialize.py). Surface
// those as their repr text so the UI shows something meaningful, not "[object]".

interface ReprPreview {
  $repr: string;
  $type: string;
}

function isReprPreview(v: unknown): v is ReprPreview {
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof (v as Record<string, unknown>).$repr === 'string' &&
    typeof (v as Record<string, unknown>).$type === 'string'
  );
}

/** A compact one-line-ish string for a socket value. */
export function previewValue(v: unknown): string {
  if (isReprPreview(v)) return v.$repr;
  if (typeof v === 'string') return v;
  if (v === null || typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** The Python-ish type name for a value, for a small dimmed label. */
export function previewType(v: unknown): string {
  if (isReprPreview(v)) return v.$type;
  if (v === null) return 'None';
  if (Array.isArray(v)) return 'list';
  switch (typeof v) {
    case 'string':
      return 'str';
    case 'boolean':
      return 'bool';
    case 'number':
      return Number.isInteger(v) ? 'int' : 'float';
    case 'object':
      return 'dict';
    default:
      return typeof v;
  }
}

function formatSize(chars: number): string {
  return chars < 1024 ? `${chars} B` : `${(chars / 1024).toFixed(1)} KB`;
}

const looksLikeMarkup = (s: string) => /^\s*<[a-z!/]/i.test(s);

/**
 * An at-a-glance summary for the small result chip on a node card. Structured
 * values (HTML blobs, lists, dicts) summarize by shape instead of dumping raw
 * JSON/markup into the footer; the full value lives in the inspector.
 */
export function previewChip(v: unknown): string {
  if (isReprPreview(v)) return v.$repr;
  if (typeof v === 'string') {
    if (looksLikeMarkup(v)) return `html · ${formatSize(v.length)}`;
    return v;
  }
  if (v === null || typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return `list · ${v.length} item${v.length === 1 ? '' : 's'}`;
  if (typeof v === 'object') {
    const n = Object.keys(v).length;
    return `dict · ${n} key${n === 1 ? '' : 's'}`;
  }
  return previewValue(v);
}
