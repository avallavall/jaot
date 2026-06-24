# State Management

> React Context for global shared state (auth, guidance, theme) + Zustand for feature-local state (builder). All providers live in `providers.tsx`.

## Provider stack

```mermaid
flowchart TB
    Layout["[locale]/layout.tsx<br/>NextIntlClientProvider"]
    Layout --> Fallback["FallbackProvider (translations)"]
    Fallback --> Providers["providers.tsx"]

    Providers --> Theme["ThemeProvider (next-themes)<br/>light / dark"]
    Theme --> Auth["AuthProvider<br/>user, org, workspace, plan"]
    Auth --> Guidance["GuidanceProvider<br/>onboarding state"]
    Guidance --> Wizard["WelcomeWizard (modal)"]
    Guidance --> Tooltip["TooltipSingletonProvider"]

    Providers --> Banner["MaintenanceBanner (503 listener)"]
```

## Context UML

```mermaid
classDiagram
    class AuthContext {
        +user: User
        +organization: Organization
        +isAuthenticated: bool
        +isLoading: bool
        +planLimits: PlanLimits
        +activeWorkspaceId: string
        +activeWorkspaceName: string
        +workspaceRole: WorkspaceRole
        +isOwner: bool
        +login(apiKey) Promise
        +loginWithEmail(email, pass) Promise
        +logout() void
        +setActiveWorkspace(id) Promise
    }

    class GuidanceContext {
        +skillLevel: SkillLevel
        +wizardStep: int
        +wizardDismissed: bool
        +wizardCompleted: bool
        +isLoading: bool
        +setSkillLevel(level) Promise
        +advanceWizard() Promise
        +dismissWizard() Promise
        +restartWizard() Promise
    }

    class User {
        +id: string
        +name: string
        +email: string
        +is_admin: bool
        +email_verified: bool
    }

    class Organization {
        +id: string
        +name: string
        +plan: string
        +credits_balance: number
    }

    AuthContext --> User
    AuthContext --> Organization
    AuthContext --> PlanLimits
```

## Consumption

| Context | Hook | Consumers |
|----------|------|--------------|
| AuthContext | `useAuth()` | `ProtectedRoute`, `workspace/*`, `admin/*`, `user/*`, headers |
| GuidanceContext | `useGuidance()` | `WelcomeWizard`, `SkillLevelSelector`, `EmptyState` |
| Theme | `useTheme()` | `LanguageSwitcher`, header, footer |
| Zustand builder | `useBuilderStore()` | `BuilderCanvas`, `PropertiesPanel`, `VersionModal` |

Derived hooks:
- `usePermission()` / `useWorkspacePermission()` — roles and permissions.
- `useSolvers()` — solver list cache.
- `useWebSocket()` / `useSSE()` — execution status streaming.

## Notes

- **Dual persistence (debt):** `AuthContext` stores the API key in `localStorage` **and** the JWT in a cookie. If the localStorage token expires before the cookie, the 401 is recovered via `refreshAccessToken()` (see [`03-api-client.md`](./03-api-client.md)).
- **Overlapping workspace context:** `activeWorkspaceId/Name/Role` live in `AuthContext`. A reasonable candidate for splitting into an independent `WorkspaceContext`.
- **Session:** validated on mount, no polling. An expired token is only noticed on the next request (and is auto-refreshed).
