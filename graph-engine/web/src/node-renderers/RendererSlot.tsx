// The one render-surface slot SpecNode mounts (ADR 0010 D3/D4). It is the
// single shared merge hazard of the renderer streams, so ALL slot logic lives
// here (an owned file): SpecNode changes reduce to rendering this component
// where ResultChips used to sit. Kind streams (10-K html-card, later kinds)
// only ADD renderer files + one registration line in index.ts; they never
// touch SpecNode or this slot.
//
// Fallback semantics (frozen, ADR 0010 wave-1 freeze 2):
//  * no spec (unknown node type), no declared renderer, or an unregistered
//    kind — today's exact behavior: chips iff `result` is non-null;
//  * a declared, registered renderer mounts whether or not a run has happened
//    (`result: null` before the first run — placeholder is the renderer's
//    call), inside a Suspense boundary (lazy kinds) and an error boundary
//    that degrades a crashing renderer to the chips instead of unmounting
//    the whole canvas node.

import { Component, Suspense, type ReactNode } from 'react';
import type { SpecNodeData } from '../types';
import './index'; // side-effect: register the built-in renderer kinds once
import { rendererFor } from './registry';
import { ResultChips } from './ResultChips';

interface RendererSlotProps {
  /** The full ReactFlow node data — the slot picks out what the contract needs. */
  data: SpecNodeData;
}

interface ErrorBoundaryProps {
  fallback: ReactNode;
  children: ReactNode;
}

// A crashing renderer must not take the node card (handles, edges, widgets)
// down with it — degrade to the fallback chips, informative never broken.
class RendererErrorBoundary extends Component<ErrorBoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function RendererSlot({ data }: RendererSlotProps) {
  const { id, spec, boundInputs, wiredInputs, result, hasError } = data;

  const decl = spec?.renderer ?? null;
  const Renderer = rendererFor(decl);

  // Today's footer, byte-identical: chips render iff a run produced values.
  const chips = result ? <ResultChips result={result} /> : null;
  if (!spec || !decl || !Renderer) return chips;

  return (
    // `nodrag`/`nowheel`/`nopan` + stopPropagation: the interaction shielding
    // WidgetSlot proved out — pointer/scroll inside the render surface must not
    // drag the node or zoom the canvas, and clicks must not select/inspect.
    <div
      className="ge-render-surface nodrag nowheel nopan"
      data-testid="render-surface"
      onClick={(event) => event.stopPropagation()}
    >
      <RendererErrorBoundary fallback={chips}>
        <Suspense fallback={<div className="ge-node__result">…</div>}>
          <Renderer
            nodeId={id}
            spec={spec}
            config={decl.config ?? {}}
            boundInputs={boundInputs}
            wiredInputs={wiredInputs}
            result={result}
            hasError={hasError}
            surface="card"
          />
        </Suspense>
      </RendererErrorBoundary>
    </div>
  );
}
