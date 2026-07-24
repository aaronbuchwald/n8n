// ADR 0014 D1 — the collapsed-region rail. A collapsed region renders size 0 in
// its split group and this thin strip takes its place at the edge, OUTSIDE the
// group (so no viewport-dependent percent `collapsedSize` is ever needed). The
// whole rail is the re-expand affordance: a focusable button, Enter/Space- and
// click-operable, that restores the region to its pre-collapse size.

import type { RegionKey } from '../../store/layout';

interface RailProps {
  region: RegionKey;
  /** Rotated (left/right) or inline (bottom) label. */
  label: string;
  /** A tiny glyph shown before the label — icon-first per the ADR. */
  icon: string;
  /** Optional trailing count (e.g. the run's node count on the bottom rail). */
  badge?: string | number;
  onExpand: () => void;
}

const EDGE_LABEL: Record<RegionKey, string> = {
  right: 'Expand dock',
  bottom: 'Expand run results',
};

export function Rail({ region, label, icon, badge, onExpand }: RailProps) {
  return (
    <button
      type="button"
      className={`ge-rail ge-rail--${region}`}
      data-testid={`rail-${region}`}
      aria-label={EDGE_LABEL[region]}
      title={EDGE_LABEL[region]}
      onClick={onExpand}
    >
      <span className="ge-rail__icon" aria-hidden="true">
        {icon}
      </span>
      <span className="ge-rail__label">{label}</span>
      {badge !== undefined && <span className="ge-rail__badge">{badge}</span>}
    </button>
  );
}
