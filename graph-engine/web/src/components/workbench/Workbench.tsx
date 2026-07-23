// ADR 0014 W1 — the workbench shell.
//
// The whole region layout lives here (D6: all region knowledge in one place —
// `components/workbench/*`). It composes react-resizable-panels into the D1
// region model: one horizontal group `left │ center │ right`, the center itself
// a vertical group `canvas ╱ bottom`, three sashes, and rails rendered OUTSIDE
// the groups for collapsed regions. Content components (Palette, the dock tabs,
// Run results, and the canvas) are passed in as slots and stay layout-ignorant.
//
// The seams the follow-up streams build on:
//   * `canvas` — the canvas host slot. W2 owns GraphView's ResizeObserver; the
//     shell only gives it a resizable box and never calls into it (resize
//     reaches the canvas purely as a container size change).
//   * `dockTabs` + RightDock — the right-dock host and its tab-registration API
//     (DockTab[]). W1 mounts the relocated Inspector as the first tab; W3 pushes
//     Export and New-node entries onto the same array.
//   * `store/layout.ts` — the UI-local layout store W4 extends for persistence
//     tests. Sash sizes ride the library's `autoSaveId`; rail/tab/width state is
//     ours.

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { Panel, PanelGroup, PanelResizeHandle, type ImperativePanelHandle } from 'react-resizable-panels';

import { RightDock, resolveActiveTab, type DockTab } from './RightDock';
import { Rail } from './Rail';
import {
  getLayout,
  resetLayout,
  setActiveRightTab,
  setRegionCollapsed,
  setRightWidth,
  type DockTabKind,
} from '../../store/layout';
import { useLayoutSelector } from '../../store/useLayout';
import type { ReactNode } from 'react';

// Defaults in the library's native percent unit, translated from today's CSS at
// a 1440px reference viewport (ADR 0014 D1). Constraints are proportional by
// nature, so percent costs us nothing here.
const LEFT = { default: 15, min: 10, max: 25 };
const RIGHT = { default: 24, min: 15, max: 50 };
const BOTTOM = { default: 30, min: 12, max: 60 };
const CENTER_MIN = 30;

/** The autoSaveId groups the library persists sash sizes under (D5). */
const MAIN_GROUP_ID = 'ge-workbench-main';
const CENTER_GROUP_ID = 'ge-workbench-center';

export interface WorkbenchHandle {
  /** Reset every region to defaults without a reload (D5 reset affordance). */
  reset: () => void;
}

interface WorkbenchProps {
  /** Left region content (the node palette). */
  palette: ReactNode;
  /** The canvas host slot (W2 owns its resize integration). */
  canvas: ReactNode;
  /** Bottom region content (run results), or null when no run exists. */
  bottom: ReactNode | null;
  /** A count for the collapsed bottom rail (e.g. executed node count). */
  bottomBadge?: string | number;
  /** The present right-dock tabs (D3 registration seam). */
  dockTabs: DockTab[];
}

