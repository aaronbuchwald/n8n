// ─────────────────────────────────────────────────────────────────────────────
// The CONTENT-REACHABILITY invariant.
//
// Playwright's `toBeVisible()` asserts PRESENCE, not REACHABILITY: it is true
// for content that is laid out but clipped away by an `overflow:hidden` box the
// user can never scroll. Three shipped bugs were exactly that shape:
//
//   1. `.ge-results__render { overflow: hidden }` — a card taller than the
//      output panel was cut off with no way to scroll to the rest.
//   2. the calc card's `.card { overflow:hidden }` + `white-space:nowrap` cells:
//      at node-card width (~280px) the rows/checks were wider than the box and
//      HORIZONTALLY unreachable (a vertical scrollbar existed; a horizontal one
//      did not).
//   3. generally: `overflow:hidden` is the reflexive fix for two legitimate
//      problems (clip to a border radius; make a flex child shrink instead of
//      blowing out its parent). Both are locally correct and silently make
//      content unreachable once the box is small or the content grows.
//
// THE RULE
//   For every rendered element, on each axis independently:
//     overflowing  ⇔  scrollSize > clientSize + TOLERANCE_PX
//   An overflowing element is OK if IT OR ANY ANCESTOR is a scrollport on the
//   SAME axis (computed `overflow-x`/`overflow-y` of `auto`/`scroll`), i.e. some
//   box can bring the content into view. Otherwise it is a FAILURE.
//
// TWO SUBTLETIES THIS ENCODES DELIBERATELY
//   * We do NOT require the overflowing element itself to scroll. An element may
//     overflow VISIBLY and still be perfectly reachable because an ancestor
//     scrolls — e.g. the calc card's `.checks` overflows visibly inside a
//     scrolling `.sec`. That is correct and must pass.
//   * A scrollport and `min-width:max-content` must be DIFFERENT elements. If
//     one box carries both, it simply grows: `scrollWidth === clientWidth`, no
//     scrollbar, and the clipping moves silently to its parent. The walk catches
//     that at the parent, and `clipsAt` in the report names the box that
//     actually clips — so the fix lands on the right element.
//
// THE EXEMPTION (deliberate truncation)
//   A single-line label that ellipsises is fine WHEN THE FULL VALUE IS
//   RECOVERABLE ANOTHER WAY. Exempt, precisely:
//     * x axis: computed `text-overflow: ellipsis` AND a non-empty `title`;
//     * y axis: computed `-webkit-line-clamp` other than `none` AND a non-empty
//       `title` (e.g. `.ge-node__doc`, clamped to two lines with the full
//       docstring in the tooltip);
//     * either axis: an explicit `data-truncates="ok"` opt-out on the element or
//       an ancestor — for author-declared truncation whose full value is
//       recoverable some other way (a copy button, an expander).
//   Ellipsis ALONE is never enough: a truncated value with no way to read it is
//   the very bug this invariant exists to catch.
//
// THREE QUALIFIERS keep the rule honest rather than noisy. Each is documented
// where it is implemented; none of them is a blanket escape hatch:
//   * geometric confirmation (`visibleClipBand`) — the scroll area must really
//     run past the last box that can show it;
//   * collapsed regions (`clientSize <= 0`, or a zero-extent clip band) — a
//     collapsed dock shows nothing on that axis; its rail is the affordance;
//   * pan surfaces (`DEFAULT_PAN_SURFACES`) — the ReactFlow canvas brings
//     content into view by panning, a real gesture that is not a scrollbar.
//
// KNOWN LIMIT: `scrollWidth`/`scrollHeight` only see overflow past the END edge
// (right/bottom in LTR). Content pushed off the top/left is not measured.
// ─────────────────────────────────────────────────────────────────────────────

import { expect, type Page } from '@playwright/test';

/** Sub-pixel slack, so fractional layout rounding is not reported as overflow. */
export const TOLERANCE_PX = 2;

/**
 * Whole subtrees excluded from the walk, each for a stated reason. Kept tiny on
 * purpose — a broad ignore list makes the invariant worthless.
 */
export const DEFAULT_IGNORE_SUBTREES: readonly string[] = [
  // Monaco virtualises its own scrolling with transforms and absolutely
  // positioned overlays; its internal boxes intentionally overflow and DOM
  // scrollWidth/clientWidth say nothing about what the user can reach.
  '.monaco-editor',
  // The minimap is a deliberate scaled-down proxy of the canvas, not content.
  '.react-flow__minimap',
];

