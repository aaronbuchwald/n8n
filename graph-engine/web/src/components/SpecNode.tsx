import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { SpecNodeData } from '../types';
import { inHandle, outHandle } from '../buildGraph';

function formatValue(v: unknown): string {
  if (typeof v === 'string') return `"${v}"`;
  return JSON.stringify(v);
}

type SpecNode = Node<SpecNodeData, 'specNode'>;

export function SpecNode({ data }: NodeProps<SpecNode>) {
  const { spec, boundInputs, wiredInputs, isOutput } = data;

  // A spec can be missing if the graph references a type with no matching spec.
  if (!spec) {
    return (
      <div className="ge-node ge-node--missing" data-testid="spec-node">
        <div className="ge-node__title">unknown node</div>
      </div>
    );
  }

  return (
    <div
      className={`ge-node${isOutput ? ' ge-node--output' : ''}`}
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
    </div>
  );
}
