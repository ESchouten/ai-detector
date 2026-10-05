# Onboarding flow review

Reviewed 30 September 2026, after consolidating camera and detector editing into Settings. The web app has since been reorganized: setup is first-run guidance only, and cameras and detectors have their own pages. File paths below describe that earlier layout.

## Current flow

1. **Cameras.** A fresh installation opens discovery directly. Select a discovered camera and enter its login, or use manual stream entry. Connect to check its picture and recording, then save. The camera overview keeps the live preview cards and offers another camera or the next step. Existing installations can be imported from this step.
2. **Detectors.** With no saved detectors, the form opens immediately. Choose a preset, select cameras with live previews, optionally connect Telegram or a Validator, and save. Both connection dialogs preserve the unsaved detector. The overview allows additional detectors or continuing to finish setup.
3. **Finish setup.** Recording locations are checked automatically. Currently, users without phone alerts must explicitly skip them before starting monitoring. Verified monitoring opens Recordings. Viewing-only setup opens Cameras.

Later changes use the same Settings steps and forms. Live Cameras shortcuts open the selected camera or detector step. Old editor URLs redirect, including saved item identifiers. There is no separate detector management screen anymore.

This removes two initial “open the editor” detours and keeps one consistent location for camera and detector configuration. It does not yet remove every unnecessary decision inside those steps.

## Highest-value remaining improvements

| Priority | Observed friction                                                                                                                                                       | Recommended change                                                                                                                                                                                                       |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1        | Phone alerts are optional in the detector form but requested again at the finish step. Start is disabled until users connect them or choose Skip.                       | Make the detector's saved selection authoritative. No assigned recipient means no phone alerts. Show that status once at the finish step, with an Edit shortcut; do not require another choice.                          |
| 1        | Reopening the application goes to Recordings as soon as any detector exists, even if guided setup was not finished.                                                     | Resume unfinished guided setup on reopening. Distinguish installations that already work from newly started setup, so established users are not forced through onboarding.                                               |
| 1        | Step links can leave an unsaved detector form. The draft survives its connection dialogs but not leaving the step.                                                      | Warn only when there are actual unsaved changes. Preserve explicit saving; avoid adding autosave and draft-restoration flows alongside it.                                                                               |
| 1        | Adding a second Gemini connection uses the same hidden default name, “Google Gemini”; the store rejects duplicates and the new-connection form cannot change that name. | Reuse the existing connection by default. If another account is needed, create a unique default name or expose a name only for that case.                                                                                |
| 2        | Single-camera and multiple-camera setup remain separate modes. Users must decide which mode to enter before connecting.                                                 | Use one discovery list supporting one or several selections, retaining the current per-camera previews, channel choices and retry behavior. Keep manual entry as an explicit secondary button.                           |
| 2        | Detector name is presented before the preset that can generate it. A single available camera still needs explicit selection.                                            | Put the preset first, retain its generated name unless changed, and preselect the only camera. Keep multi-camera selection explicit.                                                                                     |
| 2        | The finish step has both a runtime panel and a camera-check panel. Saved-item overviews also add a Continue click after every initial save.                             | Use one concise readiness summary with one primary action. Consider “Save and continue” for the initial item, while keeping “Add another” easy to reach. Validate this with farmers before removing the useful overview. |
| 3        | First-time setup shows the whole sidebar, including Advanced and Logs. Validator is called “AI verification” and “AI connection” inside the form.                       | Keep Settings prominent during onboarding, put support destinations in the background, and use consistent Validator terminology. Keep the JSON editor available for deliberate advanced changes.                         |

The first four items address blocked or lost progress. They matter more than removing another button or shortening descriptions.

## Connections and automation

Telegram already reuses a saved bot for another recipient and offers Telegram's group/channel selection. The separately hosted bot-creation manager is optional and still needs an actual deployment and configured URL before token-free creation is available. The fallback remains BotFather token entry. Adding more client-side instructions will not remove that external setup step.

Google connection already combines testing and saving after the user pastes a key. Reusing that connection is the useful next simplification; it should not be necessary to reconnect Google for each detector. Presets continue to supply the validation prompt, with custom prompts in Advanced.

Keep discovery, connection tests and recording checks automatic. Keep camera assignment, preset choice and sending images to an external Validator deliberate.

## Evidence and limits

Browser verification used the production build, isolated data directories, a synthetic local camera clip, and a detector status fixture. The Browser plugin was unavailable, so the Playwright skill's CLI fallback was used.

Verified: first-run discovery, manual connection and real FFmpeg recording checks, camera save/rename, direct first-detector editing, preset selection, camera selection, Telegram dialog cancellation without losing the draft, inline Validator connection saving and assignment, detector save/reopen, both finish destinations, old-link redirects, and desktop/mobile layout. Batch testing used mocked discovery and one connection failure, with real recording checks and configuration saves; the first successful save left the remaining camera available for retry.

Google's test call was mocked and no Telegram messages were sent. This verifies the application flow, not either external service or real model inference. Browser console errors were limited to preview connections ending when the finite test clip finished; no application JavaScript exceptions or framework error overlays appeared. Detector layout at 390 px had no horizontal overflow.

Automated checks: 287 web tests passed, one skipped; all 10 production tests passed; production build, Svelte checks, ESLint, formatting and dependency boundaries passed. Production coverage includes first-editor redirects, URL-encoded old bookmarks, missing selections, preset loading, editing despite an invalid preset, configuration preservation, and origin checks.

## Implementation references

- `src/routes/(admin)/setup/`: step navigation, explicit editor selection, initial form redirects and item overviews.
- `src/lib/components/camera-editor.svelte` and `detector-editor.svelte`: reusable forms; completion returns to Settings.
- `src/lib/components/setup-review.svelte`: finish checks, repeated alert choice and final destination.
- `src/routes/(admin)/+page.server.ts`: application reopening decision.
- `src/lib/components/llm-connection-editor.svelte` and `src/lib/server/configuration/llms.ts`: default connection naming and duplicate validation.
- `src/lib/components/camera-batch.svelte`: multi-camera selection, partial saves and retry.
