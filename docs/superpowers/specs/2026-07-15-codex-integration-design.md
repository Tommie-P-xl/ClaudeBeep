# ClaudeBeep Codex Integration Design

## Summary

ClaudeBeep will add Codex notification support while preserving the existing
Claude Code notification and interactive-reply behavior. Claude Code and Codex
will be peer integrations with independent hook, event, and notification-channel
settings. Channel credentials and delivery implementations remain shared.

The release version for this work is `1.5.0`. Both `README.md` and
`README_CN.md` must be updated to describe the two integrations, configuration,
hook installation, notification behavior, and Codex interaction limitation.

## Goals

- Preserve all Claude Code v1.1.0 notification and interactive reply behavior.
- Add Codex notifications using the documented user-level hooks interface.
- Manage Claude Code and Codex as peer integrations.
- Let each integration independently enable hooks, events, and notification
  channels.
- Configure channel credentials once and share them between integrations.
- Keep Claude Code remote approval and reply support unchanged.
- Notify for Codex completion and attention-required events, while requiring
  approvals and answers to be completed inside Codex.
- Add no Codex runtime cost when Codex hooks are not installed or enabled, and
  no Claude interaction cost on the Codex notification path.
- Support equivalent management from the Web UI and Windows tray menu.

## Non-goals

- Remotely approve, deny, or answer Codex requests.
- Control Codex terminal input or undocumented internal state.
- Install project-level `.codex/hooks.json` files.
- Duplicate channel credentials, delivery clients, or long-running listeners
  for each integration.
- Redesign unrelated channel authentication or updater behavior.

## Official Codex Constraints

Codex discovers user hooks in `~/.codex/hooks.json` or inline in
`~/.codex/config.toml`. This design uses `~/.codex/hooks.json` so ClaudeBeep can
manage its own entries without editing unrelated TOML configuration.

Codex command hooks receive JSON on standard input. Supported lifecycle events
include `Stop`, `PermissionRequest`, `SessionStart`, `SubagentStart`,
`SubagentStop`, `PreCompact`, `PostCompact`, `PreToolUse`, `PostToolUse`, and
`UserPromptSubmit`. Non-managed hooks require review and trust in Codex. Codex
does not currently provide a Claude Code `Elicitation` equivalent that lets an
external hook return a user's answer or approval decision. Codex integration is
therefore notification-only.

Reference: <https://learn.chatgpt.com/docs/hooks>

## Architecture

Use a shared notification core with separate platform adapters:

```text
~/.claude/settings.json
  -> existing Claude hook entry
  -> Claude adapter
  -> Claude event/channel policy
  -> existing notification delivery
  -> existing interaction.py and listener.py when applicable

~/.codex/hooks.json
  -> Codex hook entry
  -> Codex adapter
  -> Codex event/channel policy
  -> existing notification delivery only
```

The shared core owns channel credential lookup, channel construction, delivery,
logging, and a small normalized notification event model. Platform adapters own
hook input parsing, event mapping, titles/messages, and hook output behavior.

The normalized event contains only notification data:

```python
NotificationEvent(
    platform="claude_code" | "codex",
    event_name="Stop",
    title="Codex - Complete",
    message="...",
    cwd="...",
    session_id="...",
)
```

Claude interaction remains outside the shared event model. The Codex adapter
must not import or call `interaction.py` or `listener.py`.

## Configuration Model

The canonical configuration has shared channel credentials and peer integration
settings:

```json
{
  "channels": {
    "windows_toast": {
      "duration_ms": 5000,
      "sound": "reminder"
    },
    "telegram": {
      "bot_token": "...",
      "chat_id": "..."
    }
  },
  "integrations": {
    "claude_code": {
      "enabled": true,
      "events": {
        "Stop": true,
        "Elicitation": true,
        "PermissionRequest": true
      },
      "channels": {
        "windows_toast": true,
        "weixin": false,
        "qq": false,
        "telegram": true,
        "feishu": false,
        "dingtalk": false
      },
      "interaction": {
        "enabled": true,
        "timeout_seconds": 0,
        "show_in_terminal": true
      }
    },
    "codex": {
      "enabled": false,
      "events": {
        "Stop": true,
        "PermissionRequest": true,
        "SessionStart": false,
        "SubagentStart": false,
        "SubagentStop": false,
        "PreCompact": false,
        "PostCompact": false,
        "PreToolUse": false,
        "PostToolUse": false,
        "UserPromptSubmit": false
      },
      "channels": {
        "windows_toast": true,
        "weixin": false,
        "qq": false,
        "telegram": false,
        "feishu": false,
        "dingtalk": false
      }
    }
  }
}
```

### Legacy Migration

- On first load, copy each legacy top-level channel `enabled` value to
  `integrations.claude_code.channels`.
