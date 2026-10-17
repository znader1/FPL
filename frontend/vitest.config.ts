import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    // Without an explicit include, vitest walked the whole tree and collected
    // tests out of .claude/worktrees/* — a stale checkout with its own
    // node_modules — so `npm test` reported 9 failures that had nothing to do
    // with src/. See docs/prelaunch_audit_2026-09-12.md in the backend repo.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["**/node_modules/**", "**/dist/**", ".claude/**"],
  },
});
