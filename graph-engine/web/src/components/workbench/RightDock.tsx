// ADR 0014 D3 — the right-dock tab stack.
//
// The dock is a VS Code-style tab strip over a single body. W1 mounts the
// relocated Inspector as the first (and today only) tab; the `DockTab[]`
// contract is the registration seam W3 extends to add the Export and New-node
// tabs — it pushes more entries onto the array and supplies each tab's content
// component, without touching this shell. Content components stay entirely
// layout-ignorant (D6): they render wherever the dock mounts them.

import type { ReactNode } from 'react';
import type { DockTabKind } from '../../store/layout';

/**
 * One registered right-dock tab. The registration seam (D3/D6): App composes the
 * present tabs into an array; W3 adds Export/New-node entries here. `kind` is the
 * width-memory bucket (inspector ≈340px vs code ≈34rem), not the tab identity.
 */
export interface DockTab {
  /** Stable id; also the persisted `activeRightTab` value. */
  id: string;
  /** Width-memory bucket (ADR 0014 D3): inspector vs the code editors. */
  kind: DockTabKind;
  /** Tab-strip label. */
  label: string;
  /** The panel body rendered when this tab is active. */
  content: ReactNode;
  /** Closing the tab from the strip (× control); optional. */
  onClose?: () => void;
}

interface RightDockProps {
  tabs: DockTab[];
  /** The active tab id (persisted); resolved against `tabs` with a fallback. */
  activeId: string | null;
  onActivate: (id: string) => void;
  /** Collapse the whole dock to its rail. */
  onCollapse: () => void;
}

/** Resolve the tab to show: the persisted active one, else the last present. */
export function resolveActiveTab(tabs: DockTab[], activeId: string | null): DockTab | null {
  if (tabs.length === 0) return null;
  return tabs.find((t) => t.id === activeId) ?? tabs[tabs.length - 1];
}

export function RightDock({ tabs, activeId, onActivate, onCollapse }: RightDockProps) {
  const active = resolveActiveTab(tabs, activeId);

  return (
    <section className="ge-dock" data-testid="right-dock" aria-label="Right dock">
      <div className="ge-dock__strip" role="tablist" aria-label="Dock tabs">
        {tabs.map((tab) => {
          const selected = tab.id === active?.id;
          return (
            <div
              key={tab.id}
              className={`ge-dock__tab${selected ? ' ge-dock__tab--active' : ''}`}
              data-testid={`dock-tab-${tab.id}`}
            >
              <button
                type="button"
                role="tab"
                aria-selected={selected}
                className="ge-dock__tab-btn"
                onClick={() => onActivate(tab.id)}
              >
                {tab.label}
              </button>
              {tab.onClose && (
                <button
                  type="button"
                  className="ge-dock__tab-close"
                  aria-label={`Close ${tab.label}`}
                  data-testid={`dock-tab-close-${tab.id}`}
                  onClick={tab.onClose}
                >
                  &times;
                </button>
              )}
            </div>
          );
        })}
        <button
          type="button"
          className="ge-dock__collapse"
          data-testid="collapse-right"
          aria-label="Collapse dock"
          title="Collapse dock"
          onClick={onCollapse}
        >
          &rsaquo;
        </button>
      </div>

      <div className="ge-dock__body" data-testid="dock-body">
        {active ? (
          active.content
        ) : (
          <div className="ge-dock__placeholder" data-testid="dock-placeholder">
            Select a node to inspect it.
          </div>
        )}
      </div>
    </section>
  );
}
