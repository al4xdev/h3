#!/usr/bin/env bash
# Fixed in-container commands for the Android app workbench.
#
# Runs INSIDE the h3-android container (zdocker exec h3-android box <cmd>):
# gradle, adb, the headless emulator and the H3 backend all live there. No
# port is published; the emulator reaches the in-container backend through
# 10.0.2.2. ComfyUI points at a closed port, so a stray tap in the app can
# never start a real GPU job. Keep subcommands fixed: no "run anything".
set -euo pipefail

APP_ID="com.al4xdev.h3mock"
AVD="h3"
SYSTEM_IMAGE="system-images;android-36;google_apis;x86_64"
APK="/workspace/mobile_app/app/build/outputs/apk/debug/app-debug.apk"
SHOT_DIR="/workspace/.dumps/android"

die() { echo "box: $*" >&2; exit 2; }
int() { [[ "$1" =~ ^[0-9]{1,5}$ ]] || die "not a small integer: $1"; }
# Root writes into the bind-mounted repo go back to the repo owner.
give_back() { chown -R --reference=/workspace "$@" 2>/dev/null || true; }

usage() {
    cat <<'EOF'
uso: zdocker exec h3-android box <comando>

  build | unit-test      gradle assembleDebug | testDebugUnitTest
  emu-start | emu-stop   emulador headless (cria o AVD na primeira vez)
  backend-start [demo]   backend H3 em 127.0.0.1:8888 (ComfyUI desligado de propósito);
                         "demo" semeia e usa /cache/demo em vez do repo
  backend-stop
  backend-log [linhas]
  install                instala o APK e abre o app
  launch | stop-app
  screenshot <nome>      grava .dumps/android/<nome>.png no repo
  record <nome> [s]      grava a tela (até 60 s) em .dumps/android/<nome>.mp4
  ui-dump                hierarquia de UI (uiautomator) em XML
  logcat [linhas]
  tap <x> <y>
  swipe <x1> <y1> <x2> <y2> [ms]
  text <texto>           só [A-Za-z0-9 .,!?:/_-]
  key back|home|enter|tab|del|end [vezes]
EOF
}

cmd="${1:-}"; shift || true
case "$cmd" in
build|unit-test)
    task=assembleDebug; [[ "$cmd" == unit-test ]] && task=testDebugUnitTest
    status=0
    (cd /workspace/mobile_app && gradle "$task" --console=plain) || status=$?
    give_back /workspace/mobile_app/app/build /workspace/mobile_app/.gradle /workspace/mobile_app/build /workspace/mobile_app/.kotlin
    exit $status
    ;;
emu-start)
    [[ -d "$ANDROID_AVD_HOME/$AVD.avd" ]] || echo no | avdmanager create avd -n "$AVD" -k "$SYSTEM_IMAGE" -d pixel_7 >/dev/null
    if ! pgrep -f "qemu.*-avd $AVD" >/dev/null; then
        nohup emulator -avd "$AVD" -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect \
            -no-snapshot-save >/cache/emulator.log 2>&1 &
    fi
    adb wait-for-device
    for _ in $(seq 1 180); do
        [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]] && { echo "emulador pronto"; exit 0; }
        sleep 2
    done
    die "emulador não terminou o boot (veja /cache/emulator.log)"
    ;;
emu-stop)
    adb emu kill || true
    ;;
backend-start)
    pgrep -f "uvicorn h3_backend.api:app" >/dev/null && { echo "backend já rodando"; exit 0; }
    # venv in the cache volume keeps root-owned files out of the repo.
    export UV_PROJECT_ENVIRONMENT=/cache/venv PYTHONDONTWRITEBYTECODE=1 H3_COMFY_URL=http://127.0.0.1:9
    cd /workspace
    uv sync --frozen >/cache/backend.log 2>&1
    # "demo" serves a seeded project root kept in the cache volume, never the repo's .data.
    if [[ "${1:-}" == demo ]]; then
        if [[ ! -d /cache/demo ]]; then
            uv run --no-sync python tools/seed_demo_data.py --root /cache/demo >>/cache/backend.log 2>&1
        fi
        export H3_PROJECT_ROOT=/cache/demo
    fi
    nohup uv run --no-sync uvicorn h3_backend.api:app --host 127.0.0.1 --port 8888 >>/cache/backend.log 2>&1 &
    for _ in $(seq 1 120); do
        curl -sf -o /dev/null http://127.0.0.1:8888/app/config && { echo "backend pronto"; exit 0; }
        sleep 1
    done
    tail -20 /cache/backend.log >&2; exit 1
    ;;
