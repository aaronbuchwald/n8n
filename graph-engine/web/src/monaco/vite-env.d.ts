// Types for Vite's `?worker` virtual import, used by the Monaco worker setup in
// monaco/setup.ts. Declared narrowly (rather than referencing all of
// `vite/client`) so unrelated virtual-module types — e.g. CSS imports guarded by
// @ts-expect-error elsewhere — are left untouched.
declare module '*?worker' {
  const workerConstructor: { new (): Worker };
  export default workerConstructor;
}
