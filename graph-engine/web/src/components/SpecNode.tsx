import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { SpecNodeData } from '../types';
import { inHandle, outHandle } from '../buildGraph';
import { previewValue } from '../preview';

function formatValue(v: unknown): string {
  if (typeof v === 'string') return `"${v}"`;
  return JSON.stringify(v);
}

// A compact per-socket result overlay shown on a node after a run. Truncated so
// a long value (e.g. a big list) doesn't blow out the card.
function ResultChips({ result }: { result: Record<string, unknown> }) {
  const entries = Object.entries(result);
  if (entries.length === 0) return null;
  return (
    <div className="ge-node__result" data-testid="node-result">
      {entries.map(([socket, value]) => (
        <div className="ge-node__result-row" key={socket}>
          <span className="ge-node__result-socket">{socket}</span>
          <span className="ge-node__result-value" title={previewValue(value)}>
            {previewValue(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

type SpecNode = Node<SpecNodeData, 'specNode'>;

export function SpecNode({ data }: NodeProps<SpecNode>) {
  const { id, type, spec, boundInputs, wiredInputs, wiredOutputs, isOutput, result, hasError } =
    data;

  // A spec can be missing if the graph references a type with no matching spec.
  // Render generic target/source handles (matching the ids its edges reference)
  // so edges still connect, and surface the node's id + type for debugging.
  if (!spec) {
    const targetNames = wiredInputs.size > 0 ? [...wiredInputs] : [null];
    const sourceNames = wiredOutputs.size > 0 ? [...wiredOutputs] : [null];
    return (
      <div
        className={`ge-node ge-node--missing${hasError ? ' ge-node--error' : ''}`}
        data-testid="spec-node"
        data-node-title={id}
      >
        <div className="ge-node__header">
          <span className="ge-node__title" data-testid="node-title">
            {id}
          </span>
        </div>
        <div className="ge-node__doc ge-node__doc--missing">
          unknown node type: <code>{type}</code>
        </div>
        <div className="ge-node__body">
          <div className="ge-node__col ge-node__col--in">
            {targetNames.map((name, i) => (
              <div className="ge-socket ge-socket--in" key={`t${i}`}>
                <Handle
                  id={name ? inHandle(name) : undefined}
                  type="target"
                  position={Position.Left}
                  className="ge-handle ge-handle--in"
                />
                {name && <span className="ge-socket__name">{name}</span>}
              </div>
            ))}
          </div>
          <div className="ge-node__col ge-node__col--out">
            {sourceNames.map((name, i) => (
              <div className="ge-socket ge-socket--out" key={`s${i}`}>
                {name && <span className="ge-socket__name">{name}</span>}
                <Handle
                  id={name ? outHandle(name) : undefined}
                  type="source"
                  position={Position.Right}
                  className="ge-handle ge-handle--out"
                />
              </div>
            ))}
          </div>
        </div>
        {result && <ResultChips result={result} />}
      </div>
    );
  }

  return (
    <div
      className={`ge-node${isOutput ? ' ge-node--output' : ''}${hasError ? ' ge-node--error' : ''}`}
      data-testid="spec-node"
      data-node-title={spec.title}
      title={spec.doc}
    >
      <div className="ge-node__header">
        <span className="ge-node__title" data-testid="node-title">
          {spec.title}
        </span>
        {isOutput && (
          <span className="ge-node__badge" data-testid="output-badge" title="Graph output socket">
            output
          </span>
        )}
      </div>

      {spec.doc && <div className="ge-node__doc">{spec.doc}</div>}

      <div className="ge-node__body">
        <div className="ge-node__col ge-node__col--in">
          {spec.inputs.map((input) => {
            const wired = wiredInputs.has(input.name);
            const hasLiteral = Object.prototype.hasOwnProperty.call(boundInputs, input.name);
            return (
              <div className="ge-socket ge-socket--in" key={input.name}>
                <Handle
                  id={inHandle(input.name)}
                  type="target"
                  position={Position.Left}
                  className="ge-handle ge-handle--in"
                />
                <span className="ge-socket__name">{input.name}</span>
                <span className="ge-socket__type">{input.type}</span>
                {wired ? (
                  <span className="ge-socket__state ge-socket__state--wired">wired</span>
                ) : hasLiteral ? (
                  <span className="ge-socket__state ge-socket__state--value">
                    {formatValue(boundInputs[input.name])}
                  </span>
                ) : input.widget ? (
                  <span className="ge-socket__state ge-socket__state--widget">
                    {input.widget.kind}
                  </span>
                ) : input.required ? (
                  <span className="ge-socket__state ge-socket__state--required">required</span>
                ) : null}
              </div>
            );
          })}
        </div>

        <div className="ge-node__col ge-node__col--out">
          {spec.outputs.map((output) => (
            <div className="ge-socket ge-socket--out" key={output.name}>
              <span className="ge-socket__type">{output.type}</span>
              <span className="ge-socket__name">{output.name}</span>
              <Handle
                id={outHandle(output.name)}
                type="source"
                position={Position.Right}
                className="ge-handle ge-handle--out"
              />
            </div>
          ))}
        </div>
      </div>

      {result && <ResultChips result={result} />}
    </div>
  );
}
