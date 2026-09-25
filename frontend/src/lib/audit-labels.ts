/**
 * The audit actions a workspace log can show, and the badge colour of each.
 *
 * Keys are the backend `AuditAction` values (app/models/audit_log.py). The label
 * of each lives in the messages under `workspace.audit.actions.<value>`: it was
 * English here, so the Spanish log read "Member Removed".
 *
 * Organization-level actions (API keys) are not listed: they carry no
 * workspace, so a workspace log never holds them. `pool_allocate` went with the
 * credit pools (ADR-008); an old row shows by its raw name.
 */
const GREEN = "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400";
const BLUE = "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400";
const RED = "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400";
const YELLOW = "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400";
const GRAY = "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400";

export const AUDIT_ACTION_COLORS: Record<string, string> = {
  solve: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/20 dark:text-indigo-400",
  model_edit: BLUE,
  model_delete: RED,
  model_publish: GREEN,
  model_unpublish: YELLOW,
  member_invite: GREEN,
  member_join: GREEN,
  member_remove: RED,
  role_change: YELLOW,
  invite_revoke: RED,
  workspace_create: GREEN,
  workspace_update: BLUE,
  trigger_create: GREEN,
  trigger_update: BLUE,
  trigger_delete: RED,
  trigger_fire: "bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400",
  trigger_schedule_create: GREEN,
  trigger_schedule_update: BLUE,
  trigger_schedule_delete: RED,
};

/** The action values the filter offers, in display order. */
export const AUDIT_ACTIONS = Object.keys(AUDIT_ACTION_COLORS);

/** A translator scoped to `workspace.audit.actions`. */
export interface ActionTranslator {
  (key: string): string;
  has(key: string): boolean;
}

/**
 * Label and colour for an audit action.
 *
 * An action this list does not know (an old row, or one added to the backend
 * later) shows its raw name, capitalized, in grey.
 */
export function getActionMeta(action: string, t: ActionTranslator): { label: string; color: string } {
  const color = AUDIT_ACTION_COLORS[action];
  if (color && t.has(action)) return { label: t(action), color };
  const label = action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return { label, color: GRAY };
}