backend-stop)
    pkill -f "uvicorn h3_backend.api:app" && echo parado || echo "não estava rodando"
    ;;
backend-log)
    lines="${1:-80}"; int "$lines"; tail -n "$lines" /cache/backend.log
    ;;
install)
    [[ -f "$APK" ]] || die "APK ausente; rode build"
    adb install -r "$APK"
    adb shell monkey -p "$APP_ID" -c android.intent.category.LAUNCHER 1 >/dev/null && echo "instalado e aberto"
    ;;
launch)
    adb shell monkey -p "$APP_ID" -c android.intent.category.LAUNCHER 1 >/dev/null && echo aberto
    ;;
stop-app)
    adb shell am force-stop "$APP_ID" && echo encerrado
    ;;
screenshot)
    name="${1:-}"; [[ "$name" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]] || die "nome inválido (use a-z0-9-)"
    mkdir -p "$SHOT_DIR"
    adb exec-out screencap -p >"$SHOT_DIR/$name.png"
    give_back /workspace/.dumps
    echo ".dumps/android/$name.png"
    ;;
record)
    # Screen video for judging motion/transitions; frames are analysed with ffmpeg in here.
    name="${1:-}"; [[ "$name" =~ ^[a-z0-9][a-z0-9-]{0,63}$ ]] || die "nome inválido (use a-z0-9-)"
    secs="${2:-10}"; int "$secs"; (( secs <= 60 )) || die "máximo 60 s"
    mkdir -p "$SHOT_DIR"
    adb shell screenrecord --time-limit "$secs" /sdcard/h3-rec.mp4
    adb pull /sdcard/h3-rec.mp4 "$SHOT_DIR/$name.mp4" >/dev/null
    give_back /workspace/.dumps
    echo ".dumps/android/$name.mp4"
    ;;
ui-dump)
    adb shell uiautomator dump /sdcard/h3-ui.xml >/dev/null && adb exec-out cat /sdcard/h3-ui.xml
    ;;
logcat)
    lines="${1:-300}"; int "$lines"
    pid="$(adb shell pidof "$APP_ID" | tr -d '\r' || true)"
    if [[ -n "$pid" ]]; then adb logcat -d -t "$lines" --pid="$pid"; else adb logcat -d -t "$lines" AndroidRuntime:E '*:S'; fi
    ;;
tap)
    [[ $# -eq 2 ]] || die "tap <x> <y>"; int "$1"; int "$2"
    adb shell input tap "$1" "$2"
    ;;
swipe)
    [[ $# -ge 4 && $# -le 5 ]] || die "swipe <x1> <y1> <x2> <y2> [ms]"
    for v in "$@"; do int "$v"; done
    adb shell input swipe "$@"
    ;;
text)
    t="$*"; [[ "$t" =~ ^[A-Za-z0-9\ .,!?:/_-]{1,200}$ ]] || die "texto fora do conjunto permitido"
    adb shell input text "'${t// /%s}'"
    ;;
key)
    case "${1:-}" in
        back) k=4 ;; home) k=3 ;; enter) k=66 ;; tab) k=61 ;; del) k=67 ;; end) k=123 ;;
        *) die "key back|home|enter|tab|del|end [vezes]" ;;
    esac
    times="${2:-1}"; int "$times"
    # One adb call with repeated codes; used to clear text fields.
    adb shell input keyevent $(for _ in $(seq 1 "$times"); do printf '%s ' "$k"; done)
    ;;
""|-h|--help|help) usage ;;
*) usage >&2; exit 2 ;;
esac
