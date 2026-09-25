import { describe, it, expect } from "vitest";
import { AUDIT_ACTIONS, AUDIT_ACTION_COLORS, getActionMeta } from "@/lib/audit-labels";
import en from "../../../../../messages/en.json";
import es from "../../../../../messages/es.json";
import ca from "../../../../../messages/ca.json";
import fr from "../../../../../messages/fr.json";
import de from "../../../../../messages/de.json";

/**
 * Backend AuditAction values (app/models/audit_log.py) that a WORKSPACE log can
 * hold. API key actions are organization-level and never carry a workspace.
 */
const WORKSPACE_AUDIT_ACTIONS = [
  "solve",
  "model_edit",
  "model_delete",
  "model_publish",
  "model_unpublish",
  "member_invite",
  "member_join",
  "member_remove",
  "role_change",
  "invite_revoke",
  "workspace_create",
  "workspace_update",
  "trigger_create",
  "trigger_update",
  "trigger_delete",
  "trigger_fire",
  "trigger_schedule_create",
  "trigger_schedule_update",
  "trigger_schedule_delete",
] as const;

/** Keys that must NOT come back. `pool_allocate` went with the credit pools (ADR-008). */
const STALE_KEYS = [
  "pool_allocate",
  "workspace_created",
  "member_added",
  "invite_accepted",
  "credits_allocated",
  "solve_executed",
];

const LOCALES = { en, es, ca, fr, de } as const;

function translator(actions: Record<string, string>) {
  const t = (key: string) => actions[key];
  t.has = (key: string) => key in actions;
  return t;
}

describe("Audit actions", () => {
  it("lists exactly the actions a workspace log can hold", () => {
    expect([...AUDIT_ACTIONS].sort()).toEqual([...WORKSPACE_AUDIT_ACTIONS].sort());
  });

  // CONTRACT-TEST: the audit filter no longer offers "Credits Allocated".
  it.each(STALE_KEYS)("does not offer the stale action '%s'", (key) => {
    expect(AUDIT_ACTION_COLORS[key]).toBeUndefined();
  });

  it.each(Object.keys(LOCALES) as (keyof typeof LOCALES)[])(
    "has a label for every action in %s",
    (locale) => {
      const actions = LOCALES[locale].workspace.audit.actions as Record<string, string>;
      for (const action of AUDIT_ACTIONS) {
        expect(actions[action], `${locale}: ${action}`).toBeTruthy();
      }
    },
  );

  it("labels a join as a join, in the reader's language", () => {
    const actions = es.workspace.audit.actions as Record<string, string>;
    const meta = getActionMeta("member_join", translator(actions));
    expect(meta.label).toBe(actions.member_join);
    expect(meta.label).not.toBe(actions.member_invite);
  });
});

describe("getActionMeta fallback", () => {
  const t = translator(en.workspace.audit.actions as Record<string, string>);

  it("returns the translated label for a known action", () => {
    expect(getActionMeta("trigger_update", t).label).toBe("Trigger Updated");
  });

  it("returns a capitalized fallback for an unknown action", () => {
    expect(getActionMeta("some_new_action", t).label).toBe("Some New Action");
  });

  it("returns gray for an unknown action", () => {
    expect(getActionMeta("pool_allocate", t).color).toContain("bg-gray");
  });
});
