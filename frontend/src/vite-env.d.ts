/// <reference types="vite/client" />

// Vite serves this through a virtual module (vite:modulepreload-polyfill
// plugin) rather than a package export, so TS can't see it — declare it
// to silence "Cannot find module" on the side-effect imports in the
// main.tsx entries.
declare module 'vite/modulepreload-polyfill';
