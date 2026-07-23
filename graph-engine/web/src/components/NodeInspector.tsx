import { useEffect, useState } from 'react';

import { fetchNodeStatement, type NodeStatement } from '../api';
import type { InspectedInput, InspectedNode, InputSource, ResolvedValue } from '../inspect';
import { previewType, previewValue } from '../preview';
import { useSyncSelector } from '../store/useSyncSelector';
import { InspectorWidgetSlot } from '../widgets/InspectorWidgetSlot';
import { SourceEditor } from './SourceEditor';

interface NodeInspectorProps {
  node: InspectedNode;
  /** How many canvas nodes share this node's type (>= 1). */
  sharedNodeCount: number;
  /** True while the inspector is expanded into the node's definition editor. */
  editingSource: boolean;
  onEditSource: (open: boolean) => void;
  onClose: () => void;
}

function sourceLabel(source: InputSource): string {
  switch (source.kind) {
    case 'wired':
      return `← ${source.from.node}.${source.from.socket}`;
    case 'literal':
      return 'literal';
    case 'widget':
      return source.widget.kind;
    case 'default':
      return 'default';
    case 'required':
      return 'required';
    case 'unset':
      return 'unset';
  }
}

/** The value to show for an input: the run value, else a static literal/default. */
function inputValue(input: InspectedInput): ResolvedValue | null {
  if (input.run) return input.run;
  if (input.source.kind === 'literal') return { value: input.source.value };
  if (input.source.kind === 'default' && input.source.value !== null) {
    return { value: input.source.value };
  }
  return null;
}

function ValueLine({ resolved }: { resolved: ResolvedValue | null }) {
  if (!resolved) {
    return <div className="ge-inspector__value ge-inspector__value--empty">no value yet</div>;
  }
  const text = previewValue(resolved.value);
  return (
    <div className="ge-inspector__value" title={text}>
      {text}
    </div>
  );
}

// The declared type, and — when a run value is present with a different
// run-time type — both ("object · Add"), so the label's switch from static to
// run-time meaning is visible instead of silent.
function typeLabel(declared: string, resolved: ResolvedValue | null): string {
  if (!resolved) return declared;
  const runtime = previewType(resolved.value);
  return runtime === declared ? declared : `${declared} · ${runtime}`;
}

function InputRow({ input, nodeId }: { input: InspectedInput; nodeId: string }) {
  const resolved = inputValue(input);
  // The inspector is the editing surface now (ADR 0013 D4): an UNWIRED input
  // that declares a widget renders its editor inline, always expanded, under
  // the row head. Wired inputs (their value comes from the graph) and
  // non-widget inputs stay read-only — the ValueLine still shows "what it is
  // set to" / "what flowed in the last run" below the editor.
  const widgetSpec = input.spec?.widget ? input.spec : null;
  const editable = widgetSpec !== null && input.source.kind !== 'wired';
  return (
    <div className="ge-inspector__row" data-testid="inspector-input">
      <div className="ge-inspector__row-head">
        <span className="ge-inspector__socket" title={input.name}>
          {input.name}
        </span>
        <span className="ge-inspector__socket-type">{typeLabel(input.type, resolved)}</span>
        <span
          className={`ge-inspector__tag ge-inspector__tag--${input.source.kind}`}
          title={sourceLabel(input.source)}
        >
          {sourceLabel(input.source)}
        </span>
      </div>
      {editable && widgetSpec && (
        <InspectorWidgetSlot input={widgetSpec} value={input.literal?.value} nodeId={nodeId} />
      )}
      <ValueLine resolved={resolved} />
    </div>
  );
}

/**
 * The read-only call-site row (ADR 0015 D2): THIS node's actual `@main`
 * statement, fetched as the real file bytes (the user's own formatting), with a
 * `path · Lx–Ly` label. The structured input editors above remain the write
 * path; this row re-fetches after every commit (keyed on `rev`), closing the
 * loop "I edited the widget → that's the line it rewrote". Fetched per node so
 * the definition editor's Monaco chunk stays lazy.
 */
