import type { GraphId } from '../api';
import type { InspectedInput, InspectedNode, InputSource, ResolvedValue } from '../inspect';
import { previewType, previewValue } from '../preview';
import { SourceEditor } from './SourceEditor';

interface NodeInspectorProps {
  node: InspectedNode;
  /** How many canvas nodes share this node's type (>= 1). */
  sharedNodeCount: number;
  /** The selected entry point source reads/writes are scoped to. */
  graphId: GraphId;
  /** True while the inspector is expanded into the node's source editor. */
  editingSource: boolean;
  onEditSource: (open: boolean) => void;
  /** A source save landed — the app refreshes specs/graph quietly. */
  onSourceSaved: () => void;
  /** The source-editor buffer's unsaved state changed (ADR 0009 D6). */
  onSourceDirtyChange?: (dirty: boolean) => void;
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

function InputRow({ input }: { input: InspectedInput }) {
  const resolved = inputValue(input);
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
      <ValueLine resolved={resolved} />
    </div>
  );
}

/**
 * The per-node detail panel, opened by clicking a node on the canvas. Shows
 * where every input comes from and — after a run — the concrete value that
 * flowed through each input and output. "Edit source" expands the panel into
 * the source editor for THIS node's `@node` function (its type), so source
 * editing is always launched from a node instead of a global picker.
 */
export function NodeInspector({
  node,
  sharedNodeCount,
  graphId,
  editingSource,
  onEditSource,
  onSourceSaved,
  onSourceDirtyChange,
  onClose,
}: NodeInspectorProps) {
  const editing = editingSource && !node.missingSpec;
  return (
    <aside
      className={`ge-inspector${editing ? ' ge-inspector--editing' : ''}`}
      data-testid="node-inspector"
      aria-label={`Inspect node ${node.id}`}
    >
      <div className="ge-inspector__head">
        <div className="ge-inspector__heading">
          {/* "id · title" so the inspector shares a visible key with both the
              node cards (title) and the run-results rows (id). */}
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

      {!editing && (
        <div className="ge-inspector__toolbar">
          <button
            type="button"
            className="ge-btn ge-inspector__source-btn"
            data-testid="inspector-edit-source"
            disabled={node.missingSpec}
            title={
              node.missingSpec
                ? 'No spec found for this node type, so there is no @node function to edit.'
                : `Edit the @node function ${node.typeName} — the source behind this node`
            }
            onClick={() => onEditSource(true)}
          >
            {'</>'} Edit source
          </button>
          <span className="ge-inspector__source-hint" title={node.typeName}>
            {node.missingSpec ? 'unknown type — no source' : node.typeName}
          </span>
        </div>
      )}

      {editing ? (
        <SourceEditor
          specId={node.typeName}
          sharedNodeCount={sharedNodeCount}
          graphId={graphId}
          onSaved={onSourceSaved}
          onClose={() => onEditSource(false)}
          onDirtyChange={onSourceDirtyChange}
        />
      ) : (
      <div className="ge-inspector__body">
        {node.doc && <p className="ge-inspector__doc">{node.doc}</p>}
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
            <InputRow input={input} key={input.name} />
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
      </div>
      )}
    </aside>
  );
}