/**
 * ReactFlow's transform-panned surface. Two consequences, both deliberate:
 *
 *  * these boxes are not MEASURED themselves — the whole graph lives outside the
 *    pane box by design, which is not a clipping bug;
 *  * they COUNT AS SCROLLPORTS in the ancestor walk — content clipped at the
 *    canvas edge is reached by panning/zooming, which is a real way to bring it
 *    into view, just not a scrollbar. (This is what makes the ~10px of
 *    connector handle deliberately overhanging each node card a non-finding.)
 *
 * Their DESCENDANTS are still walked: a node card that clips its own rows is
 * exactly the bug family this invariant exists for.
 */
export const DEFAULT_PAN_SURFACES: readonly string[] = [
  '.react-flow',
  '.react-flow__renderer',
  '.react-flow__pane',
  '.react-flow__viewport',
  '.react-flow__nodes',
  '.react-flow__edges',
];

export interface ReachabilityOptions {
  /** Sub-pixel slack in px. Default {@link TOLERANCE_PX}. */
  tolerancePx?: number;
  /** Extra subtree selectors to skip, on top of {@link DEFAULT_IGNORE_SUBTREES}. */
  ignore?: readonly string[];
  /** Replace the pan-surface list (self-excluded, descendants still walked). */
  panSurfaces?: readonly string[];
}

/** One unreachable-content finding. */
export interface ReachabilityViolation {
  axis: 'x' | 'y';
  /** Human selector for the overflowing element (tag + testid + classes). */
  element: string;
  scrollSize: number;
  clientSize: number;
  overflowPx: number;
  /**
   * The nearest self-or-ancestor whose computed overflow on this axis is
   * `hidden`/`clip` — the box that ACTUALLY clips, and where the fix belongs.
   * Null when nothing clips before the (non-scrolling) viewport.
   */
  clipsAt: string | null;
  /** self → html, each annotated with its computed overflow on this axis. */
  chain: string[];
}

/**
 * Run the invariant in the page (or in whatever document `page` currently
 * holds — `page.setContent(...)` works identically) and return every violation.
 */
