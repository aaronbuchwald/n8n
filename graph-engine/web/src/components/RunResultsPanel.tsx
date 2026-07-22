import type { RunResult } from '../api';
import { previewType, previewValue } from '../preview';

interface RunResultsPanelProps {
  run: RunResult;
  onClose: () => void;
}

/** The graph's declared output socket value, if the run produced one. */
function outputValue(run: RunResult): unknown {
  if (!run.output) return undefined;
  return run.outputs[run.output.node]?.[run.output.socket];
}

/**
 * The "see the result" surface for a run: the graph's declared output socket
 * rendered in a fully sandboxed iframe (never dangerouslySetInnerHTML), plus a
 * per-node table of every socket value. Run errors are surfaced here too.
 */
export function RunResultsPanel({ run, onClose }: RunResultsPanelProps) {
  const hasErrors = run.errors.length > 0;
  const output = outputValue(run);
  // Only a string can be a self-contained HTML document; anything else (a
  // number, a $repr preview) is shown as text rather than fed to the iframe.
  const html = typeof output === 'string' ? output : null;

  return (
    <section className="ge-results" data-testid="run-results" aria-label="Run results">
      <div className="ge-results__head">
        <span className="ge-results__title">run results</span>
        <span className="ge-results__sub">
          {hasErrors ? 'run failed' : `${run.order.length} nodes executed`}
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
          {html !== null ? (
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
                ? 'no output socket value'
                : `${previewType(output)}: ${previewValue(output)}`}
            </div>
          )}
        </div>

        <div className="ge-results__nodes">
          <div className="ge-results__label">per-node outputs</div>
          <div className="ge-results__list">
            {Object.entries(run.outputs).map(([nodeId, sockets]) => (
              <div className="ge-results__node" key={nodeId} data-testid="result-node">
                <div className="ge-results__node-id">{nodeId}</div>
                {Object.entries(sockets).map(([socket, value]) => (
                  <div className="ge-results__socket" key={socket}>
                    <span className="ge-results__socket-name">{socket}</span>
                    <span className="ge-results__socket-type">{previewType(value)}</span>
                    <span className="ge-results__socket-value">{previewValue(value)}</span>
                  </div>
                ))}
              </div>
            ))}
            {Object.keys(run.outputs).length === 0 && !hasErrors && (
              <div className="ge-results__empty">no outputs</div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
