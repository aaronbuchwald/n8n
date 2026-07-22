import type { InspectedInput, InspectedNode, InputSource, ResolvedValue } from '../inspect';
import { previewType, previewValue } from '../preview';

interface NodeInspectorProps {
  node: InspectedNode;
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

function InputRow({ input }: { input: InspectedInput }) {
  const resolved = inputValue(input);
  return (
    <div className="ge-inspector__row" data-testid="inspector-input">
      <div className="ge-inspector__row-head">
        <span className="ge-inspector__socket" title={input.name}>
          {input.name}
        </span>
        <span className="ge-inspector__socket-type">
          {resolved ? previewType(resolved.value) : input.type}
        </span>
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
 * flowed through each input and output.
 */
export function NodeInspector({ node, onClose }: NodeInspectorProps) {
  return (
    <aside
      className="ge-inspector"
      data-testid="node-inspector"
      aria-label={`Inspect node ${node.id}`}
    >
      <div className="ge-inspector__head">
        <div className="ge-inspector__heading">
          <span className="ge-inspector__title" data-testid="inspector-title" title={node.title}>
            {node.title}
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
                  {output.run ? previewType(output.run.value) : output.type}
                </span>
              </div>
              <ValueLine resolved={output.run} />
            </div>
          ))}
        </section>
      </div>
    </aside>
  );
}
