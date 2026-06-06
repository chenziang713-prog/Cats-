# Android Roadmap

The desktop prototype should prove the recognition and rule model before an
Android app is created.

## Target Android Components

- Kotlin Android app as the main client.
- MediaProjection for user-approved screen capture.
- AccessibilityService for user-approved taps, swipes, and back actions.
- Foreground service plus notification for visible runtime control.
- Floating pause/stop control for immediate user override.

## Migration Strategy

1. Keep visual templates and flow rules platform neutral.
2. Port the rule engine concepts from Python to Kotlin.
3. Replace desktop screen capture with MediaProjection frames.
4. Replace desktop action execution with AccessibilityService gestures.
5. Add Android-specific permission onboarding and safety warnings.

## Compliance Boundary

Automation must only run in owned, test, or explicitly authorized environments.
The Android version should not skip ads, fake ad views, tamper with ad SDKs, or
attempt to bypass anti-cheat systems.

