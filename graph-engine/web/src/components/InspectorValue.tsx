import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

// The collapsed height cap for a value block, in px. Kept in sync with the
// `--ge-inspector-value-collapsed` CSS var on `.ge-inspector__value-scroll`; the
// JS reads it to decide whether the "Show more" toggle is warranted (content
// taller than the cap), the CSS enforces it.
const COLLAPSED_MAX_PX = 148;
const COPIED_RESET_MS = 1500;

/**
 * A small copy-to-clipboard control that reveals on hover/focus at the corner of
 * a value block. Copies the FULL raw text via the async clipboard API and shows
 * a brief "Copied ✓" confirmation that reverts on its own.
 */
/**
 * Copy-to-clipboard, revealed on hover/focus of its container. Shared by the
 * read-only value blocks here AND by the editors (a value you can edit still
 * needs to be copyable — without minting a second, read-only box for it).
 */
export function CopyButton({ value, className }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), COPIED_RESET_MS);
    } catch {
      // Clipboard unavailable (denied permission / insecure context) — leave the
      // button in its resting state rather than lie about a copy that failed.
    }
  }, [value]);

  return (
    <button
      type="button"
      className={className ?? 'ge-inspector__copy'}
      data-testid="inspector-value-copy"
      data-copied={copied ? 'true' : 'false'}
      aria-label={copied ? 'Value copied' : 'Copy value'}
      onClick={onCopy}
    >
      {copied ? 'Copied ✓' : 'Copy'}
    </button>
  );
}

interface InspectorValueBlockProps {
  /** The COMPLETE value text — shown in full, scrollable, and copied verbatim. */
  text: string;
  /**
   * `value` wraps long text (dicts, latex); `code` keeps source formatting with
   * horizontal scroll for long lines. Both are monospace and scrollable.
   */
  variant?: 'value' | 'code';
  /** data-testid stamped on the scrollable text element. */
  testid?: string;
}

/**
 * A single inspector value surface that shows the FULL value (never truncated):
 * a scrollable region capped at a sensible height, a hover/focus copy button,
 * and — only when the value overflows the cap — a "Show more/less" toggle that
 * lets the field grow. Small values stay compact (the cap is a max, not a floor).
 */
export function InspectorValueBlock({ text, variant = 'value', testid }: InspectorValueBlockProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);

  // `scrollHeight` reflects the full content height regardless of the current
  // max-height, so comparing it to the collapsed cap tells us whether expanding
  // would reveal more — correct whether the block is collapsed or expanded.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setOverflowing(el.scrollHeight > COLLAPSED_MAX_PX + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text]);

  return (
    <div className="ge-inspector__value-wrap">
      <div
        ref={scrollRef}
        className={`ge-inspector__value-scroll ge-inspector__value-scroll--${variant}${
          expanded ? ' is-expanded' : ''
        }`}
        data-testid={testid}
        data-expanded={expanded ? 'true' : 'false'}
      >
        {text}
      </div>
      <CopyButton value={text} />
      {overflowing && (
        <button
          type="button"
          className="ge-inspector__value-toggle"
          data-testid="inspector-value-toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((prev) => !prev)}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
}
