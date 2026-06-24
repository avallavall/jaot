import { describe, it, expect } from "vitest";
import { ACTION_LABELS, getActionMeta } from "@/lib/audit-labels";

/**
 * All 13 backend AuditAction enum values from app/models/audit_log.py
 */
const BACKEND_AUDIT_ACTIONS = [
  "solve",
  "model_edit",
  "model_delete",
  "member_invite",
  "member_remove",
  "role_change",
  "pool_allocate",
  "workspace_create",
  "workspace_update",
  "trigger_create",
  "trigger_update",
  "trigger_delete",
  "trigger_fire",
] as const;

/**
 * Stale/wrong keys that existed in the old ACTION_LABELS and must NOT be present
 */
const STALE_KEYS = [
  "workspace_created",
  "workspace_updated",
  "workspace_deleted",
  "member_added",
  "member_removed",
  "member_role_updated",
  "invite_created",
  "invite_accepted",
  "invite_revoked",
  "credits_allocated",
  "solve_executed",
];

describe("Audit ACTION_LABELS", () => {
  it("has exactly 13 entries matching all backend AuditAction values", () => {
    expect(Object.keys(ACTION_LABELS)).toHaveLength(13);
  });

  it.each(BACKEND_AUDIT_ACTIONS)(
    "has an explicit entry for backend action '%s'",
    (action) => {
      expect(ACTION_LABELS[action]).toBeDefined();
      expect(ACTION_LABELS[action].label).toBeTruthy();
      expect(ACTION_LABELS[action].color).toBeTruthy();
    }
  );

  it("trigger_update displays as 'Trigger Updated'", () => {
    expect(ACTION_LABELS["trigger_update"].label).toBe("Trigger Updated");
  });

  it.each(STALE_KEYS)(
    "does NOT contain stale key '%s'",
    (key) => {
      expect(ACTION_LABELS[key]).toBeUndefined();
    }
  );
});

describe("getActionMeta fallback", () => {
  it("returns explicit label for known actions", () => {
    const meta = getActionMeta("solve");
    expect(meta.label).toBe("Solve Executed");
  });

  it("returns capitalized fallback for unknown actions", () => {
    const meta = getActionMeta("some_new_action");
    expect(meta.label).toBe("Some New Action");
  });

  it("returns gray color for unknown actions", () => {
    const meta = getActionMeta("unknown_future_action");
    expect(meta.color).toContain("bg-gray");
  });
});
