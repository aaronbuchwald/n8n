import { SourceEditor } from './SourceEditor';

interface NewNodePanelProps {
  onClose: () => void;
}

/**
 * Docked entry point for authoring a brand-new `@node` (ADR 0011 D7, stream
 * 11-W6), sat beside the canvas like the export panel. The ADR's long-term
 * home for this trigger is the palette header (11-W5, "New node"); until that
 * lands, the topbar's "+ New node" button opens this panel directly so the
 * create flow is reachable and testable end-to-end. Swapping the trigger for
 * the palette's later is a one-line change — this panel only wraps
 * `SourceEditor`'s `create` mode.
 */
export function NewNodePanel({ onClose }: NewNodePanelProps) {
  return (
    <aside className="ge-newnode" data-testid="new-node-panel" aria-label="Author a new node">
      <SourceEditor mode="create" onClose={onClose} />
    </aside>
  );
}