export async function findUnreachableContent(
  page: Page,
  options: ReachabilityOptions = {},
): Promise<ReachabilityViolation[]> {
  const tolerancePx = options.tolerancePx ?? TOLERANCE_PX;
  const ignore = [...DEFAULT_IGNORE_SUBTREES, ...(options.ignore ?? [])];
  const panSurfaces = [...(options.panSurfaces ?? DEFAULT_PAN_SURFACES)];

  return await page.evaluate(
    ({ tolerancePx: tol, ignore: ignoreSelectors, panSurfaces: panSurfaceSelectors }) => {
      type Axis = 'x' | 'y';

      /** A short, greppable identity for an element. */
      function describe(el: Element): string {
        if (el === document.documentElement) return 'html';
        if (el === document.body) return 'body';
        let out = el.tagName.toLowerCase();
        const testid = el.getAttribute('data-testid');
        if (testid) out += `[data-testid="${testid}"]`;
        const classes = (el.getAttribute('class') ?? '')
          .trim()
          .split(/\s+/)
          .filter(Boolean);
        if (classes.length > 0) out += '.' + classes.slice(0, 4).join('.');
        if (!testid && classes.length === 0 && el.id) out += `#${el.id}`;
        return out;
      }

      function overflowOn(el: Element, axis: Axis): string {
        const cs = getComputedStyle(el);
        return axis === 'x' ? cs.overflowX : cs.overflowY;
      }

      /** Is this box a scrollport on `axis` — can it bring content into view? */
      function isScrollport(el: Element, axis: Axis): boolean {
        // A pan surface brings content into view by panning/zooming rather than
        // by scrolling — a different gesture, but content is still reachable.
        if (panSurfaceSelectors.some((sel) => el.matches(sel))) return true;
        const value = overflowOn(el, axis);
        if (el === document.documentElement) {
          // The root's overflow propagates to the VIEWPORT, so `visible` here
          // can mean "the page itself scrolls" — but ONLY when the document
          // really has somewhere to scroll to. In an app shell (`html, body,
          // #root { height: 100% }`) it never does: overflow clipped by some
          // box further down never reaches the document scroll area, and
          // treating the viewport as an unconditional rescuer would make the
          // whole invariant vacuous.
          if (value === 'hidden' || value === 'clip') return false;
          const scrollSize = axis === 'x' ? el.scrollWidth : el.scrollHeight;
          const clientSize = axis === 'x' ? el.clientWidth : el.clientHeight;
          return scrollSize - clientSize > tol;
        }
        return value === 'auto' || value === 'scroll' || value === 'overlay';
      }

      /**
       * Deliberate, recoverable truncation — see the exemption note at the top
       * of this file. Ellipsis alone is NOT enough.
       */
      function isExemptTruncation(el: Element, axis: Axis): boolean {
        if (el.closest('[data-truncates="ok"]')) return true;
        const hasTitle = (el.getAttribute('title') ?? '').trim().length > 0;
        if (!hasTitle) return false;
        const cs = getComputedStyle(el);
        if (axis === 'x') return cs.textOverflow === 'ellipsis';
        const clamp = cs.webkitLineClamp;
        return Boolean(clamp) && clamp !== 'none';
      }

      /** Does this element have a client box the measurement is meaningful for? */
      function hasMeasurableBox(el: Element): boolean {
        const cs = getComputedStyle(el);
        // Inline (non-replaced) and display:contents boxes report clientWidth 0
        // while scrollWidth is non-zero — a pure measurement artefact.
        if (cs.display === 'none' || cs.display === 'contents' || cs.display === 'inline') {
          return false;
        }
        if (el.clientWidth === 0 && el.clientHeight === 0) return false;
        // (per-axis zero sizes are handled in the walk — see COLLAPSED below)
        // Not painted at all (visibility/opacity/content-visibility) → nothing
        // to reach; a hidden panel is not a clipping bug.
        const withVisibilityCheck = el as Element & {
          checkVisibility?: (opts: Record<string, boolean>) => boolean;
        };
        if (typeof withVisibilityCheck.checkVisibility === 'function') {
          return withVisibilityCheck.checkVisibility({
            checkOpacity: true,
            checkVisibilityCSS: true,
            contentVisibilityAuto: true,
          });
        }
        return true;
      }

      /** Far edge (right/bottom) of an element's PADDING box, in viewport px. */
      function paddingBoxFarEdge(el: Element, axis: Axis): number {
        const rect = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return axis === 'x'
          ? rect.left + parseFloat(cs.borderLeftWidth || '0') + el.clientWidth
          : rect.top + parseFloat(cs.borderTopWidth || '0') + el.clientHeight;
      }

      /** Near edge (left/top) of an element's PADDING box, in viewport px. */
      function paddingBoxNearEdge(el: Element, axis: Axis): number {
        const rect = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return axis === 'x'
          ? rect.left + parseFloat(cs.borderLeftWidth || '0')
          : rect.top + parseFloat(cs.borderTopWidth || '0');
      }

      /**
       * The band the user can actually SEE this element's content in: the
       * tightest of every clipping self-or-ancestor padding box, and the
       * viewport.
       *
       * The far edge is the geometric confirmation that the content is really
       * cut off — without it, anything that merely paints OUTSIDE an
       * `overflow:visible` box (an anchored popover, a dropdown) reads as a
       * violation even though it sits plainly on screen and fully readable.
       *
       * The band's WIDTH matters too: a zero-extent band means the content lives
       * in a fully COLLAPSED region, which is not a clip — a collapsed dock or
       * results panel shows a rail whose whole job is to bring it back.
       */
      function visibleClipBand(el: Element, axis: Axis): { near: number; far: number } {
        let near = 0;
        let far = axis === 'x' ? window.innerWidth : window.innerHeight;
        for (let node: Element | null = el; node; node = node.parentElement) {
          const value = overflowOn(node, axis);
          if (value === 'hidden' || value === 'clip') {
            near = Math.max(near, paddingBoxNearEdge(node, axis));
            far = Math.min(far, paddingBoxFarEdge(node, axis));
          }
        }
        return { near, far };
      }

      const violations: ReachabilityViolationShape[] = [];
      interface ReachabilityViolationShape {
        axis: Axis;
        element: string;
        scrollSize: number;
        clientSize: number;
        overflowPx: number;
        clipsAt: string | null;
        chain: string[];
      }

      for (const el of Array.from(document.querySelectorAll('*'))) {
        if (ignoreSelectors.some((sel) => el.closest(sel))) continue;
        if (panSurfaceSelectors.some((sel) => el.matches(sel))) continue;
        if (!hasMeasurableBox(el)) continue;

        const axes: Array<{ axis: Axis; scrollSize: number; clientSize: number }> = [
          { axis: 'x', scrollSize: el.scrollWidth, clientSize: el.clientWidth },
          { axis: 'y', scrollSize: el.scrollHeight, clientSize: el.clientHeight },
        ];

        for (const { axis, scrollSize, clientSize } of axes) {
          const overflowPx = scrollSize - clientSize;
          if (overflowPx <= tol) continue;
          // COLLAPSED: a box with no extent at all on this axis shows nothing —
          // that is a collapse (with its own expand affordance), not a clip.
          if (clientSize <= 0) continue;
          if (isExemptTruncation(el, axis)) continue;

          // Reachable if the element ITSELF or ANY ancestor scrolls on this
          // axis. We deliberately do NOT require the overflowing element to be
          // the scrollport.
          let reachable = false;
          let clipsAt: string | null = null;
          const chain: string[] = [];
          for (let node: Element | null = el; node; node = node.parentElement) {
            chain.push(`${describe(node)} — overflow-${axis}: ${overflowOn(node, axis)}`);
            if (isScrollport(node, axis)) {
              reachable = true;
              break;
            }
            if (clipsAt === null) {
              const value = overflowOn(node, axis);
              if (value === 'hidden' || value === 'clip') clipsAt = describe(node);
            }
          }
          if (reachable) continue;

          // Geometric confirmation: the scroll area really does run past the
          // last box that can show it. Style analysis alone would flag an
          // anchored popover that simply paints outside its `overflow:visible`
          // anchor while sitting plainly on screen.
          const band = visibleClipBand(el, axis);
          // Inside a fully collapsed region — see visibleClipBand.
          if (band.far - band.near <= tol) continue;
          const scrollOffset = axis === 'x' ? el.scrollLeft : el.scrollTop;
          const contentFarEdge = paddingBoxFarEdge(el, axis) + overflowPx - scrollOffset;
          if (contentFarEdge <= band.far + tol) continue;

          violations.push({
            axis,
            element: describe(el),
            scrollSize,
            clientSize,
            overflowPx,
            clipsAt,
            chain,
          });
        }
      }
      return violations;
    },
    { tolerancePx, ignore, panSurfaces },
  );
}

