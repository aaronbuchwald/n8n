import { useEffect, useState } from 'react';

import { fetchWorkspace, type WorkspaceInfo } from '../api';

/**
 * Small top-bar badge naming the git branch source edits land on (the graph is
 * a direct editor of the source tree, ADR 0004 D2). Self-contained: fetches
 * `/api/workspace` itself and renders nothing until (unless) it resolves, so
 * the App integration is a single element.
 */
export function BranchBadge() {
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchWorkspace()
      .then((data) => {
        if (!cancelled) setInfo(data);
      })
      .catch(() => {
        // Branch info is contextual, not critical — stay hidden on failure.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!info) return null;
  const label = info.branch ?? (info.detached ? `detached @ ${info.commit ?? '?'}` : null);
  if (!label) return null;

  const editedFiles = info.modules.map((m) => m.path).join(', ');
  return (
    <span
      className="ge-branch"
      data-testid="branch-badge"
      title={editedFiles ? `edits write to ${editedFiles}` : undefined}
    >
      <span className="ge-branch__icon" aria-hidden="true">
        ⎇
      </span>
      {label}
    </span>
  );
}
