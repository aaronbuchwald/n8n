import { Suspense } from 'react';
import type { RunResult } from '../api';
import { rendererFor } from '../node-renderers';
import { previewType, previewValue } from '../preview';
import type { GraphDoc, GraphNode, NodeSpec, NodeSpecs } from '../types';

interface RunResultsPanelProps {
  run: RunResult;
  /** The graph the run executed — used to label rows "id · title". */
  graph: GraphDoc;
  specs: NodeSpecs;
  /** Focus (select + centre) a node on the canvas. */
  onFocusNode: (nodeId: string) => void;
  onClose: () => void;
}

/** The graph's declared output socket value, if the run produced one. */
function outputValue(run: RunResult): unknown {
  if (!run.output) return undefined;
  return run.outputs[run.output.node]?.[run.output.socket];
}

/** The output node's graph entry + spec, when both resolve (ADR 0010 D7). */
function outputNodeOf(
  run: RunResult,
  graph: GraphDoc,
  specs: NodeSpecs,
): { node: GraphNode; spec: NodeSpec } | null {
  if (!run.output) return null;
  const node = graph.nodes.find((n) => n.id === run.output?.node);
  const spec = node ? specs[node.type] : undefined;
  return node && spec ? { node, spec } : null;
}

/** Node ids with outputs, in execution order (ids missing from `order` last). */
function orderedNodeIds(run: RunResult): string[] {
  const withOutputs = Object.keys(run.outputs);
  const ordered = run.order.filter((id) => withOutputs.includes(id));
  return [...ordered, ...withOutputs.filter((id) => !ordered.includes(id))];
}

/**
 * The "see the result" surface for a run: the graph's declared output socket
 * rendered in a fully sandboxed iframe (never dangerouslySetInnerHTML), plus a
 * per-node table of every socket value. Run errors are surfaced here too — and
 * a failed run still lists whatever the nodes that DID execute produced.
 */
export function RunResultsPanel({ run, graph, specs, onFocusNode, onClose }: RunResultsPanelProps) {
  const hasErrors = run.errors.length > 0;
  const output = outputValue(run);
  // Only a string can be a self-contained HTML document; anything else (a
  // number, a $repr preview) is shown as text rather than fed to the iframe.
  const html = typeof output === 'string' ? output : null;

  // ADR 0010 D7: the output node's declared renderer resolves the SAME registry
  // the node card uses (`surface: 'panel'`); no declaration (or an unshipped
  // kind) falls back to the string-iframe / preview-text behavior below.
  const outputNode = outputNodeOf(run, graph, specs);
  const OutputRenderer = outputNode ? rendererFor(outputNode.spec.renderer) : null;

  // id → spec title, so rows can carry the same label the node cards show.
  const titleOf = (nodeId: string): string | null => {
    const node = graph.nodes.find((n) => n.id === nodeId);
    const title = node ? specs[node.type]?.title : undefined;
    return title && title !== nodeId ? title : null;
  };

  const executed = orderedNodeIds(run);
  const total = graph.nodes.length;

  return (
    <section className="ge-results" data-testid="run-results" aria-label="Run results">
      <div className="ge-results__head">
        <span className="ge-results__title">run results</span>
        <span className="ge-results__sub">
          {hasErrors
            ? `run failed · ${executed.length} of ${total} nodes completed`
            : `${run.order.length} nodes executed`}
        </span>
        <button type="button" className="ge-btn ge-btn--ghost" onClick={onClose}>
          Close
        </button>
      </div>

      {hasErrors && (
        <div className="ge-results__errors" data-testid="run-error" role="alert">
          {run.errors.map((err, i) => (
            <div className="ge-results__error" key={i}>
              <span className="ge-results__error-code">{err.code}</span>
              {err.nodeId && <span className="ge-results__error-node">{err.nodeId}</span>}
              <span className="ge-results__error-msg">{err.message}</span>
            </div>
          ))}
        </div>
      )}

      <div className="ge-results__body">
        <div className="ge-results__render">
          <div className="ge-results__label">output render</div>
          {OutputRenderer && outputNode ? (
            <Suspense fallback={<div className="ge-results__empty">…</div>}>
              <OutputRenderer
                nodeId={outputNode.node.id}
                spec={outputNode.spec}
                config={outputNode.spec.renderer?.config ?? {}}
                boundInputs={outputNode.node.inputs}
                wiredInputs={
                  new Set(
                    graph.edges
                      .filter((e) => e.target === outputNode.node.id)
                      .map((e) => e.targetInput),
                  )
                }
                result={run.outputs[outputNode.node.id] ?? null}
                hasError={run.errors.some((err) => err.nodeId === outputNode.node.id)}
                surface="panel"
              />
            </Suspense>
          ) : html !== null ? (
            <iframe
              className="ge-results__frame"
              data-testid="run-result-frame"
              title="Graph output render"
              // Fully sandboxed: no scripts, no same-origin, no forms. The node
              // output is untrusted HTML, so it can never touch the host page.
              sandbox=""
              srcDoc={html}
            />
          ) : (
            <div className="ge-results__empty">
              {output === undefined
                ? hasErrors
                  ? 'the run failed before producing the output socket'
                  : 'no output socket value'
                : `${previewType(output)}: ${previewValue(output)}`}
            </div>
          )}
        </div>

        <div className="ge-results__nodes">
          <div className="ge-results__label">per-node outputs</div>
          <div className="ge-results__list">
            {executed.map((nodeId) => {
              const sockets = run.outputs[nodeId] ?? {};
              const title = titleOf(nodeId);
              return (
                <button
                  type="button"
                  className="ge-results__node"
                  key={nodeId}
                  data-testid="result-node"
                  title={`Show ${nodeId} on the canvas`}
                  onClick={() => onFocusNode(nodeId)}
                >
                  <div className="ge-results__node-id">
                    {nodeId}
                    {title && <span className="ge-results__node-title"> · {title}</span>}
                  </div>
                  {Object.entries(sockets).map(([socket, value]) => (
                    <div className="ge-results__socket" key={socket}>
                      <span className="ge-results__socket-name">{socket}</span>
                      <span className="ge-results__socket-type">{previewType(value)}</span>
                      <span className="ge-results__socket-value">{previewValue(value)}</span>
                    </div>
                  ))}
                </button>
              );
            })}
            {executed.length === 0 && (
              <div className="ge-results__empty">
                {hasErrors ? 'the run failed before any node completed' : 'no outputs'}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