- Copy the legacy top-level `interaction` settings to
  `integrations.claude_code.interaction` on migration, then maintain the legacy
  field as a compatibility mirror.
- Copy channel credentials and delivery parameters under `channels` on
  migration. Maintain the complete legacy top-level channel blocks as
  compatibility mirrors so downgrading to an older ClaudeBeep binary still
  preserves credentials and Claude channel state.
- Preserve unknown fields throughout loading and saving.
- Continue mirroring Claude channel and interaction settings to the legacy
  fields so an older ClaudeBeep binary can still read the configuration after a
  downgrade.
- New code treats `channels` and `integrations` as canonical after migration.
  If canonical and legacy mirrors disagree, canonical values win and the next
  successful save refreshes the mirrors.
- A missing `integrations.codex` configuration means Codex is disabled.

Configuration writes use a temporary file followed by atomic replacement. A
malformed existing file is never overwritten automatically.

## Hook Management

### Claude Code

- Continue using user-level `~/.claude/settings.json`.
- Preserve the existing `Stop`, `Elicitation`, and `PermissionRequest` behavior.
- Allow each event to be installed or removed independently.
- Preserve all unrelated user hooks and settings.
- Replace broad substring cleanup with a stable ClaudeBeep command marker while
  retaining a narrowly tested migration path for hooks installed by older
  ClaudeBeep releases.

### Codex

- Use user-level `~/.codex/hooks.json`.
- Preserve unrelated hooks and unknown fields.
- Identify owned commands with a stable `--platform codex` marker and the
  ClaudeBeep entry path.
- Install only enabled events and remove an event hook when that event is
  disabled.
- Report whether ClaudeBeep hook entries are configured. Codex does not expose
  persisted hook trust state through this JSON file, so ClaudeBeep must not
  claim that a hook is trusted or active. Show the required `/hooks`
  trust-review instruction after installation and alongside configured status.
- Use the documented Windows command override where required.
- Uninstall only ClaudeBeep-owned Codex handlers.

Hook configuration writes use atomic replacement. Invalid JSON produces an
actionable error and leaves the original file unchanged.

## Event Behavior

### Claude Code Defaults

| Event | Default | Behavior |
|---|---:|---|
| `Stop` | On | Existing completion notification |
| `Elicitation` | On | Existing remote and terminal reply workflow |
| `PermissionRequest` | On | Existing remote and terminal approval workflow |

Claude hook parsing, auto-approval filtering, option extraction, response file
coordination, listener competition, response JSON, and timeout behavior must
remain compatible with v1.1.0.

### Codex Defaults

| Event | Default | Behavior |
|---|---:|---|
| `Stop` | On | Completion notification |
| `PermissionRequest` | On | Attention/permission notification |
| `SessionStart` | Off | Optional lifecycle notification |
| `SubagentStart` | Off | Optional lifecycle notification |
| `SubagentStop` | Off | Optional lifecycle notification |
| `PreCompact` | Off | Optional lifecycle notification |
| `PostCompact` | Off | Optional lifecycle notification |
| `PreToolUse` | Off | Optional high-frequency tool notification |
| `PostToolUse` | Off | Optional high-frequency tool notification |
| `UserPromptSubmit` | Off | Optional user-prompt submission notification |

Codex notifications state that approvals and answers must be completed in
Codex. `UserPromptSubmit` is not labeled as a Codex question event.

## Runtime and Performance Isolation

- If a platform's hooks are not installed, running that platform starts no
  ClaudeBeep hook process.
- Disabled events are removed from the platform hook file rather than filtered
  only after process startup.
- The Codex hook entry imports only its adapter and lazily imports enabled
  channel implementations.
- The Codex path never imports Claude interaction or listener modules.
- The Claude entry and hook output remain behavior-compatible.
- Notification failure is logged but does not block Codex.
- A channel failure does not stop delivery through other enabled channels.
- The tray process remains the only persistent ClaudeBeep process.

WeChat remains a special shared runtime dependency. Its keepalive starts when
either integration enables WeChat with valid credentials, and stops only when
both integrations disable it. There is exactly one keepalive instance.

## Web UI

The integration management screen uses the approved peer layout:

- A Claude Code panel and a Codex panel appear side by side on desktop and stack
  on narrow viewports.
- Each panel contains platform enablement, hook installation/status, event
  switches, and channel switches.
- Claude Code additionally contains interactive-reply settings.
- Codex clearly states that remote channels notify only and that action remains
  in Codex.
- Shared channel credentials live in a separate section and are configured
  once.
- API responses expose both integration states instead of a single global hook
  or channel state.

## Windows Tray Menu

The tray provides the same platform separation as the Web UI:

```text
Notification sources
  Claude Code
    Windows Toast / WeChat / QQ / Telegram / Feishu / DingTalk
  Codex
    Windows Toast / WeChat / QQ / Telegram / Feishu / DingTalk

Hooks
  Claude Code
    Stop / Elicitation / PermissionRequest / Uninstall all
  Codex
    Stop / PermissionRequest / optional events / Uninstall all
```

