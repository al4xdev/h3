---
name: android-gesture-nav
description: Reproduce in another Android app (Kotlin + Jetpack Compose) the H3 Studio navigation — fullscreen without a Back button, iOS-style interactive swipe to go back AND forward, integrated with system predictive back gesture, preserving per-screen state. Use when asked for "app with H3 navigation/fluidity", "iPhone-style gesture back", "swipe back/forward in Compose", or to resolve gesture conflicts with sliders, players, or text fields.
---

# iOS-Style Gesture Navigation (Compose) — H3 Studio Recipe

The reference code is in this repository. **Copy the pattern, not the H3 screens.**
All paths below are relative to `mobile_app/app/src/main/java/com/al4xdev/h3/`.

| File | What to copy |
|---|---|
| `ui/gestures/FullscreenWorkspace.kt` | the container: two layers, drag, spring, predictive back, touch interception during animation |
| `ui/gestures/WorkspaceGesturePolicy.kt` | pure (testable) rules: start bounds, axis, decision on release, exclusions |
| `ui/Nav.kt` | `NavStack` with back **and** forward stacks, serialized to text |
| `ui/MainActivity.kt` | per-screen `rememberSaveableStateHolder` + container wiring |
| `ui/components/Motion.kt` | `pressScale` (press 0.97) and `appearOnce` (item entrance) |
| `ui/components/Tiles.kt` → `reducedMotion()` | respect Android "remove animations" |
| `app/src/test/.../ui/NavStackTest.kt`, `ui/gestures/GesturePolicyTest.kt` | JVM unit tests of the rules |

Requirements: `minSdk 34`, `androidx.activity:activity-compose` ≥ 1.8 (`PredictiveBackHandler`),
and in `AndroidManifest.xml`, within the `<application>` tag: `android:enableOnBackInvokedCallback="true"`.

## How It Works (The Mental Model)

1. **A back stack and a forward stack** (`NavStack`).
   - `push(screen)` clears the forward stack, **unless** the screen is exactly the next forward screen.
   - `pop()` moves the top to the forward stack. `goForward()` does the inverse.
   - Both stacks are serialized as short text (`"lib|rot:<uuid>|blk:<uuid>:<uuid>"`)
     in a ViewModel `SavedStateHandle` to survive process death.
2. **Each screen has its state saved** with `rememberSaveableStateHolder()`, keyed by the
   encoded screen. State is only discarded when the screen leaves BOTH stacks (`liveKeys()`).
   Therefore, navigating back and forward restores scroll position, typed text, and video playback position.
3. **The container renders two layers**: `under` (bottom screen) and `over` (moving screen).
   A single variable `t` in [0,1] drives everything:
   - `over.translationX = t * width` (tracks finger 1:1);
   - `under.translationX = -0.30 * width * (1 - t)` (parallax);
   - black scrim over `under` with `alpha = 0.25 * (1 - t)`;
   - 24 dp shadow along the left edge of `over`.
   Going back animates `t` from 0 → 1; going forward animates from 1 → 0 (new screen slides in from right).
4. **The same screen preserves composition across layer swaps**: render both layers at the
   same call site using `key(screenKey) { ... }`. Without this, the screen is recreated at the end of the gesture and flickers.
5. **Three origins, identical geometry**:
   - app-level drag (left zone = back, right zone = forward);
   - system gesture via `PredictiveBackHandler` (uses `BackEventCompat.swipeEdge` and `progress`);
   - button tap / push (350 ms animation, easing `CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)`).

## Numbers That Define the Feel (Do Not Invent Others)

| Parameter | Value |
|---|---|
| Drag start zone | 45% of width (left for back, right for forward) |
| Horizontal recognition | exceeded `touchSlop` AND `dx ≥ 1.25 × |dy|`; if vertical, aborts (lets list scroll) |
| Complete on release | velocity ≥ 500 dp/s with dx ≥ 16 dp; OR dragged ≥ 40% of width |
| Cancel on release | velocity ≤ −300 dp/s (flung back) |
| Settling spring | `spring(dampingRatio = 1f, stiffness = Spring.StiffnessMedium)` with finger velocity |
| Parallax / scrim | 30% / alpha 0.25 |
| Tap push/pop | 350 ms, emphasized decelerate |
| Card press | scale 0.97, `spring(0.6f, StiffnessMedium)`, visual only (hit target does not shrink) |
| Item entrance | fade + 12 dp slide-up over 240 ms, once per item |

