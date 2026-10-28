#!/bin/sh
# run hython from an empty cwd with a private prefs dir (round D)
D="/c/Users/jujun/AppData/Local/Temp/claude/C--Users-jujun-DEV-hocus-pocus/d956ad22-ff1d-47a8-a6c1-b1930b7bee4a/scratchpad/roundD"
cd "$D/cwd" && HOUDINI_USER_PREF_DIR="$D/prefs/houdini__HVER__" "/c/Program Files/Side Effects Software/Houdini 22.0.466/bin/hython.exe" "$@" 2>&1 | grep -v "sidefx_transform2d"