function CallSiteRow({ nodeId }: { nodeId: string }) {
  const graphId = useSyncSelector((s) => s.graphId);
  // `rev` bumps on every authoritative graph acceptance — a widget commit lands
  // as a fresh `rev`, so keying the fetch on it refreshes the shown statement.
  const rev = useSyncSelector((s) => s.rev);
  const [statement, setStatement] = useState<NodeStatement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchNodeStatement(nodeId, graphId)
      .then((s) => {
        if (!cancelled) setStatement(s);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setStatement(null);
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [nodeId, graphId, rev]);

  return (
    <section className="ge-inspector__section" data-testid="inspector-callsite">
      <h3 className="ge-inspector__label">Call site</h3>
      {statement ? (
        <>
          <pre className="ge-inspector__callsite-code" data-testid="callsite-source">
            {statement.source.trimEnd()}
          </pre>
          <div
            className="ge-inspector__callsite-loc"
            data-testid="callsite-loc"
            title={`${statement.path} · lines ${statement.startLine}–${statement.endLine}`}
          >
            {statement.path} · L{statement.startLine}–L{statement.endLine}
          </div>
        </>
      ) : error ? (
        <div className="ge-inspector__empty" data-testid="callsite-unavailable">
          no call-site statement
        </div>
      ) : (
        <div className="ge-inspector__empty" data-testid="callsite-loading">
          loading…
        </div>
      )}
    </section>
  );
}

/**
 * The **Instance panel** (ADR 0015 D1): clicking a node opens THIS node's
 * instance — its id/title header, type chip, the ADR 0013 input editors
 * (literals editable, wired inputs read-only, run values), plus the read-only
 * call-site row (D2). The **definition** is a clearly separated drill-in: the
 * "node type" section's "Open node definition" (D3) — warned as shared BEFORE
 * entry — expands the panel into the `@node` function editor (its type, shared
 * by every instance). The two surfaces never mix content.
 */
export function NodeInspector({
  node,
  sharedNodeCount,
  editingSource,
  onEditSource,
  onClose,
}: NodeInspectorProps) {
  const editing = editingSource && !node.missingSpec;
  // The calc / table-recipe editors are physically large (multi-line, grids):
  // give the panel a wider layout when the selected node hosts one, the same
  // expand-in-place pattern the source editor uses (ADR 0013 D4 ergonomics).
  const hasWideEditor = node.inputs.some(
    (input) =>
      input.source.kind !== 'wired' &&
      (input.spec?.widget?.kind === 'calc' || input.spec?.widget?.kind === 'table-recipe'),
  );
  // The definition drill-in is honest BEFORE entry (D3): the shared-scope
  // subtitle rides on the button itself, not only the in-editor banner.
  const definitionSubtitle = node.missingSpec
    ? 'unknown type — no source'
    : sharedNodeCount > 1
      ? `shared — affects all ${sharedNodeCount} instances`
      : `defined in ${node.typeName} — only this node uses it`;
  return (
    <aside
      className={`ge-inspector${editing ? ' ge-inspector--editing' : ''}${
        !editing && hasWideEditor ? ' ge-inspector--wide' : ''
      }`}
      data-testid="node-inspector"
      aria-label={editing ? `Definition of ${node.typeName}` : `Instance ${node.id}`}
    >
      <div className="ge-inspector__head">
        <div className="ge-inspector__heading">
          {/* "id · title" so the inspector shares a visible key with both the
              node cards (title) and the run-results rows (id). This is the
              INSTANCE's identity (D1) — one node id, not the shared type. */}
          <span
            className="ge-inspector__title"
            data-testid="inspector-title"
            title={node.title === node.id ? node.id : `${node.id} · ${node.title}`}
          >
            {node.id}
            {node.title !== node.id && (
              <span className="ge-inspector__title-name"> · {node.title}</span>
            )}
          </span>
          <span className="ge-inspector__typename" title={node.typeName}>
            {node.typeName}
          </span>
        </div>
        {node.isOutput && <span className="ge-node__badge">output</span>}
        <button
          type="button"
          className="ge-inspector__close"
          onClick={onClose}
          aria-label="Close inspector"
        >
          &times;
        </button>
      </div>

      {editing ? (
        <SourceEditor
          specId={node.typeName}
          sharedNodeCount={sharedNodeCount}
          onClose={() => onEditSource(false)}
        />
      ) : (
        <div className="ge-inspector__body">
          {node.missingSpec && (
            <p className="ge-inspector__warn">No spec found for this node type.</p>
          )}
          {!node.hasRun && (
            <p className="ge-inspector__note" data-testid="inspector-no-run">
              Run the graph to see the values that flow through this node.
            </p>
          )}
          {node.hasRun && !node.executed && (
            <p className="ge-inspector__note" data-testid="inspector-not-executed">
              This node did not run — the latest run stopped before reaching it.
            </p>
          )}

          <section className="ge-inspector__section" data-testid="inspector-inputs">
            <h3 className="ge-inspector__label">Inputs</h3>
            {node.inputs.length === 0 && <div className="ge-inspector__empty">no inputs</div>}
            {node.inputs.map((input) => (
              <InputRow input={input} nodeId={node.id} key={input.name} />
            ))}
          </section>

          <section className="ge-inspector__section" data-testid="inspector-outputs">
            <h3 className="ge-inspector__label">Outputs</h3>
            {node.outputs.length === 0 && <div className="ge-inspector__empty">no outputs</div>}
            {node.outputs.map((output) => (
              <div className="ge-inspector__row" data-testid="inspector-output" key={output.name}>
                <div className="ge-inspector__row-head">
                  <span className="ge-inspector__socket" title={output.name}>
                    {output.name}
                  </span>
                  <span className="ge-inspector__socket-type">
                    {typeLabel(output.type, output.run)}
                  </span>
                </div>
                <ValueLine resolved={output.run} />
              </div>
            ))}
          </section>

          {/* D2: the real `@main` call site for THIS node id, read-only. */}
          <CallSiteRow nodeId={node.id} />

          {/* D3/D4: the "node type" section — the docstring reads as the
              TYPE's description (D4), grouped with the door that leads to the
              shared definition (D3). Visually secondary to the instance details
              above; the primary surface is the instance, not the definition. */}
          <section className="ge-inspector__type-section" data-testid="inspector-type">
            <div className="ge-inspector__type-caption">
              <h3 className="ge-inspector__label">Node type</h3>
              <span
                className="ge-inspector__type-name"
                data-testid="inspector-type-name"
                title={node.typeName}
              >
                {node.missingSpec ? 'unknown type' : node.typeName}
              </span>
            </div>
            {node.doc && (
              <p className="ge-inspector__doc" data-testid="inspector-type-doc">
                {node.doc}
              </p>
            )}
            <button
              type="button"
              className="ge-btn ge-inspector__def-btn"
              data-testid="inspector-open-definition"
              disabled={node.missingSpec}
              title={
                node.missingSpec
                  ? 'No spec found for this node type, so there is no @node function to open.'
                  : `Open the @node function ${node.typeName} — the shared definition behind this node`
              }
              onClick={() => onEditSource(true)}
            >
              <span className="ge-inspector__def-label">{'</>'} Open node definition</span>
              <span className="ge-inspector__def-sub" data-testid="inspector-def-shared">
                {definitionSubtitle}
              </span>
            </button>
          </section>
        </div>
      )}
    </aside>
  );
}
