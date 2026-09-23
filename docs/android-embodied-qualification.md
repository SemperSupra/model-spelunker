# Android embodied actor qualification

Authority: `SemperSupra/agent-dispatch-private#297`. Public work item: `SemperSupra/model-spelunker#89`.

This lane reuses the existing Model Spelunker configured-actor qualification kernel and the Android API 35 / KVM placement evidence from Agent Dispatch. It does not introduce a mobile benchmark service.

## First task

`android-settings-24h-struct-v0` asks one actor to enable Android's 24-hour time format through the ordinary Settings UI.

Actor-visible capabilities are deliberately smaller than verifier capabilities:

| Actor | Independent verifier |
| --- | --- |
| bounded UI hierarchy | direct final system-setting query |
| tap / swipe / back | emulator reset/initialization |
| launch Settings home | task truth |
| declared result-file write | receipt acceptance |

The actor receives no generic shell, generic ADB, `settings get`, `dumpsys`, app-private files, or verifier truth.

## Calibration

Every hosted rep is preceded on the same emulator by a deterministic reference policy using the same structural observation/action primitives. Hosted inference is not attempted unless this calibration passes the unchanged task verifier. This separates task/UI drift from actor competence.

## Evidence identity

Result-affecting dimensions remain separate:

`actor configuration × task × observation channel × action channel × language × substrate`.

In particular, structural UI evidence does not qualify screenshot grounding, and emulator evidence does not qualify a physical device.

## Next earned crossover

Only after the structural task is calibrated and one actor observation is reconciled, add a second profile that exposes exactly one bounded shortcut:

`mobile_open_section(section="date_time")`.

The task and final oracle remain unchanged. This tests whether the actor discovers/selects an available shortcut without exposing arbitrary intents or shell authority.

Multilingual UI, speech-mediated reasoning, TTS, translation, image generation, and iOS remain later earned lanes under #297.
