#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
apk="$script_dir/app/build/outputs/apk/debug/app-debug.apk"

if [[ ! -f "$apk" ]]; then
    echo "APK não encontrado em $apk. Execute ./build_apk.sh primeiro."
    exit 1
fi

echo "Verificando dispositivo via ADB..."
adb wait-for-device
echo "Instalando $apk no aparelho..."
adb install -r "$apk"
echo "Iniciando aplicativo no aparelho..."
adb shell am start -n com.al4xdev.h3mock/com.al4xdev.h3.ui.MainActivity
echo "Sucesso! H3 Mobile oficial está ativo no aparelho."
