// ADR 0017 W4 — the drag payload contract for adding a node to the canvas.
//
// A catalog entry's drag carries its spec id under this MIME type; `GraphView`'s
// `onDragOver`/`onDrop` read it and call `createNode(type, dropPosition)`. The
// constant lived in the old left `Palette` (ADR 0011 W5) until W4 retired that
// surface; it now has a neutral home shared by the catalog and the canvas. The
// value is unchanged, so the byte-for-byte drop contract still holds.
export const PALETTE_SPEC_MIME = 'application/x-graph-engine-spec';
