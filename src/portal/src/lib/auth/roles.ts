/** Portal roles, lowest first. Mirrors kb/worker.py ROLE_RANK / REQUIRED_ROLE (the worker is the guard). */
export const ROLES = ["lector", "revisor", "editor"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_LABEL: Record<Role, string> = { lector: "Lector", revisor: "Revisor", editor: "Editor" };

export function hasRole(role: Role | null | undefined, needed: Role): boolean {
  return !!role && ROLES.indexOf(role) >= ROLES.indexOf(needed);
}

/** The role each portal action needs (same table as the worker). */
export const ACTION_ROLE = {
  decide_case: "revisor",
  set_value: "editor",
  split_generation: "editor",
  merge_generations: "editor",
  add_evolution_note: "editor",
  catalog_upsert: "editor",
  user_upsert: "editor",
  recalculate: "editor",
} as const satisfies Record<string, Role>;

export type ActionKind = keyof typeof ACTION_ROLE;