Channel checkmarks read from the selected integration. Channels without valid
credentials are disabled only within that platform submenu. Toggling a hook
event immediately synchronizes the corresponding platform hook file. Existing
install/uninstall-all capability remains available under each platform.

## API Design

Existing channel authentication endpoints remain shared. Integration-aware
endpoints replace ambiguous global state with an explicit platform resource
path. Current routes remain as compatibility shims for the v1.1.0 UI and CLI.

The new route surface is:

- `GET /api/integrations` returns both integration configurations and hook
  status.
- `PUT /api/integrations/<platform>` updates platform enabled state and
  platform-specific settings.
- `POST /api/integrations/<platform>/channels/<name>/toggle` changes one
  platform's channel selection.
- `POST /api/integrations/<platform>/hooks/sync` installs the enabled event set
  and removes disabled ClaudeBeep events.
- `POST /api/integrations/<platform>/hooks/uninstall` removes all
  ClaudeBeep-owned hooks for that platform.
- `POST /api/integrations/<platform>/test` tests only that platform's selected
  notification channels.

API operations must cover:

- Read both integration configurations and effective states.
- Toggle a platform.
- Toggle a platform event and synchronize its hook file.
- Toggle a channel for one platform.
- Install or uninstall all hooks for one platform.
- Report hook configuration status separately for Claude Code and Codex.
- Test notifications for one platform using that platform's channel selection.

## Error Handling and Safety

- Never replace malformed configuration or hook files automatically.
- Preserve unrelated hook entries and unknown JSON fields.
- Use exact ownership predicates for normal uninstall operations.
- Isolate exceptions per channel.
- Include platform, event, and channel in logs without exposing credentials.
- Keep Codex hook exit behavior non-blocking on notification or parse errors.
- Keep Claude response and timeout semantics unchanged.
- Do not create Claude pending/response files from Codex events.

## Testing Strategy

The repository currently has no automated test suite. This work adds focused
tests before behavior changes.

### Configuration Tests

- Migrate an unmodified v1.1.0 configuration without changing effective Claude
  behavior.
- Keep Claude Code and Codex event/channel matrices independent.
- Require credentials to be configured only once; generated legacy mirrors
  must match the canonical values.
- Preserve unknown fields.
- Reject malformed configuration without overwriting it.
- Maintain legacy Claude mirrors for downgrade compatibility.

### Hook Manager Tests

- Install and uninstall each Claude event independently.
- Preserve Claude v1.1.0 hook command behavior and response output.
- Install and uninstall each supported Codex event independently.
- Preserve third-party and unknown hooks in both files.
- Remove only ClaudeBeep-owned entries.
- Migrate legacy ClaudeBeep hook entries narrowly and safely.
- Reject malformed hook files without overwriting them.

### Runtime Tests

- Parse representative Claude and Codex event payloads.
- Confirm Codex titles and messages state the correct action boundary.
- Confirm Codex does not import `interaction.py` or `listener.py`.
- Confirm Claude does not execute the Codex adapter.
- Confirm channel failures do not stop other deliveries.
- Confirm per-platform channel selection.
- Confirm one WeChat keepalive when either or both platforms enable it.
- Confirm no keepalive when neither platform enables it.

### UI and Tray Tests

- Exercise integration-aware Flask endpoints.
- Verify Web UI state and effective configuration for both integrations.
- Verify tray menu checkmarks and disabled states for both platform submenus.
- Verify tray event toggles update only the corresponding hook file.

### Release Verification

- Run the complete automated test suite.
- Perform a v1.1.0 upgrade smoke test with Claude remote replies.
- Perform Codex `Stop` and `PermissionRequest` notification smoke tests.
- Verify Codex trust-review guidance after installation.
- Build the Windows executable and installer.
- Verify the application reports version `1.5.0` consistently.
- Review English and Chinese README instructions against the shipped UI.

## Acceptance Criteria

1. An existing v1.1.0 user retains working Claude Code notifications and remote
   interactive replies after upgrading.
2. Claude Code and Codex appear as peers in configuration, Web UI, and tray.
3. Each platform independently controls its enabled state, installed events,
   and selected notification channels.
4. Channel credentials are configured once and shared.
5. Codex completion and permission/attention notifications reach only its
   selected channels.
6. Codex approvals and answers remain inside Codex.
7. Installing or uninstalling one platform never changes the other platform's
   hook file.
8. Third-party hooks and unknown configuration fields are preserved.
9. Running only one platform incurs no hook process, listener, or interaction
   overhead from the other integration.
10. Web UI and tray display consistent effective state.
11. The release builds successfully as version `1.5.0` and both README files
    document the delivered behavior.