## Step-by-Step Recipe for a New App

1. Copy `WorkspaceGesturePolicy.kt` and `FullscreenWorkspace.kt` without changing logic.
   The container is generic (`FullscreenWorkspace<T>`): receives `stack`, `nextForward`, `keyOf`,
   `onBack`, `onForward`, and content per screen.
2. Create your `sealed interface Screen` and a `NavStack` identical to `ui/Nav.kt`
   (adjusting only screen types and `encode`/`decode`).
3. In ViewModel: hold `NavStack` in observable state and persist `Nav.encode(back)` and
   `Nav.encode(forward)` to `SavedStateHandle` on every change. `back()` = `pop()`, `forward()` = `goForward()`.
4. At root (such as `H3Root` in `MainActivity.kt`):
   - `val holder = rememberSaveableStateHolder()`;
   - `FullscreenWorkspace(...) { screen -> holder.SaveableStateProvider(Nav.key(screen)) { Content(screen) } }`;
   - a `LaunchedEffect(liveKeys)` calling `holder.removeState` for keys that left both stacks.
5. Manifest: `enableOnBackInvokedCallback="true"`. **Do not** use standard `BackHandler` alongside it:
   the container's `PredictiveBackHandler` already handles system back and 3-button navigation.
6. On every control with its own horizontal drag, apply `Modifier.noSwipeBack()`:
   - `Slider`;
   - seekbar / player control bar (only bottom band of ~88 dp, not whole video);
   - text fields **only while focused**: `.onFocusChanged { focused = it.isFocused }.noSwipeBack { focused }`;
   - fast-scroll handle and horizontal carousels.
7. No screen has a Back button. Top bar has only title (and settings icon, if applicable).
8. Respect `reducedMotion()`: disable parallax with instant transitions, but gesture interaction remains functional.

## Pitfalls That Already Happened — Do Not Repeat

- **Black background behind dragged screen**: initial version only translated top screen.
   Must draw REAL prior screen underneath (`under` layer).
- **Forward swipe from right edge triggered back**: on Android gesture navigation, BOTH edges are
   system "back", and system intercepts touch before app. Solution is
   `PredictiveBackHandler` + `swipeEdge == EDGE_RIGHT` → forward (if stack available); otherwise, back.
- **Gesture failed over text fields and video**: excluding fields everywhere and full
   video left forms unable to navigate back. Only exclude controls with real drag and
   focused fields. Intercept touches in `PointerEventPass.Initial` (before children), otherwise a
   greedy video surface will block gesture detection.
- **Double back on rapid fling**: while animating (`busy`), swallow touches with
   an overlay layer and reject new gestures until settled.
- **Mutating stack during composition** (e.g. `removeAt` inside a `when`) causes screens to
   disappear spontaneously. Navigation belongs only in callbacks/effects.
- **Creating player (ExoPlayer) during composition** leaks resources. Create inside `DisposableEffect`.
- **Known limitation**: on root screen, if forward stack exists, left-edge back
   does not exit app. If undesirable, handle back on root as "exit" and clear forward stack.

## Verification Checklist

1. JVM rule tests (copy and adapt `NavStackTest.kt` and `GesturePolicyTest.kt`):
   push clears forward; pop/goForward symmetrical; dx/velocity dictate complete/cancel;
   vertical drag does not trigger gesture; touch on excluded region does not start gesture.
2. In emulator within Docker in this repo (`mobile_app/docker/`, see `box.sh`):
   ```bash
   zdocker exec h3-android box build && zdocker exec h3-android box install
   zdocker exec h3-android box swipe 20 1200 900 1200 250    # back from edge
   zdocker exec h3-android box swipe 850 1500 100 1500 300   # forward from right zone
   zdocker exec h3-android box screenshot post-gesture
   ```
   Verify: previous screen appears underneath, scroll and inputs restore identically, slider and
   player bar do not fire the navigation gesture.
3. Genuine fluidity can only be evaluated on a physical device; emulators render at low frame rates.