export const Workbench = forwardRef<WorkbenchHandle, WorkbenchProps>(function Workbench(
  { palette, canvas, bottom, bottomBadge, dockTabs },
  ref,
) {
  const collapsed = useLayoutSelector((s) => s.collapsed);
  const activeRightTab = useLayoutSelector((s) => s.activeRightTab);

  const leftRef = useRef<ImperativePanelHandle>(null);
  const rightRef = useRef<ImperativePanelHandle>(null);
  const bottomRef = useRef<ImperativePanelHandle>(null);

  const hasBottom = bottom !== null;
  const activeTab = resolveActiveTab(dockTabs, activeRightTab);
  const activeKind: DockTabKind = activeTab?.kind ?? 'inspector';
  const activeKindRef = useRef(activeKind);
  activeKindRef.current = activeKind;

  // Restore the persisted collapsed state authoritatively on mount (ADR 0014
  // D5: our store drives the rails). The library's own autoSave is debounced
  // (~100ms), so a quick reload after a collapse can lose it — and this shell
  // remounts wholesale on every entry switch (ADR 0009 D6). Our store is written
  // synchronously, so we snapshot it at first render (before the library's
  // child callbacks can toggle it) and force each panel to match. Sash SIZES
  // still ride the library's autoSaveId; only the collapse/rail state is ours.
  const initialCollapsed = useRef(getLayout().collapsed);
  const didReconcile = useRef(false);
  useEffect(() => {
    if (didReconcile.current) return;
    didReconcile.current = true;
    const want = initialCollapsed.current;
    const sync = (handle: ImperativePanelHandle | null, collapse: boolean) => {
      if (!handle) return;
      if (collapse && !handle.isCollapsed()) handle.collapse();
      else if (!collapse && handle.isCollapsed()) handle.expand();
    };
    sync(leftRef.current, want.left);
    sync(rightRef.current, want.right);
    sync(bottomRef.current, want.bottom);
    // Force the store back to the snapshot in case a library mount callback
    // toggled it before this effect ran.
    setRegionCollapsed('left', want.left);
    setRegionCollapsed('right', want.right);
    setRegionCollapsed('bottom', want.bottom);
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      reset() {
        resetLayout();
        leftRef.current?.expand();
        rightRef.current?.expand();
        bottomRef.current?.expand();
        leftRef.current?.resize(LEFT.default);
        rightRef.current?.resize(RIGHT.default);
        bottomRef.current?.resize(BOTTOM.default);
      },
    }),
    [],
  );

  // Auto-expand the dock onto a newly-summoned surface (node selection, and
  // later Export/New-node): a surface the user asked for must never open behind
  // a rail (D1). A tab id appearing that wasn't there is the trigger.
  const prevTabIds = useRef<Set<string>>(new Set(dockTabs.map((t) => t.id)));
  useEffect(() => {
    const ids = new Set(dockTabs.map((t) => t.id));
    let appeared: string | null = null;
    for (const id of ids) if (!prevTabIds.current.has(id)) appeared = id;
    prevTabIds.current = ids;
    if (appeared !== null) {
      setActiveRightTab(appeared);
      if (getLayout().collapsed.right) rightRef.current?.expand();
    }
  }, [dockTabs]);

  // Auto-expand the bottom region when a run lands into a collapsed strip (D1).
  const prevHasBottom = useRef(hasBottom);
  useEffect(() => {
    if (hasBottom && !prevHasBottom.current && getLayout().collapsed.bottom) {
      bottomRef.current?.expand();
    }
    prevHasBottom.current = hasBottom;
  }, [hasBottom]);

  // Per-tab-kind width memory (D3): switching to a different tab kind animates
  // the dock to that kind's remembered width. One sash, widths that fit the
  // content. (With a single tab kind present this never fires.)
  const prevKind = useRef(activeKind);
  useEffect(() => {
    if (prevKind.current !== activeKind && !getLayout().collapsed.right) {
      rightRef.current?.resize(getLayout().rightWidthByTab[activeKind]);
    }
    prevKind.current = activeKind;
  }, [activeKind]);

  return (
    <div className="ge-workbench" data-testid="workbench">
      {collapsed.left && (
        <Rail region="left" icon="☰" label="Nodes" onExpand={() => leftRef.current?.expand()} />
      )}

      <PanelGroup
        className="ge-wb-main"
        direction="horizontal"
        autoSaveId={MAIN_GROUP_ID}
        id={MAIN_GROUP_ID}
      >
        <Panel
          id="left"
          order={1}
          ref={leftRef}
          className="ge-wb-panel ge-wb-panel--left"
          collapsible
          collapsedSize={0}
          minSize={LEFT.min}
          maxSize={LEFT.max}
          defaultSize={LEFT.default}
          onCollapse={() => setRegionCollapsed('left', true)}
          onExpand={() => setRegionCollapsed('left', false)}
        >
          <div className="ge-region ge-region--left">
            {palette}
            <button
              type="button"
              className="ge-region__collapse ge-region__collapse--left"
              data-testid="collapse-left"
              aria-label="Collapse palette"
              title="Collapse palette"
              onClick={() => leftRef.current?.collapse()}
            >
              &lsaquo;
            </button>
          </div>
        </Panel>

        <PanelResizeHandle className="ge-wb-sash ge-wb-sash--v" data-testid="sash-left" />

        <Panel id="center" order={2} minSize={CENTER_MIN} className="ge-wb-panel ge-wb-panel--center">
          <div className="ge-wb-center">
            <PanelGroup
              className="ge-wb-center-group"
              direction="vertical"
              autoSaveId={CENTER_GROUP_ID}
              id={CENTER_GROUP_ID}
            >
              <Panel id="canvas" order={1} minSize={CENTER_MIN} className="ge-wb-panel--canvas">
                {canvas}
              </Panel>
              {hasBottom && (
                <PanelResizeHandle className="ge-wb-sash ge-wb-sash--h" data-testid="sash-bottom" />
              )}
              {hasBottom && (
                <Panel
                  id="bottom"
                  order={2}
                  ref={bottomRef}
                  className="ge-wb-panel ge-wb-panel--bottom"
                  collapsible
                  collapsedSize={0}
                  minSize={BOTTOM.min}
                  maxSize={BOTTOM.max}
                  defaultSize={BOTTOM.default}
                  onCollapse={() => setRegionCollapsed('bottom', true)}
                  onExpand={() => setRegionCollapsed('bottom', false)}
                >
                  <div className="ge-region ge-region--bottom">
                    {bottom}
                    <button
                      type="button"
                      className="ge-region__collapse ge-region__collapse--bottom"
                      data-testid="collapse-bottom"
                      aria-label="Collapse run results"
                      title="Collapse run results"
                      onClick={() => bottomRef.current?.collapse()}
                    >
                      &#8964;
                    </button>
                  </div>
                </Panel>
              )}
            </PanelGroup>
            {hasBottom && collapsed.bottom && (
              <Rail
                region="bottom"
                icon="▾"
                label="Run results"
                badge={bottomBadge}
                onExpand={() => bottomRef.current?.expand()}
              />
            )}
          </div>
        </Panel>

        <PanelResizeHandle className="ge-wb-sash ge-wb-sash--v" data-testid="sash-right" />

        <Panel
          id="right"
          order={3}
          ref={rightRef}
          className="ge-wb-panel ge-wb-panel--right"
          collapsible
          collapsedSize={0}
          minSize={RIGHT.min}
          maxSize={RIGHT.max}
          defaultSize={RIGHT.default}
          onCollapse={() => setRegionCollapsed('right', true)}
          onExpand={() => setRegionCollapsed('right', false)}
          onResize={(size) => {
            // Remember the dock width for the ACTIVE tab kind (D3). Skip the
            // collapse transition (size → 0) so the memory keeps a real width.
            if (size > 1) setRightWidth(activeKindRef.current, size);
          }}
        >
          <RightDock
            tabs={dockTabs}
            activeId={activeRightTab}
            onActivate={setActiveRightTab}
            onCollapse={() => rightRef.current?.collapse()}
          />
        </Panel>
      </PanelGroup>

      {collapsed.right && (
        <Rail region="right" icon="▤" label="Dock" onExpand={() => rightRef.current?.expand()} />
      )}
    </div>
  );
});
