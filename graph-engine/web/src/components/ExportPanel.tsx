interface ExportPanelProps {
  python: string;
  onClose: () => void;
}

/**
 * A read-only view of the graph exported to flat Python, sat beside the canvas
 * so the graph ↔ code correspondence is visible at a glance. Whitespace is
 * preserved; the panel is non-editable by design (export is one-way here).
 */
export function ExportPanel({ python, onClose }: ExportPanelProps) {
  return (
    <aside className="ge-export" data-testid="export-panel" aria-label="Exported Python">
      <div className="ge-export__head">
        <span className="ge-export__title">graph → python</span>
        <span className="ge-export__sub">to_python(graph) · read-only</span>
        <button type="button" className="ge-btn ge-btn--ghost" onClick={onClose}>
          Close
        </button>
      </div>
      <pre className="ge-export__code" data-testid="export-code">
        <code>{python}</code>
      </pre>
    </aside>
  );
}
