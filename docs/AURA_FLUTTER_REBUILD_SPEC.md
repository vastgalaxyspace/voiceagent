# Aura: complete Kotlin-to-Flutter frontend rebuild specification

Prepared: 27 October 2026. Source baseline: the local Android source for Aura 1.4.0, version code 7.

## Contents

- [1. Purpose and scope](#1-purpose-and-scope)
- [2. Source map](#2-source-map)
- [3. Flutter structure and native audio boundary](#3-flutter-structure-and-native-audio-boundary)
- [4. Design system and shared layout](#4-design-system-and-shared-layout)
- [5. Navigation and back behavior](#5-navigation-and-back-behavior)
- [6. Login and registration: every control](#6-login-and-registration-every-control)
- [7. Home: every visible element and state](#7-home-every-visible-element-and-state)
- [8. Orb geometry and animation](#8-orb-geometry-and-animation)
- [9. History and conversation reports](#9-history-and-conversation-reports)
- [10. Settings and account](#10-settings-and-account)
- [11. Conversation preferences](#11-conversation-preferences)
- [12. Saved memories and every dialog/control](#12-saved-memories-and-every-dialogcontrol)
- [13. References: list, search, tools, editor and delete](#13-references-list-search-tools-editor-and-delete)
- [14. Source links](#14-source-links)
- [15. Usage page](#15-usage-page)
- [16. State and operation ownership](#16-state-and-operation-ownership)
- [17. HTTP contract](#17-http-contract)
- [18. WebSocket protocol: exact mobile behavior](#18-websocket-protocol-exact-mobile-behavior)
- [19. Conversation lifecycle](#19-conversation-lifecycle)
- [20. Native PCM, audio effects and Silero details](#20-native-pcm-audio-effects-and-silero-details)
- [21. Friendly errors and lesser-visible behavior](#21-friendly-errors-and-lesser-visible-behavior)
- [22. Migration caveats: preserve intentionally, do not invent behavior](#22-migration-caveats-preserve-intentionally-do-not-invent-behavior)
- [23. Implementation order and acceptance checklist](#23-implementation-order-and-acceptance-checklist)
- [24. Handoff instruction for a Flutter developer or coding agent](#24-handoff-instruction-for-a-flutter-developer-or-coding-agent)
- [25. Embedded source snapshot](#25-embedded-source-snapshot)

## 1. Purpose and scope

Build the same Aura application in Flutter using the existing Python backend. Match the current Kotlin application's screens, text, colors, controls, validation, navigation, HTTP operations, WebSocket protocol, voice behavior, and lifecycle handling. This is a build specification, not a completed Flutter application.

The source application is `D:\android developenment\Voiceagent`. The backend is `D:\Ai Service\voiceagent`. The source code appendix in this document makes the handoff self-contained: the recipient can inspect exact expressions and defaults without access to those folders. Source code takes precedence over historical README descriptions. In particular, version 1.4.0 uses explicit speech turns and communication audio routing; older notes about media routing and continuously sending silence do not describe its current hands-free behavior.

**Parity baseline:** Android. Flutter may also target iOS later, but this Kotlin project contains no iOS implementation to copy. iOS audio routes, permissions, echo processing and runtime integration require separate implementation and device validation.

**Legend:** “Current” describes inspected Kotlin/backend behavior. “Flutter implementation guidance” is a proposed way to reproduce it, not a feature already present. “Parity caveat” identifies behavior worth reviewing rather than silently changing during migration.

Do not add a chat transcript, text-message composer, social login, password reset, recording library, subscription purchase flow, admin dashboard, or new settings merely because they are common in other assistants. They are not visible features of this app. Keep Gemini credentials and database credentials on the backend.

## 2. Source map

| Source file | Responsibility to reproduce |
| --- | --- |
| `MainActivity.kt` | Edge-to-edge Android window, system icon appearance, volume-stream behavior, Compose entry |
| `ui/VoiceApp.kt` | Root routing, theme, header, error banner, bottom tabs, Home, orb, hold control, authentication, History, Settings, Account |
| `ui/FeatureScreens.kt` | Shared feature layout/cards, usage, memories and editor, references and editor, source links, reports, preferences |
| `ui/VoiceViewModel.kt` | Application state, auth, HTTP calls, conversation orchestration, loading states, cleanup, stale-request protection |
| `data/VoiceRepository.kt` | URL validation, bearer auth, HTTP transport, friendly errors |
| `data/LiveTransport.kt` | WebSocket connection, format negotiation, speech controls, heartbeats, reconnects, output suppression |
| `data/LiveAudio.kt` | Microphone, native audio routes/effects, playback, VAD worker, capture/playback epochs |
| `data/SpeechTurnGate.kt` | Frame-based speech confirmation, pre-roll, silence hangover, hold-to-talk bypass |
| `data/MicrophoneGate.kt` | Legacy helper still present; no longer used by current VoiceViewModel |

The XML `activity_main.xml` is a starter resource, not the current screen layout. The active frontend is Compose. The decorative orb is generated geometry, not an image asset.

## 3. Flutter structure and native audio boundary

Suggested organization, not existing Dart files:

```text
lib/
  main.dart
  app/aura_app.dart
  app/aura_theme.dart
  app/app_controller.dart
  app/app_state.dart
  data/voice_repository.dart
  data/live_transport.dart
  data/models/                 # typed API responses
  audio/native_audio_bridge.dart
  ui/common/feature_layout.dart
  ui/common/feature_card.dart
  ui/common/error_banner.dart
  ui/common/source_links.dart
  ui/common/aura_orb.dart
  ui/auth/login_page.dart
  ui/auth/register_page.dart
  ui/home/home_page.dart
  ui/home/hold_to_talk_control.dart
  ui/history/history_page.dart
  ui/history/report_page.dart
  ui/settings/settings_page.dart
  ui/settings/account_page.dart
  ui/settings/preferences_page.dart
  ui/memory/memory_page.dart
  ui/memory/memory_editor.dart
  ui/knowledge/knowledge_page.dart
  ui/knowledge/knowledge_editor.dart
  ui/usage/usage_page.dart
android/.../audio/             # native capture, playback, Silero and gate
```

Use one shared application controller so changing pages does not recreate the socket or microphone. State-management package choice is open; match behavior rather than introducing a dependency solely for parity.

**Recommended Android audio approach:** retain/adapt the existing Kotlin audio engine behind a Flutter plugin or platform channel. Rebuild UI, application state and networking in Dart, but keep Android AudioRecord, AudioTrack, acoustic echo cancellation, noise suppression, routing and Silero close to the device. The Gradle artifact `com.github.gkonovalov.android-vad:silero:2.0.10` is an Android dependency, not a Dart package.

Flutter supports asynchronous calls to native code through platform channels. A proposed bridge can expose commands such as initialize/resume/pause/close, enqueue output, clear output, set hold mode, set held state, mute, and enable capture after greeting. Emit ordered speech-start/audio/speech-end events plus status, level and failure events. Use one ordered event stream for input audio and its boundaries; separate asynchronous streams must not reorder start and PCM. Include a capture generation so Dart can reject stale events. Keep inference and blocking audio reads/writes off the UI thread. See [Flutter platform channels](https://docs.flutter.dev/platform-integration/platform-channels) and [official channel examples](https://github.com/flutter/samples/blob/main/platform_channels/README.md).

Do not substitute speech-to-text followed by text-to-speech: the current app is a bidirectional raw-audio Gemini conversation through the backend. Do not run another independent VAD in Dart if the native engine already owns speech boundaries.

## 4. Design system and shared layout

Use dark Material 3 regardless of system light/dark appearance. No theme toggle exists. Use system-default typography; no custom font file is loaded. Translate Compose dp to Flutter logical pixels, and preserve accessibility text scaling rather than fixing physical pixels.

| Token | ARGB / role |
| --- | --- |
| Ink | `0xFF0C0E18`: page background, dark text on light buttons |
| Panel | `0xFF181B29`: cards and inactive hold surface |
| Muted | `0xFFB1B6CB`: supporting copy and inactive navigation |
| Lilac | `0xFFC6B8FF`: primary action, selected navigation, accents |
| Cyan | `0xFF88E2DF`: active status and held microphone surface |
| Line | `0xFF34394D`: card borders |
| White | `0xFFF5F3FF`: primary text |
| Primary container | `0xFF34304F` |
| Surface container high/highest | `0xFF252939` |
| Outline | `0xFF737B96` |
| Error/on-error | `0xFFFFB4BD` / `0xFF420D18` |
| Bottom selection indicator | `0xFF28243F` |
| Error banner background/text | `0xFF3D202D` / `0xFFFFD6DB` |

Root layout: full screen dark surface → safe drawing insets → optional main header → optional error banner → expanded page content → optional bottom navigation. Match white foreground across nested cards/fields, not only the root title. Android uses transparent edge-to-edge system bars with light icons. Native startup/window XML uses `#080A12`; the rendered Compose page uses Ink.

### 4.1 Main header

Visible on **Home, History and Settings only**. Full-width row; horizontal padding 24, vertical padding 16; centered vertically. Left outlined GraphicEq icon, 28 square, Lilac; gap 10; lowercase `aura`, 26, semibold, White. Flexible spacer. Right icon button: PersonOutline, accessible label **Your account**, White. Opens Account. Neither wordmark nor left icon is clickable.

### 4.2 Bottom navigation

Visible only on Home/History/Settings. Background Ink, zero tonal elevation. Three items in order:

| Label | Icon | Tap |
| --- | --- | --- |
| Home | GraphicEq | Show Home |
| History | History | Show History and refresh first history page, including when already selected |
| Settings | Tune | Show Settings |

Selected icon/text Lilac, other icon/text Muted; rounded indicator `#28243F`. Preserve labels. These taps are not disabled during a conversation. Leaving Home releases a held microphone control; it does not by itself stop a hands-free conversation while the app remains foregrounded.

### 4.3 Global error banner

Shown above page content whenever `error != null`, on authentication and feature pages too. Horizontal margin 20, vertical margin 6, corner radius 14. Text 13; internal left padding 14 and text vertical padding 12. Text expands; trailing Close icon button with accessibility label **Dismiss message** clears the error only. No automatic timeout, retry button, modal blocking, or navigation is attached. Starting a `work` operation clears the previous error.

### 4.4 Feature page shell

Used by Account, Preferences, Usage, Memory/list/editor, References/list/editor, Report. Full-height vertically scrolling column with keyboard-aware bottom inset. Horizontal padding 26, bottom padding 24, spacing 15. First row: auto-mirrored outlined ArrowBack button, semantic label **Back**, then title 25 medium. Subtitle appears only when nonblank, 12 Muted, line height 19. No main header/bottom tabs on these pages. Back discards editor-local unsaved changes without a confirmation dialog.

Feature cards: full width, Panel, White content, radius 18, 1-unit Line border, padding 18, inner vertical spacing 10. Unspecified Material control colors, corner sizes and hit targets are Material 3 defaults; calibrate Flutter defaults visually instead of inventing exact measured values.

## 5. Navigation and back behavior

Initial route is Login because the token is not persisted. After authentication `signedIn` changes to true and Home is selected; sign-out selects Login. Route state is saveable in the Kotlin UI, but process recreation does not restore a bearer session.

| Page | Header/tab bars | Back destination |
| --- | --- | --- |
| Login | Neither | Default Android system behavior |
| Register | Neither | Login |
| Home | Both | Default system behavior; backgrounding ends active session |
| History | Both | Home |
| Settings | Both | Home |
| Account | Neither | Settings, even when opened from Home header |
| Preferences | Neither | Settings |
| Memory list | Neither | Settings |
| Memory editor | Neither | Memory list |
| Knowledge/reference list | Neither | Settings |
| Knowledge/reference editor | Neither | Reference list |
| Usage | Neither | Settings |
| Report | Neither | History |

Editors are nested full pages, not bottom sheets. Delete confirmations are AlertDialogs. Cancelling/dismissing a delete dialog changes no server data. Source links use an external URI handler and may background the app, which can end an active conversation under the current lifecycle policy.

## 6. Login and registration: every control

Layout: scrollable, keyboard-aware, horizontal padding 28, vertical padding 36, element spacing 18. GraphicEq icon 42 Lilac; `aura` 29 semibold; extra spacer 18 before heading; heading 30 medium; supporting copy 14 Muted. Fields full width, outlined.

| Element | Login | Register |
| --- | --- | --- |
| Heading | Welcome back | Create your account |
| Supporting text | Sign in to your space. We're glad you're here. | A little space to think, speak and grow. |
| URL label | Backend URL (ngrok) | Same |
| URL placeholder | https://your-tunnel.ngrok-free.dev | Same |
| URL supporting copy | Paste your HTTPS ngrok URL only, without /docs. This address is remembered on this device. | Same |
| Email | Email keyboard; single line | Same |
| Password | Masked; password keyboard; single line | Same |
| Password support | Enter your account password | 4 to 8 characters |
| Confirm password | Absent | Masked single-line field; error border when nonempty and unequal |
| Primary action | Sign in | Create account |
| Alternate action | New to Aura? Create an account | Already have an account? Sign in |
| Footer | Absent | If signup is disabled on your server, use an account provided by its administrator. |

Primary button: full width, height 56, radius 18, label 16. While busy, replace label with 20-square circular spinner, Ink, stroke 2. Alternate action is a centered TextButton disabled while busy. Switching Login/Register clears global error.

**Enable primary action only when:** not busy; backend origin valid; email contains `@`; password nonempty and at most 128 characters; for registration password length additionally 4–8 and confirmation equals password. Frontend email validation is deliberately minimal; backend applies actual email validation and normalizes case. Do not apply registration's eight-character maximum to login. No show-password eye, forgot-password link, remember-me checkbox, OAuth button or submit-on-keyboard action is defined.

The URL field is disabled while busy; email/password/confirmation fields are not explicitly disabled. Email and URL use saveable local state. Password and confirmation are transient, not persisted; clear on successful authentication. There is no text-length input rejection on password fields, only submit validation.

### 6.1 Backend URL behavior

- Initial value: saved `backend_connection` / `backend_url` preference, otherwise current repository base URL, otherwise empty. Never hardcode an ngrok tunnel.
- On each edit, persist the normalized origin if valid. Invalid edits remain visible but do not replace the last valid saved value.
- Trim surrounding whitespace; require parsed HTTP(S) origin with root path only. Reject user/password, `@` authority credentials, query, fragment, `/docs`, `/api`, or other non-root paths.
- Remote origin must be HTTPS. HTTP is allowed only for `localhost`, `127.0.0.1`, or `::1`; the debug Android manifest permits cleartext, release does not enable it.
- Remove trailing slash for stored repository origin. A nonblank invalid URL shows field error styling; blank is not styled as error but blocks submission.
- Exact validation errors: “Enter only the backend URL, for example https://your-tunnel.ngrok-free.dev (without /docs).” and “Use HTTPS for an ngrok or remote backend. HTTP is allowed only for localhost.”
- Changing origin clears the old token. HTTP and WebSocket must use the same origin. Ngrok hosts ending `.ngrok-free.dev` or `.ngrok-free.app` receive `ngrok-skip-browser-warning: true`, including the handshake.

### 6.2 Authentication sequence

Configure origin; terminate previous local transport; clear token and personal caches; increment account generation. Register, if requested, by POSTing credentials to `/api/v1/auth/register`; then always login through `/api/v1/auth/login`. Trim email, not password. Store returned `access_token` only in memory. Fetch `/api/v1/users/me/preferences`, apply state, open Home and refresh History and Usage. No refresh-token flow or persisted auto-login exists. A failed preference fetch after successful login is a partial-authentication caveat in the original; a migration must handle this intentionally rather than assume auth is one atomic network request.

## 7. Home: every visible element and state

Scrollable full-height column, horizontal padding 28, vertical 20, horizontally centered.

1. Title 29 medium White: `Your space to talk.` if display name blank; otherwise `Hello, {displayName}.` Centered.
2. Subtitle after 12 units, 14 Muted: inactive `A clear mind starts with a conversation.`; active `Take your time. Aura is here.`
3. Spacer 20; orb canvas 250 × 250.
4. Status after 12 units, 14: inactive always `Ready when you are` in Muted; active controller status in Cyan.
5. Timer only when active, after 8 units, 12 Muted: elapsed seconds formatted minimum two-digit minutes and seconds (`00:00`). Timer starts after conversation creation/socket start, not after the first spoken response. It continues through reconnection.
6. Spacer 28; full-width Hold to talk row.
7. Conditional hold control; spacer 12 after it.
8. Full-width primary conversation button.
9. Conditional microphone pause/resume text button, top padding 6.
10. Centered footer 12 Muted, top padding 18.
11. Source links if sources exist.

| Control | Visibility / enable rule | Action / exact copy |
| --- | --- | --- |
| Hold to talk switch | Always visible on Home; enabled unless stopping | OFF by default; changes mode and releases any hold |
| Switch title | Always | Hold to talk, 14 White |
| Switch subtitle | Always, 12 Muted | OFF: Hands-free: speak to interrupt; ON: Background sound is blocked while released |
| Start talking | Inactive; enabled only `!busy && !stopping` | Request microphone permission, then create conversation; Mic icon 23 |
| Finish conversation | Active; same enable rule | Stop audio immediately and request session finish; StopCircle icon 23 |
| Main action busy state | Busy or stopping | Label/icon replaced by 21-square Ink spinner, stroke 2 |
| Pause microphone | Active, not stopping, not muted | End current input turn, mute capture upload, zero level; connection remains alive |
| Resume microphone | Active, not stopping, muted | Unmute and discard pre-mute capture state |
| Idle footer | Inactive | Tap once. Connect. Aura says hello first. |
| Active footer | Active | Your conversation stays here until you finish. |

Main button: height 60, radius 22, Lilac background, Ink foreground; label 16 semibold, gap 10 after icon. Pause/resume label 13 Lilac. There is **no visible speaker toggle**, separate end-call icon, live remaining-allowance badge, suggestion chips, transcript, keyboard button, or voice-selection control. The controller still has speaker/level/remaining state; that does not mean these are visible widgets.

### 7.1 Hold-to-talk control

Visible only when active AND hold mode enabled AND not stopping. Enabled for input when microphoneReady AND not muted. Full width, minimum height 56, radius 18, 1-unit border. Inactive surface Panel/White/Line; held surface Cyan/Ink/Cyan. Text centered, padding 18.

- Disabled label: `Microphone paused` (also used while greeting capture is unavailable).
- Enabled/released label: `Hold to talk`.
- Held label: `Listening — release when finished`.
- Supporting copy: `Hold while speaking. With a screen reader, activate to start, then activate again to finish.`; 12 Muted, top padding 6.
- Pointer down starts held state immediately. Pointer release or cancellation releases it in a finally-style cleanup; do not implement as a delayed long-press gesture.
- Accessible role Button with merged child semantics. Accessible click label alternates `Start microphone` / `Stop microphone`; activation toggles held state rather than requiring a press-and-hold.
- Actual controller eligibility additionally requires active, hold mode, microphoneReady, not stopping, not muted and foreground.
- Release when leaving Home, backgrounding, muting, changing mode, reconnecting, or cleaning up. Hold mode itself remains a controller preference across conversations in the same process; it is not persisted to disk.

### 7.2 Microphone permission

Request Android RECORD_AUDIO when Start talking is tapped. If denied show: `Allow microphone access in Android settings to start a conversation.` No automatic settings deep link is currently provided. Permission grant calls start; source-level guards prevent starts while busy, active, stopping or not foreground. Flutter lifecycle handling must not confuse the temporary permission dialog with a running conversation going to the background.

## 8. Orb geometry and animation

Use a custom painter and transform; no raster replacement is necessary. [Flutter CustomPainter](https://api.flutter.dev/flutter/rendering/CustomPainter-class.html) provides custom canvas painting. Cache geometry/gradients and isolate repainting; the source only rotates the drawn layer while active.

- Center `c=(width/2,height/2)`; radius `r=min(width,height)*0.36` (90 on a 250 canvas).
- Glow: radial gradient centered at c, radius `1.5*r`, purple `#54399D` at alpha 0.3 to transparent. Draw glow circle radius `1.5*r`.
- Body: radial gradient colors `#29396D`, `#16162F`, `#090C1B`; gradient center `(cx-0.35r,cy-0.35r)` and radius `1.55r`; body circle radius r.
- Edge: sweep gradient `#8FE4EF`, `#4A4493`, `#AA86EF`, `#8FE4EF`; circle stroke 1.2 logical units.
- Four closed ribbon paths, band 0 through 3. Each samples steps 0 through 72 inclusive. Let `a=(step/72)*2*pi`; `x=cos(a)*r*0.94`; `y=sin(a)*r*(0.28+band*0.12)+sin(2*a+band)*r*0.08`; rotate these coordinates by `band*0.8` radians around c.
- Ribbons use sweep gradient transparent → `#9380F2` alpha 0.65 → `#8CE5F1` alpha 0.65 → transparent. Stroke width `0.035r`.
- Draw order: glow, body, four ribbons, edge.
- Idle: rotation zero, no ticking animation. Active: continuous linear 0–360° rotation over 24 seconds, including Connecting/Reconnecting because the condition is `active`.
- No sound-level pulse: although microphone level is calculated, current orb does not read it.

## 9. History and conversation reports

### 9.1 History

Lazy list, padding 24, item spacing 14. Title `Your conversations`, 28 medium White; subtitle `Come back to the moments that mattered.`, 13 Muted. Empty text: `Your first conversation is waiting. Start talking from Home.`, vertical padding 42. There is no separate loading spinner or pull-to-refresh in the source; an initially empty list may show this text before the request completes.

Each whole history card is clickable, Panel, radius 20, border 1 Line, padding 20, inner spacing 9:

- Goal from `preferences_snapshot.goal`, or `A conversation with Aura` if blank: 16 White, maximum two lines, ellipsis.
- Date: first 16 characters of `created_at`, replace `T` with a space; 12 Muted. **Current history date is not converted to local time.** Usage reset time is converted separately.
- Status: capitalize first character; 12 Cyan.
- Tap fetches the conversation report, then navigates to Report on success. Errors stay in the global banner. Card itself is not disabled while busy, but the controller's `work` guard ignores duplicate work.
- `Load more conversations` TextButton appears only when `next_offset != null`. Page size 20; append and deduplicate by ID. Re-tapping History fetches the first page.

No delete conversation, search, rename, transcript playback, or individual recording download is provided.

### 9.2 Report

Feature title `Conversation details`, blank subtitle. Back → History. Inner spacing 14.

| Display | Source / condition |
| --- | --- |
| No report available yet. | Null report; Muted |
| Humanized reason, 17 Lilac | `end_reason`, underscores to spaces, capitalize first letter |
| Duration {Xm Ys} · {N} turns, 14 | `duration_seconds`, `turn_count` |
| {N} provider reconnects · {N} client reconnects | `provider_reconnect_count`, `client_reconnect_count`; 12 Muted |
| {N} tool calls · {N} reference results | `tool_call_count`, `knowledge_result_count`; 12 Muted |
| Estimated model cost: ${value} | Only when `usage_complete` true and estimated cost non-null |
| Model cost is unavailable or incomplete. | Otherwise |
| Partial observed estimate: ${value} | Only incomplete and `observed_model_cost_usd` non-null; 12 Muted |
| Estimates are not invoices. Connected voice time determines your allowance. | Always with report, 12 Muted |
| The server has not confirmed that this report was saved. | `persisted` false; 12 error color |

Duration formatter truncates seconds to integer then displays integer minutes and remainder seconds, with no zero-padding. Completing a session stores/refetches the report but **does not automatically navigate to Report**.

## 10. Settings and account

Settings: scroll column, padding 24, vertical spacing 14. Heading `Make it yours`, 28 medium White; subtitle `A conversation that feels like you.`, 13 Muted, bottom padding 10.

Every settings row is a full clickable surface, Panel, radius 18, 1 Line border, padding 18. Left title 16 White and subtitle 12 Muted separated by 7; trailing ChevronRight Lilac, decorative.

| Row title | Subtitle | Destination |
| --- | --- | --- |
| Your account | Signed-in email | Account |
| Conversation preferences | Language, response style and personalization | Preferences |
| Saved memories | Enabled if memory enabled; otherwise You choose what Aura remembers | Memory |
| Your references | Manage notes and optional reference tools | Knowledge |
| Voice time | Daily allowance and usage | Usage |

Account feature page title `Your account`; subtitle `Your own space for a conversation.` Email 18 White; `Signed in` 13 Cyan; full-width OutlinedButton `Sign out`, disabled while busy. Sign out first closes audio and requests active session stop, then POSTs logout, clears token/caches, invalidates stale requests and returns to Login. No account deletion, password change, avatar upload or email edit.

## 11. Conversation preferences

Feature title `Conversation preferences`, blank subtitle. Editor initializes local values from controller when opened. Inner spacing 12. `Changes apply to new conversations.` at 12 Muted.

| Control | Values / limits | Behavior |
| --- | --- | --- |
| Display name | Max 80; no NUL; single line | Reject edits exceeding limit; optional |
| LANGUAGE label | 10 Lilac, letter spacing 2 | Section label |
| Language radios | English; Hindi; English and Hindi | Entire row and radio clickable; mutually exclusive; labels 14 |
| Response detail chips | Brief → `brief`; Detailed → `detailed` | Mutually exclusive; horizontal gap 10 |
| CONVERSATION MODE label | 10 Lilac, letter spacing 2 | Section label |
| Mode radios | Everyday conversation → `general`; English practice → `english_practice`; Interview practice → `interview_practice` | Entire row and radio clickable |
| Conversation focus | Max 500; no NUL | Counter `{length}/500`; optional |
| How should Aura respond? | Max 1000; no NUL | Counter `{length}/1000 · Saved with your profile`; optional |
| Save preferences | Full width, height 52, radius 15 | Enabled signedIn and not busy; `Saving…` while busy |

Save PATCHes language, response_detail, goal, display_name, custom_instructions, conversation_mode; apply returned preferences and navigate back on success. Preserve editor on failure. Text fields/radios are not individually disabled while busy. If unsigned show `Sign in from your profile to save preferences.` No explicit Cancel button beyond Back. Memory consent uses the same preferences API but is on the Memories screen, not this editor.

## 12. Saved memories and every dialog/control

Feature title `Saved memories`. Subtitle: `You choose what Aura remembers. Saved facts can be sent to the voice provider when memory is enabled. No facts are extracted automatically from your voice.` Load memories on entering list; returning from editor can refresh again.

Consent card: label `Use saved memories`; secondary 11 Muted `On for new conversations` when enabled or `Off · saved facts are retained` otherwise. Switch disabled while busy. Toggle PATCHes `memory_enabled` and waits for returned preferences; do not invent optimistic persistent state. Note 11 Muted, line height 17: `Editing memories or changing consent ends affected active conversations. Deletion removes live facts, but cannot retract them from the provider or database backups.`

Next row: `{count}/{limit} saved facts`, 12 Muted, and **Add fact**. Add enabled only memoryEnabled AND not busy AND count < limit (initial limit 20, then server value). Add opens blank editor. Empty copy: `No saved facts yet. You can add a learning goal, preferred style, or useful background.`

Each fact card shows key with underscores replaced by spaces (14 Lilac), full content (14, line height 21), and `Priority {priority} · Version {version}` (10 Muted). **Edit** enabled memoryEnabled AND not busy; opens populated editor. **Delete** enabled not busy even when memory is disabled; opens confirmation. Bottom **Refresh** enabled not busy. **Delete all facts**, error-colored, appears only if list nonempty and is enabled not busy.

Delete dialog title: `Delete this fact?` or `Delete all saved facts?`. Body: `This removes the saved fact from your account. Affected live conversations will end.` / plural `facts`. **Delete** confirmation disabled busy; call individual DELETE or collection DELETE, reload list, close only on success. **Cancel**, outside dismissal and back dismissal clear dialog state. Cancel is not explicitly disabled busy; an already sent deletion cannot be undone by closing the dialog.

### 12.1 Memory editor

Full feature page title `Saved fact`; inner heading `A fact to remember` for new / `Edit saved fact` for existing, 25. Inner spacing 12.

- **Key, e.g. learning_goal**: single-line full-width outline field; max 64; enabled only creating. Supporting copy: `Lowercase letters, digits, underscores; start with a letter.` Save regex `^[a-z][a-z0-9_]{0,63}$`.
- **Saved fact**: full-width multiline outline field; max 500, no NUL; counter `{length}/500`; must be nonblank.
- **Priority: {integer}**: 12 Muted; Slider continuous range 0–100, initial 50 or existing priority. Display and submit truncate float to int. No discrete steps specified.
- Copy: `Higher priority facts are considered first. The server selects a bounded set for each conversation.`; 11 Muted.
- **Save fact** / **Saving…**: full-width Button. Enabled not busy AND memoryEnabled AND key valid AND content nonblank.
- Create body: key, trimmed content, integer priority. Update body: trimmed content, priority, expected_version; do not resend immutable key. Reload memories then close editor on success. Conflict remains visible via error banner; no silent overwrite.

## 13. References: list, search, tools, editor and delete

Feature title `Your references`. Subtitle: `Keep useful notes for conversations. Search includes your private references and published shared references; it does not search the internet.` Fetch own references on entry.

| Control | Rules / action |
| --- | --- |
| Use reference tools switch | Checked from `useTools`, default false; disabled while active; changes local next-conversation option, not a saved profile field |
| Switch support | Optional · next conversation only, 11 Muted |
| Tools explanation | Requires tools enabled on your backend. Selected reference text reaches the voice provider. Changes end affected tool-enabled conversations. |
| Search references field | Single line, max 200 characters; support Up to 8 words |
| Search outlined button | Enabled not busy, nonblank query, at most 8 whitespace-separated words; trim and URL-encode; limit 5 results |
| My references text button | Enabled not busy; clear query and reload private first page; leaves search mode |
| Add reference button | Enabled not busy; clear selected item, open blank editor |
| List heading | Search results if searchResults non-null, else Your private references ({loaded count}); 12 Lilac |
| Empty copy | No references found. Add a note or try a different search. |
| Open reference | Per item, enabled not busy; GET full item before opening editor |
| Delete | Per item only in private-list mode; not displayed in search results, even for own search hit; disabled busy |
| Load more references | Only private mode and next_offset non-null; disabled busy; page size 50, append deduplicating by ID |

Search and My references sit in a row with gap 8. Cards show title 16, optional excerpt 12 Muted, then buttons. No auto-search as you type. Search result summary is not sufficient to edit: fetch full entry to discover owner_id, content and version.

Delete dialog: title `Delete reference?`; body `{title} will be removed. Affected live conversations will end.` Confirm **Delete** disabled busy, sends individual DELETE, reloads private list and closes on success. **Cancel** and dismissal close dialog without sending. No delete-all-reference control.

### 13.1 Reference editor and shared read-only view

Feature title `Reference`, blank subtitle; heading 25: new `Add a reference`, own `Edit reference`, shared `Shared reference`. Shared means a loaded item whose `owner_id` is JSON null.

| Field | Rules |
| --- | --- |
| Title | Full width; max 120; no NUL; nonblank for save |
| Reference notes | Full width; max 6000; no NUL; min 4 and max 10 visible lines; `{length}/6000`; nonblank for save |
| Source URL (optional) | Max 1000; blank allowed; otherwise trimmed HTTP(S), host present, no user-info credentials; error style if invalid |

All three fields are read-only for shared references, rather than hidden. Explain: `Source URLs are metadata; the backend does not fetch or verify their contents.` at 11 Muted. Shared entries show SourceLinks and have no Save button. Own/new entries show full-width **Save reference** / **Saving…**, enabled not busy, valid URL, title and content nonblank. Submit trimmed title/content/url; add expected_version for updates. Success reloads private list and closes editor. Back discards unsaved local edits with no confirmation.

## 14. Source links

Used on Home after live knowledge retrieval and in shared reference view. Full-width column, vertical padding 8. Heading `References returned to Aura`, 10 Muted. Each source title is a TextButton (12) only when source_url parses as HTTP(S), has a host and no credentials. Tap delegates to external URI handling; launch exceptions are swallowed in current Kotlin. Unsafe/missing URL yields non-clickable Lilac title, 12, vertical padding 8. Do not fetch URL content automatically. Footer 10 Muted: `These references were retrieved for the assistant; they do not verify its answer.`

Live source arrays are merged and deduplicated by `id:version`. Sources clear at a fresh conversation start; they are not automatically cleared on finish, so they may remain visible on inactive Home until next start or account cleanup.

## 15. Usage page

Feature title `Your voice time`. Subtitle `Daily allowance is based on connected time. Reconnecting does not reset a session's limits.` Fetch on entry. While no usage exists display `Loading usage…` in Muted. Cached usage remains visible during refresh; no explicit refresh spinner.

First card:

- Available duration at 36 Lilac; `available today`, 13 Muted.
- Progress = clamp((connected_seconds + reserved_seconds) / max(daily_connected_seconds,1),0,1).
- `Used {duration} · Reserved {duration}`, 12 Muted.
- `Daily limit: {duration}`, 12.
- `Resets {localized date/time} (your local time)`, 12 Cyan. Source UTC reset becomes device-local medium date/short time; raw string is fallback if parsing fails.

Second card: `Usage details` 17; `{sessions_started} sessions started · {sessions_settled} settled` 12; `Model cost estimate: ${estimated_cost_usd}` 14; `An estimate, not a bill. {incomplete_cost_sessions} sessions have incomplete cost information.` 12 Muted; `Estimated spend guard enabled` or `Estimated spend guard disabled` 12 Muted.

**Refresh usage** outlined button is always present and has no busy disable guard. No purchase, allowance-edit or reset button. Frontend does not remove backend quotas; even when the hourly conversation-creation limit is disabled, daily connected time and other backend limits are independent.

## 16. State and operation ownership

Controller starts with signedIn/busy/stopping/active/muted/holdToTalk/talkHeld/microphoneReady/toolsActive/memoryEnabled/useTools false; speaker and foreground true; language `English and Hindi`; detail `brief`; mode `general`; name/instructions/goal/email/baseUrl empty; status `Ready when you are`; seconds/remaining/level zero; memoryLimit 20. Lists empty; nullable error, usage, report, selectedKnowledge, searchResults and offsets null.

Separate generations protect account operations, active conversation callbacks and report requests. Capture and playback each have their own invalidation epoch. Do not let a late response from an old account or old socket update the current UI.

`work` is a global guard: if busy, ignore another guarded operation; otherwise busy=true, clear error, await, show friendly failure, finally busy=false. Authentication, preference saves, conversation creation, report opening and memory/reference edits use it. History and usage refresh run independently. This explains why a global operation can turn the Home button into a spinner even when it is not connection work.

Data persistence: only valid backend origin is explicitly saved locally. Token stays memory-only. User preferences/memories/references/history are server-backed. Passwords, PCM, conversation checkpoints and tokens must not be placed in SharedPreferences by the Flutter port. The backend owns provider checkpoint secrets; the mobile app reattaches by conversation ID and its bearer token.

## 17. HTTP contract

Prefix all paths below with selected backend origin. Include `Authorization: Bearer <token>` after login. JSON request bodies use application/json. Connection timeout 10 seconds; read timeout 20 seconds. Do not follow HTTP or HTTPS redirects with authenticated requests. Empty successful responses must be accepted, including DELETE. Unknown response fields should not break the UI.

| Operation | Method/path | Body / response consumption |
| --- | --- | --- |
| Register | POST `/api/v1/auth/register` | email,password; then login |
| Login | POST `/api/v1/auth/login` | email,password → access_token; backend also returns token_type,expires_at |
| Logout | POST `/api/v1/auth/logout` | Empty JSON body |
| Load preferences | GET `/api/v1/users/me/preferences` | language,response_detail,goal,display_name,custom_instructions,conversation_mode,memory_enabled |
| Save preferences | PATCH same path | Only changed/edited supported keys; response is full preferences |
| Create conversation | POST `/api/v1/conversations` | goal,use_tools → id |
| Stop conversation | POST `/api/v1/conversations/{id}/stop` | Empty JSON; owner-scoped fallback in addition to socket stop |
| History | GET `/api/v1/conversations?limit=20&offset={offset}` | items,next_offset |
| Report | GET `/api/v1/conversations/{id}/report` | report fields in section 9 |
| Usage | GET `/api/v1/usage/me` | Usage fields in section 15 |
| List memories | GET `/api/v1/users/me/memories` | items,memory_enabled,limit |
| Create fact | POST same collection | key,content,priority |
| Update fact | PUT `/api/v1/users/me/memories/{id}` | content,priority,expected_version |
| Delete fact | DELETE individual path | No request body |
| Delete all facts | DELETE collection path | No request body |
| List references | GET `/api/v1/knowledge/entries?limit=50&offset={offset}` | items,next_offset |
| Search references | GET `/api/v1/knowledge/search?q={encodedQuery}&limit=5` | items with id,title,source_url,version,excerpt,offset |
| Open reference | GET `/api/v1/knowledge/entries/{id}` | Full object including owner_id,content,version |
| Create reference | POST reference collection | title,content,source_url |
| Update reference | PUT individual reference path | title,content,source_url,expected_version |
| Delete reference | DELETE individual reference path | No request body |

IDs are UUID strings. next_offset is nullable, not a boolean. Preserve expected_version exactly for optimistic updates. A memory contains id,key,content,priority,version,created_at,updated_at. A reference contains id,nullable owner_id,title,source_url,published,version,timestamps and content when loaded in full. Decimal costs may arrive as JSON strings: do not rely on only double casts. A conversation includes snapshots/status/timestamps; UI only uses selected fields.

On HTTP 401, clear the token only if it still equals the token captured for that request. This avoids an old failing request clearing a newer login. Controller failure handling then signs out and clears stale state if the current token is null.

## 18. WebSocket protocol: exact mobile behavior

Connect `/ws/live`; convert HTTPS→WSS or loopback HTTP→WS. Send bearer token as Authorization header, not query string. Flutter Android networking must support that handshake header. The backend accepts other authentication mechanisms for other clients, but this port should match mobile behavior.

After socket open, send text JSON:

```json
{"type":"start","conversation_id":"<existing-conversation-uuid>","speech_detection":"client"}
```

Do not upload audio until ready/resumed validates all of: protocol_version=3, speech_detection=client, input pcm_s16le/16000/1, output pcm_s16le/24000/1. Failure terminates with unsupported_audio_protocol. Server `ready` also supplies greeting_pending, remaining_seconds, reconnect_grace_seconds, heartbeat_interval_seconds, tools and other metadata. `resumed` uses the same validation and resets local speech-active state.

### 18.1 Client messages

| Message | Meaning |
| --- | --- |
| `{"type":"speech_start"}` | Begin confirmed user turn |
| Binary WebSocket frame | Raw signed little-endian PCM16 mono at 16 kHz, only within active turn |
| `{"type":"speech_end"}` | Finish turn after pause allowance or manual release |
| `{"type":"ping"}` | App heartbeat independent of mic activity |
| `{"type":"stop"}` | Finish conversation |

Never base64-wrap PCM or prepend WAV headers. Duplicate start/end requests are suppressed by transport. Backend rejects nonempty audio of odd byte length, packets over 3200 bytes, audio outside an active manual turn, and invalid repeated turn boundaries. Keep start and PCM in ordered send sequence. The legacy `audio_end` control is not used in client-VAD mode.

### 18.2 Server messages

| Event | Client effect |
| --- | --- |
| ready/resumed | Validate formats, enable streaming, reset reconnect budget, configure heartbeat, resume device audio; gate mic for greeting if needed |
| reconnecting | Stop uploads, reset local speech/suppression state, release hold, cancel greeting drain wait, pause/clear playback, show Reconnecting |
| interrupted | Clear queued/device playback, show Listening; do not release an actively held mic merely because Gemini acknowledged interruption |
| turn_complete | If greeting pending wait for output drain then enable mic; otherwise show Listening |
| knowledge_sources | Merge source objects by id/version |
| pong | Keeps connection alive; no visible UI |
| error | Show mapped error, finish transport, perform session cleanup |
| ended | Finish once, consume optional report, cleanup and refresh |
| Binary audio | 24 kHz PCM16 mono; play only for current streaming socket, not closed/stopping/suppressed |
| Unknown additive event | Ignore safely in UI |

Malformed JSON is fatal `invalid_server_message`. Do not render internal event names in the normal UI.

### 18.3 Heartbeats, buffers and reconnect timing

- Initial heartbeat interval 5000 ms; negotiated interval clamped 25–5000 ms.
- If no received traffic for more than max(3×interval,15000 ms), disconnect/retry.
- Send heartbeat only when outbound socket queued bytes <1024. Silence or mic pause must not stop heartbeats.
- Initial socket/ready watchdog 15000 ms. Recovery watchdog uses remaining grace deadline.
- Default reconnect grace 10000 ms, negotiated clamp 1–30000 ms.
- Retry waits 250,500,1000,1000… ms, bounded by remaining deadline; max 8 attempts. Exhaustion gives client_reconnect_exhausted.
- Reuse same conversation UUID and captured bearer token for every attempt. Never POST a new conversation to recover a socket.
- Ignore callbacks from replaced sockets. Reset deadline/attempts on successful ready/resumed.
- Do not retain/replay mic data from disconnected periods. Native capture can continue reading but drops unavailable frames.
- HTTP handshake 400/401/403/404 is fatal authentication_or_attachment_rejected; other socket failures follow retry path.
- If output upload queue >32000 bytes, fail input_backpressure instead of unbounded buffering.
- Stop cancels heartbeat/watchdog/retry. If stop JSON sends, wait up to 10000 ms for completion, otherwise finish immediately. Dispose cancels everything and the socket.

## 19. Conversation lifecycle

### 19.1 Start and greeting

Start requires signed in, foreground, not busy/active/stopping. Set active=true and status Connecting; reset elapsed/remaining, old report and sources. POST a conversation. If it finishes after generation changed or app backgrounded, immediately POST stop for the newly created ID and do not attach it. Otherwise create transport and timer, reset mic mute false, connect.

On ready, remaining time and available tools update. If greeting_pending true, status `Aura is saying hello`, capture upload disabled. Gemini greeting comes from backend/provider audio, not local TTS. On greeting turn_complete, wait until native playback queue, current packet and queued hardware frames drain, polling about every 25 ms with an 8-second maximum wait. Then invalidate prior input, enable mic, mark microphoneReady and show Listening. Do not repeat greeting on resume.

### 19.2 During conversation

Playback emits Speaking status at onset, not every packet. Confirmed local speech start immediately clears playback and shows Listening after start control was accepted. Transport suppresses received assistant audio while speechActive, and releases suppression when input ends. Actual playback activity—not the text label—is used for stricter VAD thresholds. `turn_complete` can show Listening while trailing playback still drains; preserve or explicitly review this cosmetic source behavior.

### 19.3 Finish and reports

Finish closes capture/playback immediately, releases hold, cancels greeting task and timer, sets stopping and Ending conversation, requests socket stop and HTTP stop. Remote finish performs cleanup once, clears active/stopping/toolsActive/currentId, disposes transport, stores provided report, sets internal status Conversation ended, then fetches final report. Home displays Ready when you are when inactive, so internal ended status is not visible there.

If final report absent, also attempt owner-scoped HTTP stop. Fetch report up to six times with 700 ms gaps when report_not_available; guard account/report generations. Other API failures surface, IO failure exits. Refresh History and Usage. Do not auto-open details.

### 19.4 Background and cleanup

Actual Android ON_STOP releases hold and stops an active conversation; no background listening service exists. Page navigation within the foreground app is different. Dispose releases recorder/track/effects/model, clears queues and restores previous communication route. Process death loses token and local attachment; backend timeouts/leases remain authoritative. Flutter lifecycle events need mapping to this policy rather than treating every transient inactive event as Android ON_STOP. See [Flutter AppLifecycleListener](https://api.flutter.dev/flutter/widgets/AppLifecycleListener-class.html).

## 20. Native PCM, audio effects and Silero details

### 20.1 Capture and playback

Capture: AudioRecord with VOICE_COMMUNICATION, 16000 Hz, one channel, PCM16; native buffer max(platform minimum,6400 bytes). Read into 1024-byte frames, accumulating partial reads. 1024 bytes = 512 samples = 32 ms. Frame data must be copied before worker reuses the buffer.

Optional AcousticEchoCanceler/NoiseSuppressor attached to recorder audioSessionId. Attempt enable when available. Unsupported effects do not prohibit talking. Log enabled state and route with `AuraAudio`, never PCM or user text.

AudioManager MODE_IN_COMMUNICATION. API31+: prefer available wired headset, wired headphones, USB headset, Bluetooth SCO or BLE headset; otherwise builtin speaker; call setCommunicationDevice. Older path uses speakerphone when neither wired nor SCO active. Save prior mode/speaker/device and restore on close. MODIFY_AUDIO_SETTINGS is declared. Hardware volume uses Android's default stream selection, not a permanently forced media stream.

Playback: AudioTrack USAGE_VOICE_COMMUNICATION, CONTENT_TYPE_SPEECH, 24000 Hz mono PCM16; streaming buffer max(24000 bytes, platform minimum). Bounded queue 128 packets; poll 100 ms. Write at most 960 bytes per write (20 ms at 24 kHz). Track cumulative written sample frames and hardware playback head. Packet carries playback epoch; interrupted/cleared packets are stale and must not be played. Clear means increment playback epoch, empty queue, reset frame count, pause/flush/play native output.

Errors: `Microphone or audio output unavailable.` on setup failure; `Speech detection or microphone failed. Please reconnect.` on capture/VAD failure; `Audio playback fell behind. Please reconnect.` when bounded playback queue full. These surface then stop session.

### 20.2 VAD and turn gate

Android Gradle dependency `com.github.gkonovalov.android-vad:silero:2.0.10`, scoped JitPack repository. Model and ONNX runtime are packaged in APK. One worker owns model/gate state; release model when capture stops or epoch changes. A new epoch clears partial frame and pre-roll so previously recorded audio cannot leak into a new turn after mute/reconnect/mode changes.

| Setting | Current value |
| --- | --- |
| Sample rate/frame | 16 kHz / 512 samples / 32 ms |
| Idle detector mode | NORMAL |
| Assistant-playing mode | AGGRESSIVE |
| Idle confirmation | 3 consecutive positive frames = 96 ms |
| Playing confirmation | 6 consecutive positive frames = 192 ms |
| Pre-roll | Last 9 frames, max 288 ms, including confirmation frames |
| End silence | 24 negative frames = 768 ms |
| Pre-roll send packet | At most 3072 bytes to stay below server 3200-byte limit |

When not speaking, retain latest nine frames and count consecutive positives; any negative resets positive streak. On enough speech, emit Start then buffered audio chunks; clear pre-roll. During active speech send every frame including pauses; positive frames reset silence counter. After 24 silent frames emit final audio then End and reset turn state. This is not word recognition and does not specifically recognize “stop.”

Hold mode bypasses Silero: held=true allows input immediately; released means no mic packets. Release/mode/mute changes end current activity and invalidate capture. The old `MicrophoneGate.packet()` helper that replaces audio with silence is **unused** in this version; do not use it instead of SpeechTurnGate.

Microphone level calculation: normalize signed samples by 32768, RMS over 512 samples, multiply by five and clamp 0–1; report at most once per 100 ms. It is currently not drawn on Home. Do not confuse level with VAD confidence.

No claim of speaker identification: TV dialogue, nearby people and residual speaker echo may qualify as speech. Device AEC and real acoustic tuning remain necessary. No semantic acknowledgment filtering or keyword spotting is implemented locally.

## 21. Friendly errors and lesser-visible behavior

Use exact messages from VoiceRepository appendix. Main mappings:

| Code(s) | User-facing handling |
| --- | --- |
| invalid_start / unsupported_audio_protocol / speech_detection_mismatch | This app needs the updated voice backend. Restart your updated backend, then start a new conversation. |
| registration_disabled | This server uses provisioned accounts. Sign in with the account supplied by your administrator. |
| daily_allowance_exhausted | Today's voice allowance has been used. Check Usage for the reset time. |
| session_busy / user_session_active | A conversation is already active. End it before starting another. |
| tools_disabled | Knowledge tools are disabled on this server. Turn off reference tools to start an audio-only conversation. |
| missing_api_key | The server's Gemini API key is not configured. Configure it on the backend and restart the server before starting a voice conversation. |
| memory_version_conflict / knowledge_version_conflict | This item changed since you opened it. Refresh and reopen it before saving. |
| server_draining | The server is being updated. Please try again later. |
| authentication_required / invalid_token / session_expired | Your session has expired. Please sign in again. |
| report_not_available | The session report is still being finalized. Try again shortly. |
| Other HTTP 429 | Too many requests. Please wait [Retry-After seconds] and try again. |
| Other API code | Underscores to spaces, capitalize first character |
| Unclassified exception | Could not reach the backend. Check your connection and try again. |

Invalid successful JSON response: `The server returned an invalid response.` Unsuccessful non-JSON response maps server_unavailable. Repository called without an origin: `Enter your backend URL on the sign-in page first.` Errors do not automatically change pages except authentication loss. Preserve form contents on save failures.

## 22. Migration caveats: preserve intentionally, do not invent behavior

1. `speaker`, `level`, `remaining` and `toolsActive` exist in state but have no direct Home control/indicator in current UI.
2. `MicrophoneGate.kt` is a legacy file; current hold behavior uses explicit boundaries.
3. Original README sections describe older versions. Current source controls routing/VAD behavior.
4. History date is raw truncated server time; Usage reset is localized.
5. Home is active during connection setup, so orb rotates before audio readiness.
6. Idle Home hides internal Conversation ended status and final report; History is the way to open reports.
7. No persistent auth; saving the backend URL does not save login.
8. App background stops a conversation; opening a source externally may therefore end it.
9. No native live audio behavior has been proven merely by unit tests/build success.
10. Initial empty list and loading behavior is simple. Adding skeletons, refresh spinners or new retry actions is an enhancement, not strict parity.
11. Settings/Account routes do not use a conventional navigation history stack in every case; Back goes to explicit destinations.
12. Android AEC availability and selected route can differ per device. Do not promise silence/noise immunity.
13. Current Kotlin password policy is 4–8 only for new registration, with 1–128 login compatibility. Do not silently alter the backend policy as part of a frontend rewrite.
14. Some fields remain editable during busy requests; either match this or mark a deliberate UX deviation.

## 23. Implementation order and acceptance checklist

Suggested sequence: theme/shared shell → auth/origin setup → route tree and all CRUD pages → HTTP data mapping → WebSocket lifecycle → native audio bridge → speech gate integration → visual/device comparison. No backend API redesign is required for a faithful port of the current client.

### Visual and interaction acceptance

- [ ] Login and Register are separate pages with the exact fields, copy, password rules and switch links.
- [ ] Backend origin is remembered while token/passwords are not; invalid origin cannot be submitted.
- [ ] Main header/profile and all three bottom tabs match colors, padding and destinations.
- [ ] Global banner displays and dismisses without resetting unrelated state.
- [ ] Home title, subtitle, timer, status, button labels/spinners and footers change under the documented conditions.
- [ ] Orb matches geometry and only rotates while active; no invented volume pulse.
- [ ] Hold pointer-down/release/cancel and accessibility-toggle behaviors both work.
- [ ] Greeting keeps input unavailable until playback drains; short failures do not leave Connecting indefinitely.
- [ ] History empty/card/pagination/report behavior matches, including date formatting.
- [ ] All five Settings rows, Account logout and back destinations work.
- [ ] Preferences include every option, length limit, counter and correct JSON enum.
- [ ] Memory consent, quota, add/edit, immutable key, slider, individual/all-delete dialogs work.
- [ ] Reference search limits, private/search lists, read-only shared entries, source validation and delete dialog work.
- [ ] Usage displays available/used/reserved time, progress, local reset, cost and guard state.
- [ ] Reports show complete/partial/unavailable cost and persistence warning correctly.
- [ ] Keyboard does not cover submit controls; small screens scroll; large text remains operable.

### Functional acceptance

- [ ] No duplicate conversation creation on retry, no stale account/screen writes from old responses.
- [ ] HTTP redirects remain disabled, 401 clears only the matching current token, empty DELETE handled.
- [ ] Start handshake requests client speech detection; wrong formats/mode fail clearly.
- [ ] Speech start precedes buffered PCM; end follows final frame; no out-of-turn packets.
- [ ] Input and output sample rates/endianness match; playback is flushable mid-answer.
- [ ] Idle ping works with paused mic and silence; reconnect has bounded deadline/attempts.
- [ ] Old socket callbacks, recovery gap audio and old capture/playback epochs are discarded.
- [ ] Stop works while connected or detached, final report refresh is bounded, no auto-new session.
- [ ] Native effects/routes/resources clean up and restore when app stops or conversation ends.
- [ ] Physical-device comparison covers headphones, loudspeaker, keyboard clicks, quiet speech, short stop/wait, sentence pauses and TV speech.

These are handoff acceptance criteria, not Python test files. This documentation task does not change the running backend or build a Flutter application.

## 24. Handoff instruction for a Flutter developer or coding agent

> Rebuild Aura in Flutter using this document and its embedded source snapshot as the behavioral reference. Implement every described screen, control, validation and state transition against the existing backend. Preserve its authenticated HTTP and protocol-v3 client-VAD WebSocket contract. Use Flutter for UI/application state and a native Android audio bridge for the existing PCM/Silero/echo-cancellation pipeline unless an alternative is verified to provide the same controls. Do not mock live voice, add unsupported buttons or store credentials in the app. Keep Android parity first; label iOS work separately. Compare every acceptance item and report any intentional deviations explicitly.

## 25. Embedded source snapshot

The following appendices are generated directly from local source at handoff time. They include exact UI copy, all active Kotlin classes, the legacy helper clearly labeled, Android configuration/resources and client-facing backend schemas. They contain no `.env`, keystore, account token, password or Gemini key. SHA-256 values identify the exact bytes inspected. Kotlin/XML here are reference material to translate or adapt, not Dart code to paste directly.

<!-- GENERATED SOURCE SNAPSHOT -->

### 25.1 Source inventory and fingerprints

| Project | Relative source | SHA-256 |
| --- | --- | --- |
| Android | `app/src/main/java/com/example/voiceagent/data/LiveAudio.kt` | `c16d6898b2d021e48ce138db4876e0e7bcaef905a37302f6f7fc6720608705c6` |
| Android | `app/src/main/java/com/example/voiceagent/data/LiveTransport.kt` | `4c0f0ad7ae5cbf4fa725c49a13252e3c3414cdc9bbf9b47cd1de74807815269a` |
| Android | `app/src/main/java/com/example/voiceagent/data/MicrophoneGate.kt` | `5bf0c8dac441b249caa4dbf72b42b1000b0d92692f2981d9e6e23559f14519c7` |
| Android | `app/src/main/java/com/example/voiceagent/data/SpeechTurnGate.kt` | `7b3f3d0e9b7e546bb4ef714599df0421f6cab8870e3eca5bb3292248ea5eca94` |
| Android | `app/src/main/java/com/example/voiceagent/data/VoiceRepository.kt` | `5d3e0d45616aeb0ca6f02bfe7751cfdcf8201d8dcba852e8a24478b947747d11` |
| Android | `app/src/main/java/com/example/voiceagent/MainActivity.kt` | `bc272136c51f2296f40018c44823bf41e788a48dea0686fecff0d8a1274d7e60` |
| Android | `app/src/main/java/com/example/voiceagent/ui/FeatureScreens.kt` | `95c7d05517e205f14f5ff5e8bc8aa8639701f6261d614cee24ad614333f5f35c` |
| Android | `app/src/main/java/com/example/voiceagent/ui/VoiceApp.kt` | `ed5b76f0599593ada7e605c07e0b6466d6de3945fdb93bbec388cd4021c22ddb` |
| Android | `app/src/main/java/com/example/voiceagent/ui/VoiceViewModel.kt` | `b2956783e94f7b8e8505e5b299856a4dc2f72ffe33d39fe1e2953577d3631c1c` |
| Android | `app/src/main/AndroidManifest.xml` | `a1e74636a1b3d7938b183e96f1475a5a550815a53fcfc14d6af873b790363205` |
| Android | `app/src/debug/AndroidManifest.xml` | `53c01c7b40f6e1ba705b89674fe73988706e83acc06551723a480055d947afe5` |
| Android | `app/build.gradle.kts` | `1b3c3ac315fb9440bbceea45893677335a69da2911d0fec5bf6354643ab8e479` |
| Android | `build.gradle.kts` | `5dad2d59c54beb7d7801e06e1c795456d1bea58c0ccbeddfce159cd8f58c2fa8` |
| Android | `settings.gradle.kts` | `61230e0838b9acc2867bd0f93a5052f242b573ef1d0ab45a914cfc1086c316c5` |
| Android | `gradle/libs.versions.toml` | `a819c2a2be63f6ab3e8d34e038b401eaf930fa7ed7b4c3207a5ce9e7102eab1c` |
| Android | `app/src/main/res/drawable/ic_launcher_background.xml` | `ed423c73a6f40a4d2909f0901e60527b3a807cd59e1b5593bcaae1808b1c6321` |
| Android | `app/src/main/res/drawable/ic_launcher_foreground.xml` | `01d1a6a6c1234eb7fe270d097eb283d72b9c95ae5118886f1b6573aad280f1f7` |
| Android | `app/src/main/res/layout/activity_main.xml` | `4edb8f1a46136317c0f7745ebe5157e785132339b16e228c2b4340da66a1d9be` |
| Android | `app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml` | `88f7653499ef524126ea5018a99baf9cc3269e7e584d6205dfdd76db39f39cc0` |
| Android | `app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml` | `88f7653499ef524126ea5018a99baf9cc3269e7e584d6205dfdd76db39f39cc0` |
| Android | `app/src/main/res/values/colors.xml` | `efb70d7499549a57cea32b00e790ef0632cb0c95cdaeefd16903c8cd12c889e4` |
| Android | `app/src/main/res/values/strings.xml` | `3dbefcfc3485b2e2e7a838cd803fcfd8ad3b093a5e60f887a70180043cf495f6` |
| Android | `app/src/main/res/values/themes.xml` | `4b056a51e376f2dd2ab78f283d55b264c3e2022f3b8d58766ff26e43281e236b` |
| Android | `app/src/main/res/values-night/themes.xml` | `4b056a51e376f2dd2ab78f283d55b264c3e2022f3b8d58766ff26e43281e236b` |
| Android | `app/src/main/res/xml/backup_rules.xml` | `6cf1a27e6807b1d24e41d3fbe7ddc1bfe1f42226027964f6eaf477d71b43b283` |
| Android | `app/src/main/res/xml/data_extraction_rules.xml` | `cb1fc47ab4a984530ed60e0e6ee638929c3038290e7e7e0b4b03a3a30fbe7381` |
| Backend schema | `app/schemas/auth.py` | `1e34ee8ca5bdd6aecab533c2816d3aa6e5f1b24831997c8c01c363a1df2638aa` |
| Backend schema | `app/schemas/preferences.py` | `4f2c124fbe3c5cd646220b4f9a9be4795529306d912f35b47249525fc521c45e` |
| Backend schema | `app/schemas/memory.py` | `90f7981df3c83da4fe6805461fd5f66288955ec0f361499a53428cfb47c7496c` |
| Backend schema | `app/schemas/knowledge.py` | `94f8594249239642833032e1a78e11809ce8eda2bd9fccaa411f44d3fc989399` |
| Backend schema | `app/schemas/conversations.py` | `d7886443072eda9d7c5706355e8e17592ce94adf2ec06625657d44528ea68e7f` |
| Backend schema | `app/schemas/usage.py` | `31c8ef58a3e485a3f69a69e50b0b8d5b166642b6fcc360831cf3c37a45d8d1f7` |
| Backend schema | `app/schemas/live.py` | `24cfe34debc9b84f5f3078457a8bbd74f4c1c22df52282b5af4a88cc43f8c134` |

### 25.2 Complete source files


#### Android: app/src/main/java/com/example/voiceagent/data/LiveAudio.kt

```kotlin
package com.example.voiceagent.data

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.util.Log
import com.konovalov.vad.silero.VadSilero
import com.konovalov.vad.silero.config.FrameSize
import com.konovalov.vad.silero.config.Mode
import com.konovalov.vad.silero.config.SampleRate
import android.media.*
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import kotlinx.coroutines.*
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.sqrt
import java.util.concurrent.atomic.AtomicLong

/** Device audio only. PCM is discarded while transport recovery is pending; never replayed. */
class LiveAudio(private val scope: CoroutineScope, private val input: (ByteString) -> Unit,
                private val state: (String) -> Unit, private val failure: (String) -> Unit,
                private val level: (Float) -> Unit,
                private val activity: (Boolean) -> Unit) {
    private var appContext: Context? = null
    private var audioManager: AudioManager? = null
    private var previousMode = AudioManager.MODE_NORMAL
    private var previousSpeaker = false
    private var previousDevice: AudioDeviceInfo? = null
    @Volatile private var holdToTalk = false
    @Volatile private var held = false
    fun initialize(context: Context) { appContext = context.applicationContext }
    fun setTalkMode(enabled: Boolean) {
        activity(false); holdToTalk = enabled; held = false; inputEpoch++
    }
    fun setTalkHeld(value: Boolean) {
        if (held == value) return
        activity(false); held = value; inputEpoch++
    }
    private fun isPlaying(): Boolean = queue.isNotEmpty() || playingPacket ||
        (track?.playbackHeadPosition?.toLong()?.and(0xffffffffL) ?: 0) < writtenFrames.get()

    @Suppress("DEPRECATION")
    private fun configureRoute(context: Context) {
        val manager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audioManager = manager
        previousMode = manager.mode; previousSpeaker = manager.isSpeakerphoneOn
        if (Build.VERSION.SDK_INT >= 31) previousDevice = manager.communicationDevice
        manager.mode = AudioManager.MODE_IN_COMMUNICATION
        if (Build.VERSION.SDK_INT >= 31) {
            val devices = manager.availableCommunicationDevices
            val headset = devices.firstOrNull { it.type in setOf(AudioDeviceInfo.TYPE_WIRED_HEADSET,
                AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_USB_HEADSET,
                AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_BLE_HEADSET) }
            val target = headset ?: devices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
            Log.i("AuraAudio", "Communication route selected: ${target?.type}; accepted=${target?.let { manager.setCommunicationDevice(it) }}")
        } else {
            manager.isSpeakerphoneOn = !manager.isWiredHeadsetOn && !manager.isBluetoothScoOn
        }
    }

    @Suppress("DEPRECATION")
    private fun restoreRoute() {
        audioManager?.let { manager -> runCatching {
            if (Build.VERSION.SDK_INT >= 31) {
                manager.clearCommunicationDevice()
                previousDevice?.let { manager.setCommunicationDevice(it) }
            } else manager.isSpeakerphoneOn = previousSpeaker
            manager.mode = previousMode
        } }
        audioManager = null; previousDevice = null
    }
    private data class Packet(val bytes: ByteArray, val epoch: Long)
    private val queue = ArrayBlockingQueue<Packet>(128)
    private var recorder: AudioRecord? = null
    private var echoCanceler: AcousticEchoCanceler? = null
    private var noiseSuppressor: NoiseSuppressor? = null
    private var track: AudioTrack? = null
    private var capture: Job? = null
    private var playback: Job? = null
    @Volatile private var running = false
    @Volatile private var uploading = false
    @Volatile private var microphoneEnabled = true
    @Volatile private var playingPacket = false
    private val writtenFrames = AtomicLong(0)
    @Volatile private var inputEpoch = 0L
    @Volatile private var playbackEpoch = 0L
    @Volatile var muted = false
    @Volatile var speaker = true

    @SuppressLint("MissingPermission")
    fun resume(captureEnabled: Boolean = true): Boolean {
        microphoneEnabled = captureEnabled
        if (running) { inputEpoch++; uploading = true; return true }
        try {
            val context = checkNotNull(appContext) { "Audio context unavailable" }
            configureRoute(context)
            val minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            require(minimum > 0)
            val mic = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum, 6400))
            recorder = mic; check(mic.state == AudioRecord.STATE_INITIALIZED)
            // Effects are optional: unsupported devices must still be able to talk.
            echoCanceler = runCatching {
                if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(mic.audioSessionId) else null
            }.getOrNull()
            noiseSuppressor = runCatching {
                if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(mic.audioSessionId) else null
            }.getOrNull()
            runCatching { echoCanceler?.enabled = true }
            runCatching { noiseSuppressor?.enabled = true }
            Log.i("AuraAudio", "AEC enabled=${echoCanceler?.enabled}; noise suppression enabled=${noiseSuppressor?.enabled}")
            val output = AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                .setAudioFormat(AudioFormat.Builder().setSampleRate(24000).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                .setBufferSizeInBytes(maxOf(24000, AudioTrack.getMinBufferSize(24000, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)))
                .setTransferMode(AudioTrack.MODE_STREAM).build()
            writtenFrames.set(0)
            track = output; mic.startRecording(); output.play(); running = true; uploading = true
            capture = scope.launch(Dispatchers.IO) {
                var detector: VadSilero? = null
                var detectorEpoch = -1L
                var gate = SpeechTurnGate()
                val buffer = ByteArray(1024)
                var filled = 0
                var lastLevelUpdate = 0L
                try {
                    while (isActive && running) {
                        val capturedEpoch = inputEpoch
                        if (detectorEpoch != capturedEpoch) {
                            detector?.close(); detector = null
                            gate = SpeechTurnGate(); filled = 0; detectorEpoch = capturedEpoch
                        }
                        val captureWasAllowed = uploading && microphoneEnabled && !muted
                        val count = mic.read(buffer, filled, buffer.size - filled)
                        if (!isActive) break
                        if (count <= 0) error("Microphone disconnected")
                        if (!captureWasAllowed || !uploading || !microphoneEnabled || muted || capturedEpoch != inputEpoch) {
                            filled = 0
                            continue
                        }
                        filled += count
                        if (filled < buffer.size) continue
                        filled = 0
                        val frame = buffer.copyOf()
                        val assistantSpeaking = isPlaying()
                        val speech = if (holdToTalk) held else {
                            val vad = detector ?: VadSilero(context, SampleRate.SAMPLE_RATE_16K,
                                FrameSize.FRAME_SIZE_512, Mode.NORMAL).also { detector = it }
                            // Stricter while assistant audio is playing; easier to hear quiet replies when idle.
                            vad.mode = if (assistantSpeaking) Mode.AGGRESSIVE else Mode.NORMAL
                            vad.isSpeech(frame)
                        }
                        val events = gate.accept(frame, speech, assistantSpeaking, holdToTalk, held)
                        var sum = 0.0
                        for (i in frame.indices step 2) {
                            val sample = ((frame[i].toInt() and 255) or (frame[i + 1].toInt() shl 8)).toShort().toDouble() / 32768
                            sum += sample * sample
                        }
                        val value = (sqrt(sum / 512) * 5).toFloat().coerceIn(0f, 1f)
                        withContext(Dispatchers.Main) {
                            if (uploading && microphoneEnabled && !muted && capturedEpoch == inputEpoch) {
                                val now = System.nanoTime()
                                if (now - lastLevelUpdate >= 100_000_000) { level(value); lastLevelUpdate = now }
                                events.forEach { event -> when (event) {
                                    SpeechTurnGate.Event.Start -> { Log.d("AuraAudio", "Speech start"); activity(true) }
                                    is SpeechTurnGate.Event.Audio -> input(event.bytes)
                                    SpeechTurnGate.Event.End -> { Log.d("AuraAudio", "Speech end"); activity(false) }
                                } }
                            }
                        }
                    }
                } catch (e: CancellationException) { throw e }
                catch (e: Exception) {
                    Log.e("AuraAudio", "Capture/VAD failed: ${e.javaClass.simpleName}")
                    withContext(Dispatchers.Main) { failure("Speech detection or microphone failed. Please reconnect.") }
                } finally { detector?.close() }
            }
            playback = scope.launch(Dispatchers.IO) {
                var notifiedSpeaking = false
                try {
                    while (isActive && running) {
                        val packet = queue.poll(100, TimeUnit.MILLISECONDS) ?: run { notifiedSpeaking = false; null } ?: continue
                        if (!speaker || packet.epoch != playbackEpoch) continue
                        playingPacket = true
                        if (!notifiedSpeaking) {
                            withContext(Dispatchers.Main) { if (packet.epoch == playbackEpoch) state("Speaking") }
                            notifiedSpeaking = true
                        }
                        var offset = 0
                        while (isActive && running && speaker && packet.epoch == playbackEpoch && offset < packet.bytes.size) {
                            val length = minOf(960, packet.bytes.size - offset)
                            val written = runCatching { output.write(packet.bytes, offset, length) }.getOrDefault(-1)
                            if (written <= 0) break
                            offset += written
                            writtenFrames.addAndGet(written.toLong() / 2)
                        }
                        playingPacket = false
                    }
                } catch (_: InterruptedException) { /* cancelled during cleanup */ }
                finally { playingPacket = false }
            }
            return true
        } catch (_: Exception) { close(); failure("Microphone or audio output unavailable."); return false }
    }
    fun enqueue(bytes: ByteString) {
        if (running && uploading && speaker && !queue.offer(Packet(bytes.toByteArray(), playbackEpoch))) failure("Audio playback fell behind. Please reconnect.")
    }
    suspend fun enableMicrophoneAfterGreeting() {
        withTimeoutOrNull(8000) {
            while (running && (queue.isNotEmpty() || playingPacket ||
                (track?.playbackHeadPosition?.toLong()?.and(0xffffffffL) ?: 0) < writtenFrames.get())) delay(25)
        }
        inputEpoch++
        microphoneEnabled = true
    }
    fun clearPlayback() {
        playbackEpoch++; queue.clear(); writtenFrames.set(0)
        runCatching { track?.pause(); track?.flush(); track?.play() }
    }
    fun pause() { uploading = false; inputEpoch++; clearPlayback(); level(0f) }
    fun toggleMute() { activity(false); inputEpoch++; muted = !muted; level(0f) }
    fun toggleSpeaker() { speaker = !speaker; if (!speaker) clearPlayback() }
    fun close() {
        running = false; uploading = false; inputEpoch++; playbackEpoch++
        capture?.cancel(); playback?.cancel()
        runCatching { echoCanceler?.release() }; echoCanceler = null
        runCatching { noiseSuppressor?.release() }; noiseSuppressor = null
        runCatching { recorder?.stop() }; runCatching { recorder?.release() }; recorder = null
        runCatching { track?.stop() }; runCatching { track?.release() }; track = null
        restoreRoute()
        queue.clear(); level(0f)
    }
}
```


#### Android: app/src/main/java/com/example/voiceagent/data/LiveTransport.kt

```kotlin
package com.example.voiceagent.data

import kotlinx.coroutines.*
import okhttp3.*
import okio.ByteString
import org.json.JSONObject

/** One durable conversation/token per transport. Network recovery never creates a conversation. */
class LiveTransport(
    private val repository: VoiceRepository,
    private val scope: CoroutineScope,
    private val conversationId: String,
    private val control: (JSONObject) -> Unit,
    private val audio: (ByteString) -> Unit,
    private val finished: (JSONObject?) -> Unit,
    private val now: () -> Long = { System.nanoTime() / 1_000_000 },
    private val socketFactory: (Request, WebSocketListener) -> WebSocket = { request, listener -> repository.client.newWebSocket(request, listener) },
) {
    private val token = requireNotNull(repository.token)
    private var socket: WebSocket? = null
    private var heartbeat: Job? = null
    private var watchdog: Job? = null
    private var retry: Job? = null
    private var stopTimer: Job? = null
    private var speechActive = false
    private var suppressOutput = false
    private var attempt = 0
    private var deadline: Long? = null
    private var graceMs = 10000L
    private var lastReceived = now()
    @Volatile var streaming = false; private set
    @Volatile private var closed = false
    @Volatile private var stopping = false

    fun start() = connect()
    private fun connect() {
        if (closed || stopping) return
        val request = Request.Builder().url(repository.baseUrl.replaceFirst("http", "ws") + "/ws/live")
            .header("Authorization", "Bearer $token").build()
        socket = socketFactory(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { scope.launch {
                if (closed || stopping || webSocket !== socket) { webSocket.close(1000, null); return@launch }
                webSocket.send(JSONObject().put("type", "start").put("conversation_id", conversationId).put("speech_detection", "client").toString())
                lastReceived = now(); startHeartbeat(webSocket, 5000L)
            } }
            override fun onMessage(webSocket: WebSocket, text: String) { scope.launch {
                if (closed || webSocket !== socket) return@launch
                lastReceived = now()
                val message = runCatching { JSONObject(text) }.getOrElse { fail("invalid_server_message"); return@launch }
                when (message.optString("type")) {
                    "ready", "resumed" -> {
                        if (message.optInt("protocol_version") != 3 ||
                            message.optString("speech_detection") != "client" ||
                            message.optJSONObject("input")?.optInt("sample_rate") != 16000 ||
                            message.optJSONObject("output")?.optInt("sample_rate") != 24000 ||
                            message.optJSONObject("input")?.optString("encoding") != "pcm_s16le" ||
                            message.optJSONObject("output")?.optString("encoding") != "pcm_s16le" ||
                            message.optJSONObject("input")?.optInt("channels") != 1 ||
                            message.optJSONObject("output")?.optInt("channels") != 1) {
                            fail("unsupported_audio_protocol"); return@launch
                        }
                        watchdog?.cancel(); deadline = null; attempt = 0
                        graceMs = (message.optDouble("reconnect_grace_seconds", 10.0) * 1000).toLong().coerceIn(1, 30000)
                        speechActive = false; suppressOutput = false
                        streaming = !stopping
                        startHeartbeat(webSocket, (message.optDouble("heartbeat_interval_seconds", 5.0) * 1000).toLong().coerceIn(25, 5000))
                    }
                    "reconnecting" -> { streaming = false; speechActive = false; suppressOutput = false; watchdog?.cancel() }
                    "interrupted", "turn_complete" -> { if (!speechActive) suppressOutput = false }
                    "error" -> { control(message); finish(); return@launch }
                    "ended" -> { control(message); finish(message.optJSONObject("report")); return@launch }
                }
                control(message) // Unknown additive events are safe to ignore in the UI.
            } }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) { scope.launch {
                if (!closed && !stopping && streaming && !suppressOutput && webSocket === socket) { lastReceived = now(); audio(bytes) }
            } }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { scope.launch {
                if (closed || webSocket !== socket) return@launch
                if (response?.code in listOf(400, 401, 403, 404)) fail("authentication_or_attachment_rejected") else disconnected(webSocket)
            } }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { scope.launch { disconnected(webSocket) } }
        })
        watchdog?.cancel()
        watchdog = scope.launch {
            delay(deadline?.let { (it - now()).coerceAtLeast(1) } ?: 15000)
            socket?.let { disconnected(it) }
        }
    }
    private fun startHeartbeat(ws: WebSocket, interval: Long) {
        heartbeat?.cancel()
        heartbeat = scope.launch {
            while (isActive && !closed && !stopping && ws === socket) {
                delay(interval)
                if (now() - lastReceived > maxOf(interval * 3, 15000L)) { disconnected(ws); break }
                if (ws.queueSize() < 1024) ws.send("{\"type\":\"ping\"}")
            }
        }
    }
    private fun disconnected(ws: WebSocket) {
        if (closed || ws !== socket) return
        heartbeat?.cancel(); watchdog?.cancel(); socket = null; ws.cancel(); streaming = false; speechActive = false; suppressOutput = false
        if (stopping) { finish(); return }
        val limit = deadline ?: (now() + graceMs).also { deadline = it }
        if (now() >= limit || attempt >= 8) { fail("client_reconnect_exhausted"); return }
        control(JSONObject().put("type", "reconnecting").put("reason", "client_network"))
        val wait = minOf(1000L, 250L * (1L shl attempt++), limit - now())
        retry = scope.launch { delay(wait); if (now() >= limit) fail("client_reconnect_exhausted") else connect() }
    }
    fun sendActivity(started: Boolean): Boolean {
        if (!streaming || stopping || closed || speechActive == started) return false
        val ws = socket ?: return false
        val type = if (started) "speech_start" else "speech_end"
        if (!ws.send(JSONObject().put("type", type).toString())) { disconnected(ws); return false }
        speechActive = started
        suppressOutput = started
        return true
    }
    fun sendAudio(bytes: ByteString) {
        // Called on the transport's dispatcher, so readiness and socket changes cannot race upload.
        if (!streaming || stopping || closed || !speechActive) return
        val ws = socket ?: return
        if (ws.queueSize() > 32000) { fail("input_backpressure"); return }
        if (!ws.send(bytes)) disconnected(ws)
    }
    fun stop() {
        if (closed || stopping) return
        stopping = true; streaming = false
        retry?.cancel(); heartbeat?.cancel(); watchdog?.cancel()
        if (socket?.send("{\"type\":\"stop\"}") == true) {
            stopTimer = scope.launch { delay(10000); finish() }
        } else finish()
    }
    private fun fail(code: String) { control(JSONObject().put("type", "error").put("code", code)); finish() }
    private fun finish(report: JSONObject? = null) {
        if (closed) return
        closed = true; streaming = false
        heartbeat?.cancel(); watchdog?.cancel(); retry?.cancel(); stopTimer?.cancel()
        socket?.close(1000, null); socket = null
        finished(report)
    }
    fun dispose() { if (!closed) { closed = true; streaming = false; heartbeat?.cancel(); watchdog?.cancel(); retry?.cancel(); stopTimer?.cancel(); socket?.cancel(); socket = null } }
}
```


#### Android: app/src/main/java/com/example/voiceagent/data/MicrophoneGate.kt (legacy, unused by current controller)

```kotlin
package com.example.voiceagent.data

import okio.ByteString
import okio.ByteString.Companion.toByteString

/** Silence lets automatic VAD finish a turn without forwarding background sound. */
class MicrophoneGate {
    var holdToTalk = false; private set
    var held = false; private set
    private var silence = ByteString.EMPTY
    fun setMode(enabled: Boolean) { holdToTalk = enabled; held = false }
    fun updateHeld(value: Boolean) { held = value && holdToTalk }
    fun packet(audio: ByteString): ByteString {
        if (!holdToTalk || held) return audio
        if (silence.size != audio.size) silence = ByteArray(audio.size).toByteString()
        return silence
    }
}
```


#### Android: app/src/main/java/com/example/voiceagent/data/SpeechTurnGate.kt

```kotlin
package com.example.voiceagent.data

import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.io.ByteArrayOutputStream
import java.util.ArrayDeque

/** One instance per uninterrupted capture epoch. Only the capture worker owns this state. */
internal class SpeechTurnGate {
    sealed interface Event {
        data object Start : Event
        data class Audio(val bytes: ByteString) : Event
        data object End : Event
    }
    private val preRoll = ArrayDeque<ByteArray>()
    private var speaking = false
    private var positiveFrames = 0
    private var silentFrames = 0

    fun accept(frame: ByteArray, speech: Boolean, assistantSpeaking: Boolean,
               holdToTalk: Boolean, held: Boolean): List<Event> {
        require(frame.size == 1024) // 512 PCM16 samples = 32 ms at 16 kHz.
        if (holdToTalk && !held) {
            preRoll.clear(); positiveFrames = 0; silentFrames = 0
            if (!speaking) return emptyList()
            speaking = false
            return listOf(Event.End)
        }
        if (!speaking) {
            preRoll.addLast(frame)
            while (preRoll.size > 9) preRoll.removeFirst() // 288 ms, including confirmation.
            positiveFrames = if (speech) positiveFrames + 1 else 0
            val required = if (assistantSpeaking) 6 else 3 // 192 ms / 96 ms.
            if (!holdToTalk && positiveFrames < required) return emptyList()
            speaking = true; silentFrames = 0
            val events = mutableListOf<Event>(Event.Start)
            // Coalesce pre-roll to stay below backend packet and queue limits.
            val buffered = ByteArrayOutputStream()
            preRoll.forEach { buffered.write(it) }
            val bytes = buffered.toByteArray()
            for (offset in bytes.indices step 3072) {
                events.add(Event.Audio(bytes.toByteString(offset, minOf(3072, bytes.size - offset))))
            }
            preRoll.clear()
            return events
        }
        silentFrames = if (speech || holdToTalk) 0 else silentFrames + 1
        val events = mutableListOf<Event>(Event.Audio(frame.toByteString()))
        if (silentFrames >= 24) { // 768 ms: tolerate natural pauses.
            speaking = false; positiveFrames = 0; silentFrames = 0
            events.add(Event.End)
        }
        return events
    }
}
```


#### Android: app/src/main/java/com/example/voiceagent/data/VoiceRepository.kt

```kotlin
package com.example.voiceagent.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

class ApiException(val code: String, val status: Int, val retryAfter: String? = null) : IOException(
    when (code) {
        "invalid_start", "unsupported_audio_protocol", "speech_detection_mismatch" -> "This app needs the updated voice backend. Restart your updated backend, then start a new conversation."
        "registration_disabled" -> "This server uses provisioned accounts. Sign in with the account supplied by your administrator."
        "daily_allowance_exhausted" -> "Today's voice allowance has been used. Check Usage for the reset time."
        "session_busy", "user_session_active" -> "A conversation is already active. End it before starting another."
        "tools_disabled" -> "Knowledge tools are disabled on this server. Turn off reference tools to start an audio-only conversation."
        "missing_api_key" -> "The server's Gemini API key is not configured. Configure it on the backend and restart the server before starting a voice conversation."
        "memory_version_conflict", "knowledge_version_conflict" -> "This item changed since you opened it. Refresh and reopen it before saving."
        "server_draining" -> "The server is being updated. Please try again later."
        "authentication_required", "invalid_token", "session_expired" -> "Your session has expired. Please sign in again."
        "report_not_available" -> "The session report is still being finalized. Try again shortly."
        else -> if (status == 429) "Too many requests. Please wait${retryAfter?.let { " $it seconds" }.orEmpty()} and try again." else code.replace('_', ' ').replaceFirstChar { it.uppercase() }
    }
)

/** Tokens remain in memory; redirecting authenticated requests to another origin is forbidden. */
class VoiceRepository(val client: OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(10, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS)
    .addInterceptor { chain ->
        val request = chain.request()
        val host = request.url.host
        val outgoing = if (host.endsWith(".ngrok-free.dev") || host.endsWith(".ngrok-free.app")) {
            request.newBuilder().header("ngrok-skip-browser-warning", "true").build()
        } else request
        chain.proceed(outgoing)
    }
    .followRedirects(false).followSslRedirects(false).build()) {
    var baseUrl = ""; private set
    @Volatile var token: String? = null
    fun configure(address: String) {
        val normalized = normalizeBackendOrigin(address)
        if (baseUrl != normalized) token = null
        baseUrl = normalized
    }

    suspend fun request(path: String, method: String = "GET", body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        check(baseUrl.isNotBlank()) { "Enter your backend URL on the sign-in page first." }
        val originalToken = token
        val builder = Request.Builder().url(baseUrl + path)
        originalToken?.let { builder.header("Authorization", "Bearer $it") }
        if (method != "GET") builder.method(method, if (method == "DELETE") null else (body ?: JSONObject()).toString().toRequestBody("application/json".toMediaType()))
        client.newCall(builder.build()).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            val json = runCatching { if (raw.isBlank()) JSONObject() else JSONObject(raw) }.getOrElse {
                if (!response.isSuccessful) throw ApiException("server_unavailable", response.code)
                throw IOException("The server returned an invalid response.")
            }
            if (!response.isSuccessful) {
                if (response.code == 401 && token == originalToken) token = null
                throw ApiException(json.optString("error", "request_failed"), response.code, response.header("Retry-After"))
            }
            json
        }
    }
    suspend fun authenticate(email: String, password: String, register: Boolean) {
        val credentials = JSONObject().put("email", email.trim()).put("password", password)
        if (register) request("/api/v1/auth/register", "POST", credentials)
        token = request("/api/v1/auth/login", "POST", credentials).getString("access_token")
    }
}

/** One origin is used for both HTTP and WebSocket connections. */
fun normalizeBackendOrigin(address: String): String {
    val url = address.trim().toHttpUrlOrNull()
    require(url != null && url.username.isEmpty() && url.password.isEmpty() &&
        url.encodedPath == "/" && url.query == null && url.fragment == null &&
        !address.substringAfter("://", "").substringBefore('/').contains('@')) {
        "Enter only the backend URL, for example https://your-tunnel.ngrok-free.dev (without /docs)."
    }
    require(url.isHttps || url.host in listOf("127.0.0.1", "localhost", "::1")) {
        "Use HTTPS for an ngrok or remote backend. HTTP is allowed only for localhost."
    }
    return url.toString().removeSuffix("/")
}
```


#### Android: app/src/main/java/com/example/voiceagent/MainActivity.kt

```kotlin
package com.example.voiceagent

import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import com.example.voiceagent.ui.VoiceApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        volumeControlStream = android.media.AudioManager.USE_DEFAULT_STREAM_TYPE
        enableEdgeToEdge(SystemBarStyle.dark(android.graphics.Color.TRANSPARENT), SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        setContent { VoiceApp() }
    }
}
```


#### Android: app/src/main/java/com/example/voiceagent/ui/FeatureScreens.kt

```kotlin
package com.example.voiceagent.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject
import java.text.DateFormat
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

private fun localTime(raw: String): String = runCatching {
    val date = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }.parse(raw.substringBefore('.').removeSuffix("Z").substringBefore('+'))!!
    DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(date)
}.getOrDefault(raw)
private fun duration(seconds: Double): String = "${seconds.toInt() / 60}m ${seconds.toInt() % 60}s"

@Composable internal fun FeatureLayout(title: String, subtitle: String, back: () -> Unit, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(horizontal = 26.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(15.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = back) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") }
            Text(title, fontSize = 25.sp, fontWeight = FontWeight.Medium)
        }
        if (subtitle.isNotBlank()) Text(subtitle, color = Muted, fontSize = 12.sp, lineHeight = 19.sp)
        content()
    }
}
@Composable private fun FeatureCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = Panel, contentColor = White, shape = RoundedCornerShape(18.dp), border = BorderStroke(1.dp, Line), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
    }
}

@Composable fun UsageScreen(model: VoiceViewModel, back: () -> Unit) {
    LaunchedEffect(Unit) { model.refreshUsage() }
    FeatureLayout("Your voice time", "Daily allowance is based on connected time. Reconnecting does not reset a session's limits.", back) {
        val usage = model.usage
        if (usage == null) Text("Loading usage…", color = Muted)
        else {
            FeatureCard {
                Text(duration(usage.optDouble("available_seconds")), fontSize = 36.sp, color = Lilac)
                Text("available today", color = Muted, fontSize = 13.sp)
                val daily = usage.optDouble("daily_connected_seconds", 1.0).coerceAtLeast(1.0)
                LinearProgressIndicator(progress = { ((usage.optDouble("connected_seconds") + usage.optDouble("reserved_seconds")) / daily).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                Text("Used ${duration(usage.optDouble("connected_seconds"))} · Reserved ${duration(usage.optDouble("reserved_seconds"))}", fontSize = 12.sp, color = Muted)
                Text("Daily limit: ${duration(daily)}", fontSize = 12.sp)
                Text("Resets ${localTime(usage.optString("resets_at"))} (your local time)", fontSize = 12.sp, color = Cyan)
            }
            FeatureCard {
                Text("Usage details", fontSize = 17.sp)
                Text("${usage.optInt("sessions_started")} sessions started · ${usage.optInt("sessions_settled")} settled", fontSize = 12.sp)
                Text("Model cost estimate: $${usage.optString("estimated_cost_usd", "0")}", fontSize = 14.sp)
                Text("An estimate, not a bill. ${usage.optInt("incomplete_cost_sessions")} sessions have incomplete cost information.", fontSize = 12.sp, color = Muted)
                Text(if (usage.optBoolean("cost_guard_enabled")) "Estimated spend guard enabled" else "Estimated spend guard disabled", fontSize = 12.sp, color = Muted)
            }
        }
        OutlinedButton(onClick = model::refreshUsage) { Text("Refresh usage") }
    }
}

@Composable fun MemoryScreen(model: VoiceViewModel, back: () -> Unit) {
    var editing by remember { mutableStateOf<JSONObject?>(null) }
    var editor by rememberSaveable { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<JSONObject?>(null) }
    var clearAll by rememberSaveable { mutableStateOf(false) }
    if (editor) {
        BackHandler { editor = false }
        MemoryEditor(model, editing) { editor = false }
        return
    }
    LaunchedEffect(Unit) { model.refreshMemories() }
    FeatureLayout("Saved memories", "You choose what Aura remembers. Saved facts can be sent to the voice provider when memory is enabled. No facts are extracted automatically from your voice.", back) {
        FeatureCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text("Use saved memories"); Text(if (model.memoryEnabled) "On for new conversations" else "Off · saved facts are retained", color = Muted, fontSize = 11.sp) }
                Switch(checked = model.memoryEnabled, onCheckedChange = model::changeMemoryConsent, enabled = !model.busy)
            }
            Text("Editing memories or changing consent ends affected active conversations. Deletion removes live facts, but cannot retract them from the provider or database backups.", fontSize = 11.sp, color = Muted, lineHeight = 17.sp)
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("${model.memories.size}/${model.memoryLimit} saved facts", color = Muted, fontSize = 12.sp)
            Button(onClick = { editing = null; editor = true }, enabled = model.memoryEnabled && !model.busy && model.memories.size < model.memoryLimit) { Text("Add fact") }
        }
        if (model.memories.isEmpty()) Text("No saved facts yet. You can add a learning goal, preferred style, or useful background.", fontSize = 13.sp, color = Muted)
        model.memories.forEach { item -> FeatureCard {
            Text(item.getString("key").replace('_', ' '), color = Lilac, fontSize = 14.sp)
            Text(item.getString("content"), fontSize = 14.sp, lineHeight = 21.sp)
            Text("Priority ${item.getInt("priority")} · Version ${item.getInt("version")}", color = Muted, fontSize = 10.sp)
            Row {
                TextButton(onClick = { editing = item; editor = true }, enabled = model.memoryEnabled && !model.busy) { Text("Edit") }
                TextButton(onClick = { deleting = item }, enabled = !model.busy) { Text("Delete", color = MaterialTheme.colorScheme.error) }
            }
        } }
        Row {
            TextButton(onClick = model::refreshMemories, enabled = !model.busy) { Text("Refresh") }
            if (model.memories.isNotEmpty()) TextButton(onClick = { clearAll = true }, enabled = !model.busy) { Text("Delete all facts", color = MaterialTheme.colorScheme.error) }
        }
    }
    if (deleting != null || clearAll) AlertDialog(onDismissRequest = { deleting = null; clearAll = false }, title = { Text(if (clearAll) "Delete all saved facts?" else "Delete this fact?") }, text = { Text("This removes the saved fact${if (clearAll) "s" else ""} from your account. Affected live conversations will end.") }, confirmButton = {
        TextButton(onClick = { model.deleteMemory(if (clearAll) null else deleting!!.getString("id")) { deleting = null; clearAll = false } }, enabled = !model.busy) { Text("Delete") }
    }, dismissButton = { TextButton(onClick = { deleting = null; clearAll = false }) { Text("Cancel") } })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun MemoryEditor(model: VoiceViewModel, item: JSONObject?, dismiss: () -> Unit) {
    var key by remember { mutableStateOf(item?.getString("key").orEmpty()) }
    var content by remember { mutableStateOf(item?.getString("content").orEmpty()) }
    var priority by remember { mutableFloatStateOf(item?.getInt("priority")?.toFloat() ?: 50f) }
    FeatureLayout("Saved fact", "", dismiss) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(if (item == null) "A fact to remember" else "Edit saved fact", fontSize = 25.sp)
            OutlinedTextField(key, { if (it.length <= 64) key = it }, label = { Text("Key, e.g. learning_goal") }, enabled = item == null, singleLine = true, modifier = Modifier.fillMaxWidth(), supportingText = { Text("Lowercase letters, digits, underscores; start with a letter.") })
            OutlinedTextField(content, { if (it.length <= 500 && '\u0000' !in it) content = it }, label = { Text("Saved fact") }, supportingText = { Text("${content.length}/500") }, modifier = Modifier.fillMaxWidth())
            Text("Priority: ${priority.toInt()}", color = Muted, fontSize = 12.sp)
            Slider(value = priority, onValueChange = { priority = it }, valueRange = 0f..100f)
            Text("Higher priority facts are considered first. The server selects a bounded set for each conversation.", color = Muted, fontSize = 11.sp)
            Button(onClick = { model.saveMemory(item?.getString("id"), key, content, priority.toInt(), item?.getInt("version") ?: 1, dismiss) }, enabled = !model.busy && model.memoryEnabled && key.matches(Regex("^[a-z][a-z0-9_]{0,63}$")) && content.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text(if (model.busy) "Saving…" else "Save fact") }
        }
    }
}

@Composable fun KnowledgeScreen(model: VoiceViewModel, back: () -> Unit) {
    var query by rememberSaveable { mutableStateOf("") }
    var editor by rememberSaveable { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<JSONObject?>(null) }
    if (editor) {
        BackHandler { editor = false }
        KnowledgeEditor(model, model.selectedKnowledge) { editor = false }
        return
    }
    LaunchedEffect(Unit) { model.refreshKnowledge() }
    FeatureLayout("Your references", "Keep useful notes for conversations. Search includes your private references and published shared references; it does not search the internet.", back) {
        FeatureCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) { Text("Use reference tools"); Text("Optional · next conversation only", fontSize = 11.sp, color = Muted) }
                Switch(checked = model.useTools, onCheckedChange = { model.useTools = it }, enabled = !model.active)
            }
            Text("Requires tools enabled on your backend. Selected reference text reaches the voice provider. Changes end affected tool-enabled conversations.", fontSize = 11.sp, color = Muted, lineHeight = 17.sp)
        }
        OutlinedTextField(query, { if (it.length <= 200) query = it }, label = { Text("Search references") }, modifier = Modifier.fillMaxWidth(), singleLine = true, supportingText = { Text("Up to 8 words") })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { model.searchKnowledge(query) }, enabled = !model.busy && query.isNotBlank() && query.trim().split(Regex("\\s+")).size <= 8) { Text("Search") }
            TextButton(onClick = { query = ""; model.refreshKnowledge() }, enabled = !model.busy) { Text("My references") }
        }
        Button(onClick = { model.clearSelectedKnowledge(); editor = true }, enabled = !model.busy) { Text("Add reference") }
        Text(if (model.searchResults != null) "Search results" else "Your private references (${model.knowledge.size})", color = Lilac, fontSize = 12.sp)
        val items = model.searchResults ?: model.knowledge
        if (items.isEmpty()) Text("No references found. Add a note or try a different search.", color = Muted, fontSize = 13.sp)
        items.forEach { item -> FeatureCard {
            Text(item.getString("title"), fontSize = 16.sp)
            if (item.has("excerpt")) Text(item.getString("excerpt"), color = Muted, fontSize = 12.sp)
            TextButton(onClick = { model.openKnowledge(item.getString("id")) { editor = true } }, enabled = !model.busy) { Text("Open reference") }
            if (model.searchResults == null) TextButton(onClick = { deleting = item }, enabled = !model.busy) { Text("Delete", color = MaterialTheme.colorScheme.error) }
        } }
        if (model.searchResults == null && model.knowledgeNext != null) TextButton(onClick = model::moreKnowledge, enabled = !model.busy) { Text("Load more references") }
    }
    deleting?.let { item -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("Delete reference?") }, text = { Text("${item.getString("title")} will be removed. Affected live conversations will end.") }, confirmButton = {
        TextButton(onClick = { model.deleteKnowledge(item.getString("id")) { deleting = null } }, enabled = !model.busy) { Text("Delete") }
    }, dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancel") } }) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun KnowledgeEditor(model: VoiceViewModel, item: JSONObject?, dismiss: () -> Unit) {
    var title by remember { mutableStateOf(item?.getString("title").orEmpty()) }
    var content by remember { mutableStateOf(item?.getString("content").orEmpty()) }
    var url by remember { mutableStateOf(item?.optString("source_url").orEmpty()) }
    val shared = item != null && item.isNull("owner_id")
    val validUrl = url.isBlank() || runCatching { val uri = java.net.URI(url.trim()); uri.scheme in listOf("http", "https") && uri.host != null && uri.userInfo == null }.getOrDefault(false)
    FeatureLayout("Reference", "", dismiss) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(if (shared) "Shared reference" else if (item == null) "Add a reference" else "Edit reference", fontSize = 25.sp)
            OutlinedTextField(title, { if (it.length <= 120 && '\u0000' !in it) title = it }, label = { Text("Title") }, readOnly = shared, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(content, { if (it.length <= 6000 && '\u0000' !in it) content = it }, label = { Text("Reference notes") }, minLines = 4, maxLines = 10, readOnly = shared, supportingText = { Text("${content.length}/6000") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(url, { if (it.length <= 1000) url = it }, label = { Text("Source URL (optional)") }, isError = !validUrl, readOnly = shared, modifier = Modifier.fillMaxWidth())
            Text("Source URLs are metadata; the backend does not fetch or verify their contents.", fontSize = 11.sp, color = Muted)
            if (shared) SourceLinks(listOf(item!!))
            else Button(onClick = { model.saveKnowledge(item?.getString("id"), title, content, url, item?.getInt("version") ?: 1, dismiss) }, enabled = !model.busy && validUrl && title.isNotBlank() && content.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text(if (model.busy) "Saving…" else "Save reference") }
        }
    }
}

@Composable internal fun SourceLinks(sources: List<JSONObject>) {
    val handler = LocalUriHandler.current
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Text("References returned to Aura", fontSize = 10.sp, color = Muted)
        sources.forEach { source ->
            val url = source.optString("source_url")
            val safe = runCatching { val uri = java.net.URI(url); uri.scheme in listOf("http", "https") && uri.host != null && uri.userInfo == null }.getOrDefault(false)
            if (safe) TextButton(onClick = { runCatching { handler.openUri(url) } }) { Text(source.optString("title"), fontSize = 12.sp) }
            else Text(source.optString("title"), color = Lilac, fontSize = 12.sp, modifier = Modifier.padding(vertical = 8.dp))
        }
        Text("These references were retrieved for the assistant; they do not verify its answer.", fontSize = 10.sp, color = Muted)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun ReportPage(model: VoiceViewModel, dismiss: () -> Unit) {
    val report = model.report
    FeatureLayout("Conversation details", "", dismiss) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            if (report == null) Text("No report available yet.", color = Muted)
            else {
                Text(report.optString("end_reason").replace('_', ' ').replaceFirstChar { it.uppercase() }, color = Lilac, fontSize = 17.sp)
                Text("Duration ${duration(report.optDouble("duration_seconds"))} · ${report.optInt("turn_count")} turns", fontSize = 14.sp)
                Text("${report.optInt("provider_reconnect_count")} provider reconnects · ${report.optInt("client_reconnect_count")} client reconnects", fontSize = 12.sp, color = Muted)
                Text("${report.optInt("tool_call_count")} tool calls · ${report.optInt("knowledge_result_count")} reference results", fontSize = 12.sp, color = Muted)
                val complete = report.optBoolean("usage_complete") && !report.isNull("estimated_model_cost_usd")
                Text(if (complete) "Estimated model cost: $${report.optString("estimated_model_cost_usd")}" else "Model cost is unavailable or incomplete.", fontSize = 14.sp)
                if (!complete && !report.isNull("observed_model_cost_usd")) Text("Partial observed estimate: $${report.optString("observed_model_cost_usd")}", color = Muted, fontSize = 12.sp)
                Text("Estimates are not invoices. Connected voice time determines your allowance.", fontSize = 12.sp, color = Muted)
                if (!report.optBoolean("persisted")) Text("The server has not confirmed that this report was saved.", color = MaterialTheme.colorScheme.error, fontSize = 12.sp)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable internal fun PreferencesPage(model: VoiceViewModel, dismiss: () -> Unit) {
    var language by remember { mutableStateOf(model.language) }
    var detail by remember { mutableStateOf(model.detail) }
    var goal by remember { mutableStateOf(model.goal) }
    var name by remember { mutableStateOf(model.displayName) }
    var instructions by remember { mutableStateOf(model.instructions) }
    var mode by remember { mutableStateOf(model.mode) }
    FeatureLayout("Conversation preferences", "", dismiss) {
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Changes apply to new conversations.", color = Muted, fontSize = 12.sp)
            OutlinedTextField(name, { if (it.length <= 80 && '\u0000' !in it) name = it }, label = { Text("Display name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Text("LANGUAGE", fontSize = 10.sp, letterSpacing = 2.sp, color = Lilac)
            listOf("English", "Hindi", "English and Hindi").forEach { value ->
                Row(Modifier.fillMaxWidth().clickable { language = value }, verticalAlignment = Alignment.CenterVertically) { RadioButton(selected = language == value, onClick = { language = value }); Text(value, fontSize = 14.sp) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { listOf("brief", "detailed").forEach { value -> FilterChip(selected = detail == value, onClick = { detail = value }, label = { Text(value.replaceFirstChar { it.uppercase() }) }) } }
            Text("CONVERSATION MODE", fontSize = 10.sp, letterSpacing = 2.sp, color = Lilac)
            listOf("general" to "Everyday conversation", "english_practice" to "English practice", "interview_practice" to "Interview practice").forEach { (value, label) ->
                Row(Modifier.fillMaxWidth().clickable { mode = value }, verticalAlignment = Alignment.CenterVertically) { RadioButton(selected = mode == value, onClick = { mode = value }); Text(label, fontSize = 14.sp) }
            }
            OutlinedTextField(goal, { if (it.length <= 500 && '\u0000' !in it) goal = it }, label = { Text("Conversation focus") }, supportingText = { Text("${goal.length}/500") }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(instructions, { if (it.length <= 1000 && '\u0000' !in it) instructions = it }, label = { Text("How should Aura respond?") }, supportingText = { Text("${instructions.length}/1000 · Saved with your profile") }, modifier = Modifier.fillMaxWidth())
            Button(onClick = { model.savePreferences(JSONObject().put("language", language).put("response_detail", detail).put("goal", goal).put("display_name", name).put("custom_instructions", instructions).put("conversation_mode", mode), dismiss) }, enabled = model.signedIn && !model.busy, modifier = Modifier.fillMaxWidth().height(52.dp), shape = RoundedCornerShape(15.dp)) { Text(if (model.busy) "Saving…" else "Save preferences") }
            if (!model.signedIn) Text("Sign in from your profile to save preferences.", color = Muted, fontSize = 12.sp)
        }
    }
}
```


#### Android: app/src/main/java/com/example/voiceagent/ui/VoiceApp.kt

```kotlin
﻿package com.example.voiceagent.ui

import android.Manifest
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.*
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlin.math.*
import com.example.voiceagent.data.normalizeBackendOrigin

internal val Ink = Color(0xFF0C0E18)
internal val Panel = Color(0xFF181B29)
internal val Muted = Color(0xFFB1B6CB)
internal val Lilac = Color(0xFFC6B8FF)
internal val Cyan = Color(0xFF88E2DF)
internal val Line = Color(0xFF34394D)
internal val White = Color(0xFFF5F3FF)
private val VoiceColors = darkColorScheme(
    primary = Lilac, onPrimary = Ink, primaryContainer = Color(0xFF34304F), onPrimaryContainer = White,
    secondary = Cyan, onSecondary = Ink, background = Ink, onBackground = White,
    surface = Panel, onSurface = White, surfaceVariant = Panel, onSurfaceVariant = Muted,
    surfaceContainer = Panel, surfaceContainerHigh = Panel, surfaceContainerHighest = Color(0xFF252939),
    outline = Color(0xFF737B96), outlineVariant = Line, error = Color(0xFFFFB4BD), onError = Color(0xFF420D18)
)

/** Surface supplies content color to every screen, including plain Text and form labels. */
@Composable internal fun AuraTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = VoiceColors) {
        Surface(Modifier.fillMaxSize(), color = Ink, contentColor = White) { content() }
    }
}

@Composable fun VoiceApp(model: VoiceViewModel = viewModel()) {
    val audioContext = LocalContext.current
    SideEffect { model.initializeAudio(audioContext) }
    var page by rememberSaveable { mutableStateOf(if (model.signedIn) "Home" else "Login") }
    val mainPages = listOf("Home", "History", "Settings")
    fun back() { page = when (page) {
        "Register" -> "Login"
        "Preferences", "Memory", "Knowledge", "Usage", "Account" -> "Settings"
        "Report" -> "History"
        else -> "Home"
    } }
    BackHandler(page !in listOf("Home", "Login")) { back() }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) model.start() else model.error = "Allow microphone access in Android settings to start a conversation."
    }
    LaunchedEffect(model.signedIn) { page = if (model.signedIn) "Home" else "Login" }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        model.setForeground(owner.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_START) model.setForeground(true)
            if (event == Lifecycle.Event.ON_STOP) model.setForeground(false)
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }
    AuraTheme {
        Column(Modifier.fillMaxSize().safeDrawingPadding()) {
            if (page in mainPages) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.GraphicEq, null, tint = Lilac, modifier = Modifier.size(28.dp))
                    Text("aura", color = White, fontSize = 26.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(start = 10.dp))
                    Spacer(Modifier.weight(1f))
                    IconButton(onClick = { page = "Account" }) { Icon(Icons.Outlined.PersonOutline, "Your account", tint = White) }
                }
            }
            model.error?.let { message ->
                Surface(color = Color(0xFF3D202D), contentColor = Color(0xFFFFD6DB), modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 6.dp), shape = RoundedCornerShape(14.dp)) {
                    Row(Modifier.padding(start = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(message, color = Color(0xFFFFD6DB), fontSize = 13.sp, modifier = Modifier.weight(1f).padding(vertical = 12.dp))
                        IconButton(onClick = { model.error = null }) { Icon(Icons.Outlined.Close, "Dismiss message") }
                    }
                }
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (page) {
                    "Login" -> AuthPage(model, register = false, switchPage = { model.error = null; page = "Register" }) { page = "Home" }
                    "Register" -> AuthPage(model, register = true, switchPage = { model.error = null; page = "Login" }) { page = "Home" }
                    "Home" -> HomeScreen(model) { if (model.signedIn) permission.launch(Manifest.permission.RECORD_AUDIO) else page = "Login" }
                    "History" -> HistoryScreen(model) { id -> model.openReport(id) { page = "Report" } }
                    "Preferences" -> PreferencesPage(model) { back() }
                    "Report" -> ReportPage(model) { back() }
                    "Memory" -> MemoryScreen(model) { back() }
                    "Knowledge" -> KnowledgeScreen(model) { back() }
                    "Usage" -> UsageScreen(model) { back() }
                    "Account" -> AccountPage(model) { back() }
                    else -> SettingsScreen(model) { destination -> page = destination }
                }
            }
            if (page in mainPages) {
                NavigationBar(containerColor = Ink, contentColor = White, tonalElevation = 0.dp) {
                    listOf("Home" to Icons.Outlined.GraphicEq, "History" to Icons.Outlined.History, "Settings" to Icons.Outlined.Tune).forEach { (label, icon) ->
                        NavigationBarItem(selected = page == label, onClick = { page = label; if (label == "History") model.refreshHistory() }, icon = { Icon(icon, label) }, label = { Text(label) },
                            colors = NavigationBarItemDefaults.colors(selectedIconColor = Lilac, selectedTextColor = Lilac, unselectedIconColor = Muted, unselectedTextColor = Muted, indicatorColor = Color(0xFF28243F)))
                    }
                }
            }
        }
    }
}

@Composable internal fun HomeScreen(model: VoiceViewModel, start: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 28.dp, vertical = 20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(if (model.displayName.isBlank()) "Your space to talk." else "Hello, ${model.displayName}.", color = White, fontSize = 29.sp, fontWeight = FontWeight.Medium, textAlign = TextAlign.Center)
        Text(if (model.active) "Take your time. Aura is here." else "A clear mind starts with a conversation.", color = Muted, fontSize = 14.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 12.dp))
        Spacer(Modifier.height(20.dp))
        AuraOrb(Modifier.size(250.dp), active = model.active)
        Text(if (model.active) model.status else "Ready when you are", color = if (model.active) Cyan else Muted, fontSize = 14.sp, modifier = Modifier.padding(top = 12.dp))
        if (model.active) Text("%02d:%02d".format(model.seconds / 60, model.seconds % 60), color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
        Spacer(Modifier.height(28.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Hold to talk", color = White, fontSize = 14.sp)
                Text(if (model.holdToTalk) "Background sound is blocked while released" else "Hands-free: speak to interrupt", color = Muted, fontSize = 12.sp)
            }
            Switch(checked = model.holdToTalk, onCheckedChange = model::updateHoldToTalk, enabled = !model.stopping)
        }
        if (model.active && model.holdToTalk && !model.stopping) {
            HoldToTalkControl(model)
            Spacer(Modifier.height(12.dp))
        }
        Button(onClick = { if (model.active) model.stop() else start() }, enabled = !model.busy && !model.stopping,
            colors = ButtonDefaults.buttonColors(containerColor = Lilac, contentColor = Ink), shape = RoundedCornerShape(22.dp), modifier = Modifier.fillMaxWidth().height(60.dp)) {
            if (model.busy || model.stopping) CircularProgressIndicator(Modifier.size(21.dp), color = Ink, strokeWidth = 2.dp)
            else {
                Icon(if (model.active) Icons.Outlined.StopCircle else Icons.Outlined.Mic, null, modifier = Modifier.size(23.dp))
                Text(if (model.active) "Finish conversation" else "Start talking", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(start = 10.dp))
            }
        }
        if (model.active && !model.stopping) TextButton(onClick = model::toggleMute, modifier = Modifier.padding(top = 6.dp)) {
            Text(if (model.muted) "Resume microphone" else "Pause microphone", color = Lilac, fontSize = 13.sp)
        }
        Text(if (model.active) "Your conversation stays here until you finish." else "Tap once. Connect. Aura says hello first.", color = Muted, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 18.dp))
        if (model.sources.isNotEmpty()) SourceLinks(model.sources)
    }
}

/** Pointer cancellation and leaving Home always release the microphone. */
@Composable private fun HoldToTalkControl(model: VoiceViewModel) {
    val enabled = model.microphoneReady && !model.muted
    DisposableEffect(model) { onDispose { model.updateTalkHeld(false) } }
    Surface(color = if (model.talkHeld) Cyan else Panel, contentColor = if (model.talkHeld) Ink else White,
        shape = RoundedCornerShape(18.dp), border = BorderStroke(1.dp, if (model.talkHeld) Cyan else Line),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp)
            .semantics(mergeDescendants = true) {
                role = Role.Button
                onClick(label = if (model.talkHeld) "Stop microphone" else "Start microphone") {
                    if (enabled) model.updateTalkHeld(!model.talkHeld)
                    enabled
                }
            }
            .pointerInput(enabled) {
                if (enabled) detectTapGestures(onPress = {
                    model.updateTalkHeld(true)
                    try { tryAwaitRelease() } finally { model.updateTalkHeld(false) }
                })
            }) {
        Text(if (!enabled) "Microphone paused" else if (model.talkHeld) "Listening — release when finished" else "Hold to talk",
            modifier = Modifier.padding(18.dp), textAlign = TextAlign.Center)
    }
    Text("Hold while speaking. With a screen reader, activate to start, then activate again to finish.",
        color = Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
}

/** Geometry and gradients are cached once. Only the GPU layer rotates during a conversation. */
@Composable internal fun AuraOrb(modifier: Modifier = Modifier, active: Boolean = false) {
    val rotation = if (active) {
        val transition = rememberInfiniteTransition(label = "orb layer")
        transition.animateFloat(0f, 360f, infiniteRepeatable(tween(24000, easing = LinearEasing)), label = "rotation")
    } else remember { mutableFloatStateOf(0f) }
    Box(modifier.graphicsLayer { rotationZ = rotation.value }.drawWithCache {
        val c = Offset(size.width / 2, size.height / 2); val r = size.minDimension * .36f
        val glow = Brush.radialGradient(listOf(Color(0xFF54399D).copy(alpha = .3f), Color.Transparent), c, r * 1.5f)
        val body = Brush.radialGradient(listOf(Color(0xFF29396D), Color(0xFF16162F), Color(0xFF090C1B)), Offset(c.x - r * .35f, c.y - r * .35f), r * 1.55f)
        val edge = Brush.sweepGradient(listOf(Color(0xFF8FE4EF), Color(0xFF4A4493), Color(0xFFAA86EF), Color(0xFF8FE4EF)), c)
        val ribbons = (0..3).map { band ->
            val path = Path()
            for (step in 0..72) {
                val a = step / 72f * (2 * PI).toFloat()
                val x = cos(a) * r * .94f
                val y = sin(a) * r * (.28f + band * .12f) + sin(a * 2 + band) * r * .08f
                val angle = band * .8f
                val px = c.x + x * cos(angle) - y * sin(angle)
                val py = c.y + x * sin(angle) + y * cos(angle)
                if (step == 0) path.moveTo(px, py) else path.lineTo(px, py)
            }
            path.close()
            path to Brush.sweepGradient(listOf(Color.Transparent, Color(0xFF9380F2).copy(alpha = .65f), Color(0xFF8CE5F1).copy(alpha = .65f), Color.Transparent), c)
        }
        onDrawBehind {
            drawCircle(glow, r * 1.5f)
            drawCircle(body, r)
            ribbons.forEach { (path, brush) -> drawPath(path, brush, style = Stroke(r * .035f)) }
            drawCircle(edge, r, style = Stroke(1.2.dp.toPx()))
        }
    })
}

@Composable private fun HistoryScreen(model: VoiceViewModel, open: (String) -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { Text("Your conversations", color = White, fontSize = 28.sp, fontWeight = FontWeight.Medium) }
        item { Text("Come back to the moments that mattered.", color = Muted, fontSize = 13.sp) }
        if (model.history.isEmpty()) item { Text("Your first conversation is waiting. Start talking from Home.", color = Muted, modifier = Modifier.padding(vertical = 42.dp)) }
        items(model.history, key = { it.getString("id") }) { item ->
            Surface(onClick = { open(item.getString("id")) }, color = Panel, contentColor = White, shape = RoundedCornerShape(20.dp), border = BorderStroke(1.dp, Line)) {
                Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                    Text(item.optJSONObject("preferences_snapshot")?.optString("goal")?.takeIf { it.isNotBlank() } ?: "A conversation with Aura", color = White, fontSize = 16.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(item.optString("created_at").take(16).replace('T', ' '), color = Muted, fontSize = 12.sp)
                    Text(item.optString("status").replaceFirstChar { it.uppercase() }, color = Cyan, fontSize = 12.sp)
                }
            }
        }
        if (model.historyNext != null) item { TextButton(onClick = { model.refreshHistory(true) }) { Text("Load more conversations") } }
    }
}

@Composable private fun SettingsScreen(model: VoiceViewModel, navigate: (String) -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Make it yours", color = White, fontSize = 28.sp, fontWeight = FontWeight.Medium)
        Text("A conversation that feels like you.", color = Muted, fontSize = 13.sp, modifier = Modifier.padding(bottom = 10.dp))
        SettingRow("Your account", model.email) { navigate("Account") }
        SettingRow("Conversation preferences", "Language, response style and personalization") { navigate("Preferences") }
        SettingRow("Saved memories", if (model.memoryEnabled) "Enabled" else "You choose what Aura remembers") { navigate("Memory") }
        SettingRow("Your references", "Manage notes and optional reference tools") { navigate("Knowledge") }
        SettingRow("Voice time", "Daily allowance and usage") { navigate("Usage") }
    }
}
@Composable private fun SettingRow(title: String, subtitle: String, click: () -> Unit) {
    Surface(onClick = click, color = Panel, contentColor = White, shape = RoundedCornerShape(18.dp), border = BorderStroke(1.dp, Line)) {
        Row(Modifier.fillMaxWidth().padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) { Text(title, color = White, fontSize = 16.sp); Text(subtitle, color = Muted, fontSize = 12.sp) }
            Icon(Icons.Outlined.ChevronRight, null, tint = Lilac)
        }
    }
}

@Composable private fun AccountPage(model: VoiceViewModel, back: () -> Unit) {
    FeatureLayout("Your account", "Your own space for a conversation.", back) {
        Text(model.email, color = White, fontSize = 18.sp)
        Text("Signed in", color = Cyan, fontSize = 13.sp)
        OutlinedButton(onClick = model::logout, enabled = !model.busy, modifier = Modifier.fillMaxWidth()) { Text("Sign out") }
    }
}

@Composable private fun AuthPage(model: VoiceViewModel, register: Boolean, switchPage: () -> Unit, connected: () -> Unit) {
    var email by rememberSaveable(register) { mutableStateOf("") }
    var password by remember(register) { mutableStateOf("") }
    var confirm by remember(register) { mutableStateOf("") }
    val context = LocalContext.current
    val connection = remember(context) { context.getSharedPreferences("backend_connection", Context.MODE_PRIVATE) }
    var address by rememberSaveable { mutableStateOf(connection.getString("backend_url", model.baseUrl).orEmpty()) }
    val addressValid = runCatching { normalizeBackendOrigin(address) }.isSuccess
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(horizontal = 28.dp, vertical = 36.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Icon(Icons.Outlined.GraphicEq, null, tint = Lilac, modifier = Modifier.size(42.dp))
        Text("aura", color = White, fontSize = 29.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(18.dp))
        Text(if (register) "Create your account" else "Welcome back", color = White, fontSize = 30.sp, fontWeight = FontWeight.Medium)
        Text(if (register) "A little space to think, speak and grow." else "Sign in to your space. We're glad you're here.", color = Muted, fontSize = 14.sp)
        OutlinedTextField(address, { value ->
            address = value
            runCatching { normalizeBackendOrigin(value) }.getOrNull()?.let { normalized ->
                connection.edit().putString("backend_url", normalized).apply()
            }
        }, label = { Text("Backend URL (ngrok)") }, placeholder = { Text("https://your-tunnel.ngrok-free.dev") },
            supportingText = { Text("Paste your HTTPS ngrok URL only, without /docs. This address is remembered on this device.") },
            isError = address.isNotBlank() && !addressValid, enabled = !model.busy,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(email, { email = it }, label = { Text("Email") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(password, { password = it }, label = { Text("Password") }, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), singleLine = true, modifier = Modifier.fillMaxWidth(), supportingText = { Text(if (register) "4 to 8 characters" else "Enter your account password") })
        if (register) OutlinedTextField(confirm, { confirm = it }, label = { Text("Confirm password") }, visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), singleLine = true, isError = confirm.isNotEmpty() && confirm != password, modifier = Modifier.fillMaxWidth())
        Button(onClick = { model.authenticate(address, email, password, register) { password = ""; confirm = ""; connected() } }, enabled = !model.busy && addressValid && email.contains('@') && validAuthPassword(password, register) && (!register || confirm == password), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth().height(56.dp)) {
            if (model.busy) CircularProgressIndicator(Modifier.size(20.dp), color = Ink, strokeWidth = 2.dp) else Text(if (register) "Create account" else "Sign in", fontSize = 16.sp)
        }
        TextButton(onClick = switchPage, enabled = !model.busy, modifier = Modifier.align(Alignment.CenterHorizontally)) { Text(if (register) "Already have an account? Sign in" else "New to Aura? Create an account") }
        if (register) Text("If signup is disabled on your server, use an account provided by its administrator.", color = Muted, fontSize = 12.sp)
    }
}

internal fun validAuthPassword(password: String, register: Boolean): Boolean =
    password.isNotEmpty() && password.length <= 128 && (!register || password.length in 4..8)
```


#### Android: app/src/main/java/com/example/voiceagent/ui/VoiceViewModel.kt

```kotlin
package com.example.voiceagent.ui

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.voiceagent.data.*
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

internal fun JSONArray.objects() = (0 until length()).map { getJSONObject(it) }

class VoiceViewModel : ViewModel() {
    private val repository = VoiceRepository()
    var signedIn by mutableStateOf(false); private set
    var busy by mutableStateOf(false); private set
    var stopping by mutableStateOf(false); private set
    var status by mutableStateOf("Ready when you are"); private set
    var error by mutableStateOf<String?>(null)
    var language by mutableStateOf("English and Hindi"); private set
    var detail by mutableStateOf("brief"); private set
    var goal by mutableStateOf("")
    var displayName by mutableStateOf(""); private set
    var instructions by mutableStateOf(""); private set
    var mode by mutableStateOf("general"); private set
    var memoryEnabled by mutableStateOf(false); private set
    var useTools by mutableStateOf(false)
    var toolsActive by mutableStateOf(false); private set
    var active by mutableStateOf(false); private set
    var muted by mutableStateOf(false); private set
    var holdToTalk by mutableStateOf(false); private set
    var talkHeld by mutableStateOf(false); private set
    var microphoneReady by mutableStateOf(false); private set
    var speaker by mutableStateOf(true); private set
    var level by mutableFloatStateOf(0f); private set
    var seconds by mutableIntStateOf(0); private set
    var remaining by mutableIntStateOf(0); private set
    var history by mutableStateOf(listOf<JSONObject>()); private set
    var historyNext by mutableStateOf<Int?>(null); private set
    var memories by mutableStateOf(listOf<JSONObject>()); private set
    var memoryLimit by mutableIntStateOf(20); private set
    var knowledge by mutableStateOf(listOf<JSONObject>()); private set
    var searchResults by mutableStateOf<List<JSONObject>?>(null); private set
    var sources by mutableStateOf(listOf<JSONObject>()); private set
    var usage by mutableStateOf<JSONObject?>(null); private set
    var report by mutableStateOf<JSONObject?>(null); private set
    var selectedKnowledge by mutableStateOf<JSONObject?>(null); private set
    var knowledgeNext by mutableStateOf<Int?>(null); private set
    var email by mutableStateOf(""); private set
    var baseUrl by mutableStateOf(repository.baseUrl); private set
    private var accountGeneration = 0
    private var generation = 0
    private var reportGeneration = 0
    private var currentId: String? = null
    private var timer: Job? = null
    private var transport: LiveTransport? = null
    private var foreground = true
    private var awaitingGreeting = false
    private var greetingCompletion: Job? = null
    private val audio = LiveAudio(viewModelScope, { transport?.sendAudio(it) },
        { if (active) status = it }, { message -> error = message; stop() }, { level = it }, ::onSpeechActivity)
    fun initializeAudio(context: android.content.Context) { audio.initialize(context) }
    private fun onSpeechActivity(started: Boolean) {
        if (transport?.sendActivity(started) == true && started) {
            audio.clearPlayback(); status = "Listening"
        }
    }

    private fun failure(e: Exception) {
        if (e is CancellationException) throw e
        error = when (e) {
            is ApiException -> e.message
            is IllegalArgumentException, is IllegalStateException -> e.message
            else -> "Could not reach the backend. Check your connection and try again."
        }
        if (repository.token == null && signedIn) {
            signedIn = false; accountGeneration++; terminate(); clearPersonalData()
        }
    }
    private fun work(block: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null
        viewModelScope.launch {
            try { block() } catch (e: Exception) { failure(e) } finally { busy = false }
        }
    }
    private fun applyPreferences(prefs: JSONObject) {
        language = prefs.getString("language"); detail = prefs.getString("response_detail"); goal = prefs.getString("goal")
        displayName = prefs.optString("display_name"); instructions = prefs.optString("custom_instructions")
        mode = prefs.optString("conversation_mode", "general"); memoryEnabled = prefs.optBoolean("memory_enabled")
    }
    fun authenticate(address: String, mail: String, password: String, register: Boolean, done: () -> Unit) = work {
        repository.configure(address); baseUrl = repository.baseUrl
        terminate(); repository.token = null; signedIn = false; clearPersonalData(); accountGeneration++
        repository.authenticate(mail, password, register)
        signedIn = true; email = mail.trim()
        applyPreferences(repository.request("/api/v1/users/me/preferences"))
        done(); refreshHistory(); refreshUsage()
    }
    fun savePreferences(values: JSONObject, done: () -> Unit) = work {
        applyPreferences(repository.request("/api/v1/users/me/preferences", "PATCH", values)); done()
    }
    fun changeMemoryConsent(value: Boolean) = savePreferences(JSONObject().put("memory_enabled", value)) {}
    fun setForeground(value: Boolean) {
        foreground = value
        if (!value) { updateTalkHeld(false); if (active) stop() }
    }
    fun updateHoldToTalk(value: Boolean) {
        holdToTalk = value; audio.setTalkMode(value); talkHeld = false
    }
    fun updateTalkHeld(value: Boolean) {
        talkHeld = value && holdToTalk && active && microphoneReady && !stopping && !muted && foreground
        audio.setTalkHeld(talkHeld)
    }
    private fun closeMicrophoneGate() { microphoneReady = false; updateTalkHeld(false) }

    fun start() {
        if (active || stopping || busy || !foreground) return
        work {
            check(signedIn) { "Sign in to start a conversation." }
            val session = ++generation
            reportGeneration++
            active = true; status = "Connecting"; seconds = 0; remaining = 0; report = null; sources = emptyList()
            try {
                val conversation = repository.request("/api/v1/conversations", "POST", JSONObject().put("goal", goal).put("use_tools", useTools))
                val id = conversation.getString("id")
                if (session != generation || !foreground) {
                    repository.request("/api/v1/conversations/$id/stop", "POST"); return@work
                }
                currentId = id; muted = false; audio.muted = false
                transport = LiveTransport(repository, viewModelScope, id, { message ->
                    if (session == generation) onControl(message)
                }, { bytes -> if (session == generation) audio.enqueue(bytes) }, { final ->
                    if (session == generation) finishSession(id, final)
                })
                transport?.start()
                timer = viewModelScope.launch {
                    while (isActive) { delay(1000); seconds++; if (remaining > 0) remaining-- }
                }
            } catch (e: Exception) {
                active = false; status = "Ready when you are"; timer?.cancel(); throw e
            }
        }
    }
    private fun onControl(message: JSONObject) {
        when (message.optString("type")) {
            "ready", "resumed" -> {
                closeMicrophoneGate()
                remaining = message.optDouble("remaining_seconds").toInt().coerceAtLeast(0)
                toolsActive = (message.optJSONArray("tools")?.length() ?: 0) > 0
                awaitingGreeting = message.optBoolean("greeting_pending", false)
                greetingCompletion?.cancel()
                if (!stopping && audio.resume(captureEnabled = !awaitingGreeting)) {
                    microphoneReady = !awaitingGreeting
                    status = if (awaitingGreeting) "Aura is saying hello" else "Listening"
                }
                refreshUsage()
            }
            "reconnecting" -> { closeMicrophoneGate(); greetingCompletion?.cancel(); audio.pause(); status = "Reconnecting" }
            "interrupted" -> { audio.clearPlayback(); status = "Listening" }
            "turn_complete" -> {
                if (awaitingGreeting) {
                    greetingCompletion = viewModelScope.launch {
                        audio.enableMicrophoneAfterGreeting()
                        awaitingGreeting = false
                        if (active && !stopping) { microphoneReady = true; status = "Listening" }
                    }
                } else status = "Listening"
            }
            "knowledge_sources" -> sources = (sources + (message.optJSONArray("sources")?.objects() ?: emptyList())).distinctBy { it.optString("id") + ":" + it.optInt("version") }
            "error" -> error = ApiException(message.optString("code", "session_error"), 400).message
        }
    }
    private fun finishSession(id: String, final: JSONObject?) {
        closeMicrophoneGate()
        greetingCompletion?.cancel(); awaitingGreeting = false
        audio.close(); timer?.cancel(); active = false; stopping = false; toolsActive = false; currentId = null
        transport?.dispose(); transport = null
        status = "Conversation ended"
        if (final != null) report = final
        val reportRequest = ++reportGeneration
        val account = accountGeneration
        viewModelScope.launch {
            if (final == null) {
                // Idempotent HTTP stop works even after the socket and its grace period are lost.
                try { repository.request("/api/v1/conversations/$id/stop", "POST") }
                catch (e: Exception) { if (account == accountGeneration) failure(e) }
            }
            fetchReport(id, account, reportRequest)
            if (account == accountGeneration) { refreshHistory(); refreshUsage() }
        }
    }
    fun stop() {
        closeMicrophoneGate()
        if (!active && !stopping) return
        greetingCompletion?.cancel(); awaitingGreeting = false
        audio.close(); timer?.cancel(); stopping = true; status = "Ending conversation"
        val id = currentId
        if (id == null) { generation++; active = false; stopping = false; status = "Ready when you are"; return }
        transport?.stop()
        val account = accountGeneration
        viewModelScope.launch {
            try { repository.request("/api/v1/conversations/$id/stop", "POST") }
            catch (e: Exception) { if (account == accountGeneration) failure(e) }
        }
    }
    fun toggleMute() { updateTalkHeld(false); audio.toggleMute(); muted = audio.muted }
    fun toggleSpeaker() { audio.toggleSpeaker(); speaker = audio.speaker }

    fun refreshHistory(more: Boolean = false) {
        if (!signedIn) return
        val offset = if (more) historyNext ?: return else 0
        val account = accountGeneration
        viewModelScope.launch {
            try {
                val response = repository.request("/api/v1/conversations?limit=20&offset=$offset")
                if (account != accountGeneration) return@launch
                history = ((if (more) history else emptyList()) + response.getJSONArray("items").objects()).distinctBy { it.getString("id") }
                historyNext = if (response.isNull("next_offset")) null else response.getInt("next_offset")
            } catch (e: Exception) { if (account == accountGeneration) failure(e) }
        }
    }
    fun refreshUsage() {
        if (!signedIn) return
        val account = accountGeneration
        viewModelScope.launch { try {
            val data = repository.request("/api/v1/usage/me")
            if (account == accountGeneration) usage = data
        } catch (e: Exception) { if (account == accountGeneration) failure(e) } }
    }
    fun openReport(id: String, done: () -> Unit) = work {
        val request = ++reportGeneration
        val data = repository.request("/api/v1/conversations/$id/report")
        if (request == reportGeneration) { report = data; done() }
    }
    private suspend fun fetchReport(id: String, account: Int, reportRequest: Int) {
        repeat(6) {
            if (account != accountGeneration || reportRequest != reportGeneration) return
            try {
                val data = repository.request("/api/v1/conversations/$id/report")
                if (account == accountGeneration && reportRequest == reportGeneration) report = data
                return
            } catch (e: ApiException) {
                if (e.code != "report_not_available") { if (account == accountGeneration) failure(e); return }
            } catch (_: java.io.IOException) { return }
            delay(700)
        }
    }
    fun refreshMemories() = work { loadMemories() }
    private suspend fun loadMemories() {
        val data = repository.request("/api/v1/users/me/memories")
        memories = data.getJSONArray("items").objects(); memoryEnabled = data.getBoolean("memory_enabled"); memoryLimit = data.getInt("limit")
    }
    fun saveMemory(id: String?, key: String, content: String, priority: Int, version: Int, done: () -> Unit) = work {
        val body = JSONObject().put("content", content.trim()).put("priority", priority)
        if (id == null) body.put("key", key) else body.put("expected_version", version)
        repository.request("/api/v1/users/me/memories" + (id?.let { "/$it" } ?: ""), if (id == null) "POST" else "PUT", body)
        loadMemories(); done()
    }
    fun deleteMemory(id: String?, done: () -> Unit) = work {
        repository.request("/api/v1/users/me/memories" + (id?.let { "/$it" } ?: ""), "DELETE"); loadMemories(); done()
    }
    fun refreshKnowledge() = work { loadKnowledge() }
    private suspend fun loadKnowledge(more: Boolean = false) {
        val offset = if (more) knowledgeNext ?: return else 0
        val data = repository.request("/api/v1/knowledge/entries?limit=50&offset=$offset")
        knowledge = ((if (more) knowledge else emptyList()) + data.getJSONArray("items").objects()).distinctBy { it.getString("id") }
        knowledgeNext = if (data.isNull("next_offset")) null else data.getInt("next_offset")
        searchResults = null
    }
    fun moreKnowledge() = work { loadKnowledge(true) }
    fun searchKnowledge(query: String) = work {
        if (query.isBlank()) { searchResults = null; return@work }
        val encoded = java.net.URLEncoder.encode(query.trim(), "UTF-8")
        searchResults = repository.request("/api/v1/knowledge/search?q=$encoded&limit=5").getJSONArray("items").objects()
    }
    fun openKnowledge(id: String, done: () -> Unit) = work {
        selectedKnowledge = repository.request("/api/v1/knowledge/entries/$id"); done()
    }
    fun clearSelectedKnowledge() { selectedKnowledge = null }
    fun saveKnowledge(id: String?, title: String, content: String, url: String, version: Int, done: () -> Unit) = work {
        val body = JSONObject().put("title", title.trim()).put("content", content.trim()).put("source_url", url.trim())
        if (id != null) body.put("expected_version", version)
        repository.request("/api/v1/knowledge/entries" + (id?.let { "/$it" } ?: ""), if (id == null) "POST" else "PUT", body)
        loadKnowledge(); done()
    }
    fun deleteKnowledge(id: String, done: () -> Unit) = work {
        repository.request("/api/v1/knowledge/entries/$id", "DELETE"); loadKnowledge(); done()
    }
    private fun terminate() {
        closeMicrophoneGate()
        greetingCompletion?.cancel(); awaitingGreeting = false
        generation++; reportGeneration++; transport?.dispose(); transport = null; audio.close(); timer?.cancel()
        active = false; stopping = false; currentId = null; toolsActive = false; status = "Ready when you are"
    }
    private fun clearPersonalData() {
        history = emptyList(); historyNext = null; knowledgeNext = null; memories = emptyList(); knowledge = emptyList(); searchResults = null
        sources = emptyList(); report = null; selectedKnowledge = null; usage = null; email = ""; goal = ""
        displayName = ""; instructions = ""; memoryEnabled = false; mode = "general"; useTools = false
    }
    fun logout() = work {
        closeMicrophoneGate(); audio.close(); transport?.stop()
        currentId?.let { repository.request("/api/v1/conversations/$it/stop", "POST") }
        repository.request("/api/v1/auth/logout", "POST")
        terminate(); accountGeneration++; repository.token = null; signedIn = false; clearPersonalData()
    }
    override fun onCleared() { closeMicrophoneGate(); transport?.stop(); transport?.dispose(); audio.close(); super.onCleared() }
}
```


#### Android: app/src/main/AndroidManifest.xml

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
    <application
        android:allowBackup="true"
        android:dataExtractionRules="@xml/data_extraction_rules"
        android:fullBackupContent="@xml/backup_rules"
        android:icon="@mipmap/ic_launcher"
        android:label="@string/app_name"
        android:roundIcon="@mipmap/ic_launcher_round"
        android:supportsRtl="true"
        android:theme="@style/Theme.Voiceagent">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />

                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>

</manifest>
```


#### Android: app/src/debug/AndroidManifest.xml

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:usesCleartextTraffic="true" />
</manifest>
```


#### Android: app/build.gradle.kts

```kotlin
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.compose.compiler)
}

android {
    namespace = "com.example.voiceagent"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.example.voiceagent"
        minSdk = 24
        targetSdk = 36
        versionCode = 7
        versionName = "1.4.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation("com.github.gkonovalov.android-vad:silero:2.0.10")
    implementation(platform(libs.compose.bom))
    implementation(libs.activity.compose)
    implementation(libs.compose.ui)
    implementation(libs.compose.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.okhttp)
    debugImplementation(libs.compose.tooling)
    debugImplementation(libs.compose.test.manifest)
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.test)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    testImplementation(libs.junit)
    testImplementation(libs.test.coroutines)
    testImplementation(libs.test.json)
    testImplementation(libs.test.mockwebserver)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
```


#### Android: build.gradle.kts

```kotlin
// Top-level build file where you can add configuration options common to all sub-projects/modules.
plugins {
    alias(libs.plugins.android.application) apply false
}
```


#### Android: settings.gradle.kts

```kotlin
pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}
plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven { url = uri("https://jitpack.io"); content { includeGroup("com.github.gkonovalov.android-vad") } }
    }
}

rootProject.name = "Voiceagent"
include(":app")
```


#### Android: gradle/libs.versions.toml

```toml
[versions]
agp = "9.1.1"
coreKtx = "1.17.0"
junit = "4.13.2"
junitVersion = "1.3.0"
espressoCore = "3.7.0"
appcompat = "1.8.0"
material = "1.14.0"
activity = "1.13.0"
constraintlayout = "2.2.2"
composeBom = "2025.08.01"
kotlin = "2.2.10"
lifecycle = "2.9.3"
okhttp = "4.12.0"
coroutinesTest = "1.9.0"
jsonTest = "20240303"

[libraries]
test-coroutines = { module = "org.jetbrains.kotlinx:kotlinx-coroutines-test", version.ref = "coroutinesTest" }
test-json = { module = "org.json:json", version.ref = "jsonTest" }
test-mockwebserver = { module = "com.squareup.okhttp3:mockwebserver", version.ref = "okhttp" }
compose-bom = { module = "androidx.compose:compose-bom", version.ref = "composeBom" }
activity-compose = { module = "androidx.activity:activity-compose", version.ref = "activity" }
compose-ui = { module = "androidx.compose.ui:ui" }
compose-test = { module = "androidx.compose.ui:ui-test-junit4" }
compose-test-manifest = { module = "androidx.compose.ui:ui-test-manifest" }
compose-preview = { module = "androidx.compose.ui:ui-tooling-preview" }
compose-tooling = { module = "androidx.compose.ui:ui-tooling" }
compose-material3 = { module = "androidx.compose.material3:material3" }
compose-icons = { module = "androidx.compose.material:material-icons-extended" }
lifecycle-viewmodel-compose = { module = "androidx.lifecycle:lifecycle-viewmodel-compose", version.ref = "lifecycle" }
okhttp = { module = "com.squareup.okhttp3:okhttp", version.ref = "okhttp" }
androidx-core-ktx = { group = "androidx.core", name = "core-ktx", version.ref = "coreKtx" }
junit = { group = "junit", name = "junit", version.ref = "junit" }
androidx-junit = { group = "androidx.test.ext", name = "junit", version.ref = "junitVersion" }
androidx-espresso-core = { group = "androidx.test.espresso", name = "espresso-core", version.ref = "espressoCore" }
androidx-appcompat = { group = "androidx.appcompat", name = "appcompat", version.ref = "appcompat" }
material = { group = "com.google.android.material", name = "material", version.ref = "material" }
androidx-activity = { group = "androidx.activity", name = "activity", version.ref = "activity" }
androidx-constraintlayout = { group = "androidx.constraintlayout", name = "constraintlayout", version.ref = "constraintlayout" }

[plugins]
compose-compiler = { id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }
android-application = { id = "com.android.application", version.ref = "agp" }
```


#### Android: app/src/main/res/drawable/ic_launcher_background.xml

```xml
<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <path
        android:fillColor="#3DDC84"
        android:pathData="M0,0h108v108h-108z" />
    <path
        android:fillColor="#00000000"
        android:pathData="M9,0L9,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M19,0L19,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M29,0L29,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M39,0L39,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M49,0L49,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M59,0L59,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M69,0L69,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M79,0L79,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M89,0L89,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M99,0L99,108"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,9L108,9"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,19L108,19"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,29L108,29"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,39L108,39"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,49L108,49"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,59L108,59"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,69L108,69"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,79L108,79"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,89L108,89"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M0,99L108,99"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M19,29L89,29"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M19,39L89,39"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M19,49L89,49"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M19,59L89,59"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M19,69L89,69"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M19,79L89,79"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M29,19L29,89"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M39,19L39,89"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M49,19L49,89"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M59,19L59,89"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M69,19L69,89"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
    <path
        android:fillColor="#00000000"
        android:pathData="M79,19L79,89"
        android:strokeWidth="0.8"
        android:strokeColor="#33FFFFFF" />
</vector>
```


#### Android: app/src/main/res/drawable/ic_launcher_foreground.xml

```xml
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:aapt="http://schemas.android.com/aapt"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <path android:pathData="M31,63.928c0,0 6.4,-11 12.1,-13.1c7.2,-2.6 26,-1.4 26,-1.4l38.1,38.1L107,108.928l-32,-1L31,63.928z">
        <aapt:attr name="android:fillColor">
            <gradient
                android:endX="85.84757"
                android:endY="92.4963"
                android:startX="42.9492"
                android:startY="49.59793"
                android:type="linear">
                <item
                    android:color="#44000000"
                    android:offset="0.0" />
                <item
                    android:color="#00000000"
                    android:offset="1.0" />
            </gradient>
        </aapt:attr>
    </path>
    <path
        android:fillColor="#FFFFFF"
        android:fillType="nonZero"
        android:pathData="M65.3,45.828l3.8,-6.6c0.2,-0.4 0.1,-0.9 -0.3,-1.1c-0.4,-0.2 -0.9,-0.1 -1.1,0.3l-3.9,6.7c-6.3,-2.8 -13.4,-2.8 -19.7,0l-3.9,-6.7c-0.2,-0.4 -0.7,-0.5 -1.1,-0.3C38.8,38.328 38.7,38.828 38.9,39.228l3.8,6.6C36.2,49.428 31.7,56.028 31,63.928h46C76.3,56.028 71.8,49.428 65.3,45.828zM43.4,57.328c-0.8,0 -1.5,-0.5 -1.8,-1.2c-0.3,-0.7 -0.1,-1.5 0.4,-2.1c0.5,-0.5 1.4,-0.7 2.1,-0.4c0.7,0.3 1.2,1 1.2,1.8C45.3,56.528 44.5,57.328 43.4,57.328L43.4,57.328zM64.6,57.328c-0.8,0 -1.5,-0.5 -1.8,-1.2s-0.1,-1.5 0.4,-2.1c0.5,-0.5 1.4,-0.7 2.1,-0.4c0.7,0.3 1.2,1 1.2,1.8C66.5,56.528 65.6,57.328 64.6,57.328L64.6,57.328z"
        android:strokeWidth="1"
        android:strokeColor="#00000000" />
</vector>
```


#### Android: app/src/main/res/layout/activity_main.xml (starter resource, not the active Compose UI)

```xml
<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    xmlns:tools="http://schemas.android.com/tools"
    android:id="@+id/main"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    tools:context=".MainActivity">

    <TextView
        android:layout_width="wrap_content"
        android:layout_height="wrap_content"
        android:text="Hello World!"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintTop_toTopOf="parent" />

</androidx.constraintlayout.widget.ConstraintLayout>
```


#### Android: app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml

```xml
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
    <monochrome android:drawable="@drawable/ic_launcher_foreground" />
</adaptive-icon>
```


#### Android: app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml

```xml
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground" />
    <monochrome android:drawable="@drawable/ic_launcher_foreground" />
</adaptive-icon>
```


#### Android: app/src/main/res/values/colors.xml

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="black">#FF000000</color>
    <color name="white">#FFFFFFFF</color>
</resources>
```


#### Android: app/src/main/res/values/strings.xml

```xml
<resources>
    <string name="app_name">Aura</string>
</resources>
```


#### Android: app/src/main/res/values/themes.xml

```xml
<resources>
    <style name="Base.Theme.Voiceagent" parent="Theme.Material3.DayNight.NoActionBar">
        <item name="android:windowBackground">#080A12</item>
        <item name="android:statusBarColor">#080A12</item>
        <item name="android:navigationBarColor">#080A12</item>
        <item name="android:windowLightStatusBar">false</item>
        <item name="colorPrimary">#B5A5FF</item>
    </style>
    <style name="Theme.Voiceagent" parent="Base.Theme.Voiceagent" />
</resources>
```


#### Android: app/src/main/res/values-night/themes.xml

```xml
<resources>
    <style name="Base.Theme.Voiceagent" parent="Theme.Material3.DayNight.NoActionBar">
        <item name="android:windowBackground">#080A12</item>
        <item name="android:statusBarColor">#080A12</item>
        <item name="android:navigationBarColor">#080A12</item>
        <item name="android:windowLightStatusBar">false</item>
        <item name="colorPrimary">#B5A5FF</item>
    </style>
    <style name="Theme.Voiceagent" parent="Base.Theme.Voiceagent" />
</resources>
```


#### Android: app/src/main/res/xml/backup_rules.xml

```xml
<?xml version="1.0" encoding="utf-8"?><!--
   Sample backup rules file; uncomment and customize as necessary.
   See https://developer.android.com/guide/topics/data/autobackup
   for details.
   Note: This file is ignored for devices older than API 31
   See https://developer.android.com/about/versions/12/backup-restore
-->
<full-backup-content>
    <!--
   <include domain="sharedpref" path="."/>
   <exclude domain="sharedpref" path="device.xml"/>
-->
</full-backup-content>
```


#### Android: app/src/main/res/xml/data_extraction_rules.xml

```xml
<?xml version="1.0" encoding="utf-8"?><!--
   Sample data extraction rules file; uncomment and customize as necessary.
   See https://developer.android.com/about/versions/12/backup-restore#xml-changes
   for details.
-->
<data-extraction-rules>
    <cloud-backup>
        <!-- TODO: Use <include> and <exclude> to control what is backed up.
        <include .../>
        <exclude .../>
        -->
    </cloud-backup>
    <!--
    <device-transfer>
        <include .../>
        <exclude .../>
    </device-transfer>
    -->
</data-extraction-rules>
```


#### Backend: app/schemas/auth.py

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class BaseCredentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr = Field(max_length=254)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower()


class RegistrationCredentials(BaseCredentials):
    password: SecretStr = Field(
        min_length=4, max_length=8,
        description='New account password; must contain 4 to 8 characters.',
    )


class LoginCredentials(BaseCredentials):
    # Keep the historical upper bound so accounts created under the former
    # 12-128 character registration policy can continue to authenticate.
    password: SecretStr = Field(
        min_length=1, max_length=128,
        description='Account password. Legacy passwords longer than 8 characters remain valid.',
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_at: datetime


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    created_at: datetime
```


#### Backend: app/schemas/preferences.py

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal['English', 'Hindi', 'English and Hindi']
ResponseDetail = Literal['brief', 'detailed']
ConversationMode = Literal['general', 'english_practice', 'interview_practice']


class PreferencesPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Language | None = None
    response_detail: ResponseDetail | None = None
    goal: str | None = Field(default=None, max_length=500)
    display_name: str | None = Field(default=None, max_length=80)
    custom_instructions: str | None = Field(default=None, max_length=1000)
    conversation_mode: ConversationMode | None = None
    memory_enabled: bool | None = None

    @field_validator('goal', 'display_name', 'custom_instructions')
    @classmethod
    def supported_text(cls, value):
        if value is not None and '\x00' in value:
            raise ValueError('Null characters are not supported')
        return value


class PreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language: Language
    response_detail: ResponseDetail
    goal: str
    display_name: str
    custom_instructions: str
    conversation_mode: ConversationMode
    memory_enabled: bool
    updated_at: datetime
```


#### Backend: app/schemas/memory.py

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def meaningful_content(value):
    value = value.strip()
    if not value:
        raise ValueError('Memory content cannot be blank')
    if '\x00' in value:
        raise ValueError('Null characters are not supported')
    return value


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str = Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_]*$')
    content: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=50, ge=0, le=100)

    _content = field_validator('content')(meaningful_content)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=50, ge=0, le=100)
    expected_version: int = Field(ge=1)

    _content = field_validator('content')(meaningful_content)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    key: str
    content: str
    priority: int
    version: int
    created_at: datetime
    updated_at: datetime


class MemoryList(BaseModel):
    items: list[MemoryResponse]
    memory_enabled: bool
    limit: int
```


#### Backend: app/schemas/knowledge.py

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator


class KnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=6000)
    source_url: str = Field(default='', max_length=1000)

    @field_validator('title', 'content')
    @classmethod
    def meaningful_text(cls, value):
        value = value.strip()
        if not value or '\x00' in value:
            raise ValueError('Provide nonblank text without null characters')
        return value

    @field_validator('source_url')
    @classmethod
    def citation_url(cls, value):
        if not value:
            return ''
        parsed = str(TypeAdapter(HttpUrl).validate_python(value))
        if len(parsed) > 1000:
            raise ValueError('Source URL is too long')
        return parsed


class KnowledgeUpdate(KnowledgeCreate):
    expected_version: int = Field(ge=1)


class SharedKnowledgeCreate(KnowledgeCreate):
    published: bool = False


class SharedKnowledgeUpdate(SharedKnowledgeCreate):
    expected_version: int = Field(ge=1)


class KnowledgeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID | None
    title: str
    source_url: str
    published: bool
    version: int
    created_at: datetime
    updated_at: datetime


class KnowledgeResponse(KnowledgeSummary):
    content: str


class KnowledgePage(BaseModel):
    items: list[KnowledgeSummary]
    next_offset: int | None


class KnowledgeHit(BaseModel):
    id: UUID
    title: str
    source_url: str
    version: int
    excerpt: str
    offset: int


class KnowledgeSearch(BaseModel):
    items: list[KnowledgeHit]


class SearchKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=3, ge=1, le=5)


class ReadKnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    entry_id: str = Field(min_length=36, max_length=36)
    expected_version: int = Field(ge=1)
    offset: int = Field(default=0, ge=0, le=6000)
    max_chars: int = Field(default=800, ge=1, le=1000)

    @field_validator('entry_id')
    @classmethod
    def valid_uuid(cls, value):
        UUID(value)
        return value


class EmptyToolArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
```


#### Backend: app/schemas/conversations.py

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goal: str | None = Field(default=None, max_length=500)
    use_tools: bool = False


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    prompt_version: str
    preferences_snapshot: dict
    configuration_snapshot: dict
    configuration_fingerprint: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None


class ConversationPage(BaseModel):
    items: list[ConversationResponse]
    next_offset: int | None
```


#### Backend: app/schemas/usage.py

```python
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UsageStatus(BaseModel):
    usage_date: date
    connected_seconds: float
    reserved_seconds: float
    available_seconds: float
    daily_connected_seconds: int
    estimated_cost_usd: Decimal
    reserved_cost_usd: Decimal
    daily_estimated_cost_limit_usd: Decimal | None
    cost_guard_enabled: bool
    sessions_started: int
    sessions_settled: int
    incomplete_cost_sessions: int
    resets_at: datetime


class AdminUsageRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: UUID
    usage_date: date
    connected_seconds: Decimal
    reserved_seconds: Decimal
    estimated_cost_usd: Decimal
    reserved_cost_usd: Decimal
    sessions_started: int
    sessions_settled: int
    incomplete_cost_sessions: int
    updated_at: datetime


class AdminUsagePage(BaseModel):
    items: list[AdminUsageRow]
    next_offset: int | None
```


#### Backend: app/schemas/live.py

```python
"""Validated client messages for the live WebSocket protocol."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class StartMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['start']
    language: Literal['English', 'Hindi', 'English and Hindi'] = 'English and Hindi'
    goal: str = Field(default='', max_length=500)


class AuthenticatedStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['start']
    conversation_id: UUID
    speech_detection: Literal['server', 'client'] = 'server'
    access_token: SecretStr | None = Field(default=None, max_length=128)
```