/** Render one violation as a report a developer can act on without re-deriving. */
export function formatViolation(v: ReachabilityViolation): string {
  const size = v.axis === 'x' ? 'Width' : 'Height';
  const lines = [
    `  UNREACHABLE (${v.axis}-axis): ${v.element}`,
    `    scroll${size} ${v.scrollSize} > client${size} ${v.clientSize} ` +
      `(${v.overflowPx}px of content past the edge)`,
    `    clipped by: ${v.clipsAt ?? '(nothing clips — the viewport itself does not scroll)'}`,
    `    no ancestor scrolls on ${v.axis}:`,
    ...v.chain.map((step) => `      ${step}`),
  ];
  return lines.join('\n');
}

/**
 * Assert the content-reachability invariant for the page's CURRENT state.
 * `state` names the state/viewport under test so a failure reads as a repro.
 */
export async function expectContentReachable(
  page: Page,
  state: string,
  options: ReachabilityOptions = {},
): Promise<void> {
  const violations = await findUnreachableContent(page, options);
  const report = [
    '',
    `CONTENT-REACHABILITY FAILED — ${violations.length} element(s) clipped with no way to scroll to them.`,
    `  state:    ${state}`,
    `  viewport: ${JSON.stringify(page.viewportSize())}`,
    `  url:      ${page.url()}`,
    '',
    ...violations.map(formatViolation),
    '',
    'How to fix: give the box named in `clipped by:` an `overflow-x`/`overflow-y` of',
    '`auto` on the FAILING AXIS — not necessarily the overflowing element itself, and',
    'note that one box carrying BOTH `overflow:auto` and `min-width:max-content` just',
    'grows instead of scrolling (the clipping then moves silently to its parent).',
    'Deliberate truncation is exempt only when the full value stays recoverable:',
    'computed `text-overflow: ellipsis` + a non-empty `title` (x axis),',
    '`-webkit-line-clamp` + a non-empty `title` (y axis), or `data-truncates="ok"`.',
    '',
  ].join('\n');
  // Assert on the COUNT, not the objects: the authored report above is the whole
  // signal, and a raw object diff would bury it.
  expect(violations.length, report).toBe(0);
}
