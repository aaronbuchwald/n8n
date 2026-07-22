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
  return typeof v;
}
