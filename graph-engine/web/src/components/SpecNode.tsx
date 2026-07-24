import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import type { SpecNodeData } from '../types';
import { inHandle, outHandle } from '../buildGraph';
import { RendererSlot } from '../node-renderers/RendererSlot';
import { WidgetPreview } from '../widgets/WidgetPreview';
import { previewPlacementFor } from '../widgets/registry';

type SpecNode = Node<SpecNodeData, 'specNode'>;

export function SpecNode({ data }: NodeProps<SpecNode>) {
  const { id, type, spec, boundInputs, wiredInputs, wiredOutputs, isOutput, hasError, needsWiring } =
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
          <span className="ge-node__title" data-testid="node-title" title={id}>
            {id}
          </span>
        </div>
        <div className="ge-node__doc ge-node__doc--missing" title={type}>
          unknown node type: <code>{type}</code>
        </div>
        <div className="ge-node__body">
          <div className="ge-node__sockets">
            {targetNames.map((name, i) => (
              <div className="ge-socket ge-socket--in" key={`t${i}`}>
                <Handle
                  id={name ? inHandle(name) : undefined}
                  type="target"
                  position={Position.Left}
                  className="ge-handle ge-handle--in"
                />
                {name && (
                  <span className="ge-socket__name" title={name}>
                    {name}
                  </span>
                )}
              </div>
            ))}
          </div>
          <div className="ge-node__sockets ge-node__sockets--out">
            {sourceNames.map((name, i) => (
              <div className="ge-socket ge-socket--out" key={`s${i}`}>
                {name && (
                  <span className="ge-socket__name" title={name}>
                    {name}
                  </span>
                )}
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
        <RendererSlot data={data} />
      </div>
    );
  }

  return (
    <div
      className={`ge-node${isOutput ? ' ge-node--output' : ''}${hasError ? ' ge-node--error' : ''}`}
      data-testid="spec-node"
      data-node-title={spec.title}
    >
      <div className="ge-node__header">
        <span className="ge-node__title" data-testid="node-title" title={spec.title}>
          {spec.title}
        </span>
        {/* The graph id is the key the inspector and run-results rows use;
            surfacing it here gives all three surfaces one visible shared key. */}
        {id !== spec.title && (
          <span className="ge-node__id" data-testid="node-id" title={`graph id: ${id}`}>
            {id}
          </span>
        )}
        {isOutput && (
          <span className="ge-node__badge" data-testid="output-badge" title="Graph output socket">
            output
          </span>
        )}
        {/* The store's edit-mode validation (`incomplete`) badged in place —
            ADR 0011 D6/W4: a half-built node reads "needs wiring", not error. */}
        {needsWiring.length > 0 && (
          <span
            className="ge-node__badge ge-node__badge--wiring"
            data-testid="node-needs-wiring"
            title={`required inputs not yet wired: ${needsWiring.join(', ')}`}
          >
            needs wiring
          </span>
        )}
      </div>

      {spec.doc && (
        <div className="ge-node__doc" title={spec.doc}>
          {spec.doc}
        </div>
      )}

      <div className="ge-node__body">
        {spec.inputs.length > 0 && (
          <div className="ge-node__sockets">
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
                  <span className="ge-socket__name" title={input.name}>
                    {input.name}
                  </span>
                  <span className="ge-socket__type">{input.type}</span>
                  {/* The card is read-only now (ADR 0013 D1): the socket row
                      mounts the INLINE preview (value chip / table summary);
                      block previews (typeset math/calc) render in the strip
                      below. All editing lives in the inspector. */}
                  {wired ? (
                    <span className="ge-socket__state ge-socket__state--wired">wired</span>
                  ) : (
                    <WidgetPreview
                      input={input}
                      value={boundInputs[input.name]}
                      hasLiteral={hasLiteral}
                      slot="inline"
                    />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {spec.inputs.length > 0 && spec.outputs.length > 0 && (
          <div className="ge-node__divider" aria-hidden="true" />
        )}

        {spec.outputs.length > 0 && (
          <div className="ge-node__sockets ge-node__sockets--out">
            {spec.outputs.map((output) => (
              <div className="ge-socket ge-socket--out" key={output.name}>
                <span className="ge-socket__type">{output.type}</span>
                <span className="ge-socket__name" title={output.name}>
                  {output.name}
                </span>
                <Handle
                  id={outHandle(output.name)}
                  type="source"
                  position={Position.Right}
                  className="ge-handle ge-handle--out"
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Block-placement previews (ADR 0013 D2): typeset math/calc, one per
          widget-bearing unwired input whose kind registered `block`. Read-only;
          clicking still selects the node (no pointer shielding). */}
      {(() => {
        const blockInputs = spec.inputs.filter(
          (input) =>
            !wiredInputs.has(input.name) &&
            input.widget &&
            previewPlacementFor(input.widget) === 'block',
        );
        if (blockInputs.length === 0) return null;
        return (
          <div className="ge-node__previews" data-testid="node-previews">
            {blockInputs.map((input) => (
              <WidgetPreview
                key={input.name}
                input={input}
                value={boundInputs[input.name]}
                hasLiteral={Object.prototype.hasOwnProperty.call(boundInputs, input.name)}
                slot="block"
              />
            ))}
          </div>
        );
      })()}

      <RendererSlot data={data} />
    </div>
  );
}
