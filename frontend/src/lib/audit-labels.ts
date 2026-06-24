/**
 * Audit action labels matching backend AuditAction enum values exactly.
 * Source of truth: app/models/audit_log.py — AuditAction enum (13 values)
 */
export const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  solve: { label: "Solve Executed", color: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/20 dark:text-indigo-400" },
  model_edit: { label: "Model Edited", color: "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400" },
  model_delete: { label: "Model Deleted", color: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400" },
  member_invite: { label: "Member Invited", color: "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400" },
  member_remove: { label: "Member Removed", color: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400" },
  role_change: { label: "Role Changed", color: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-400" },
  pool_allocate: { label: "Credits Allocated", color: "bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400" },
  workspace_create: { label: "Workspace Created", color: "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400" },
  workspace_update: { label: "Workspace Updated", color: "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400" },
  trigger_create: { label: "Trigger Created", color: "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400" },
  trigger_update: { label: "Trigger Updated", color: "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400" },
  trigger_delete: { label: "Trigger Deleted", color: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400" },
  trigger_fire: { label: "Trigger Fired", color: "bg-orange-100 text-orange-800 dark:bg-orange-900/20 dark:text-orange-400" },
};

/**
 * Get label and color for an audit action.
 * Falls back to capitalize-cased raw string for unknown/future actions.
 */
export function getActionMeta(action: string) {
  if (ACTION_LABELS[action]) return ACTION_LABELS[action];
  // Graceful degradation: capitalize raw string
  const label = action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return { label, color: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400" };
}
