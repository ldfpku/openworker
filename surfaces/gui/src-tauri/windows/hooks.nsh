; NSIS installer hooks for OpenWorker (wired via bundle.windows.nsis.installerHooks).
;
; Why this exists: Tauri's generated installer only checks for / kills the *main* binary
; (CheckIfAppIsRunning "${MAINBINARYNAME}.exe"). OpenWorker also runs a Python sidecar,
; sidecar\openworker-server.exe, which keeps its exe, python312.dll and every loaded .pyd
; open. If it is still alive when the installer reaches those files, the File steps fail
; (the "error during installation" the user sees), the rest of the payload is still
; written, and the result is a new GUI driving an OLD sidecar — exactly what shipped as
; "1.0.6 installed, gateway still sees openworker/1.0.5". The in-app updater also stops
; the sidecar itself (stop_sidecar in lib.rs) before launching this installer; this hook
; covers manual installs over a running app and any case where that kill did not land.
;
; Uses the same nsis_tauri_utils plugin + INSTALLMODE define as the template's own
; CheckIfAppIsRunning macro, but without the OK/Cancel prompt: a running sidecar is never
; something the user needs to decide about, it is ours to stop.

!macro _OpenWorkerKillSidecar
  !define /ifndef OW_SIDECAR_EXE "openworker-server.exe"
  ; Kill, then give the kernel a moment to close the handles before any File step runs.
  ; Loop a few times: the kill is async and a busy sidecar (mid tool call) can take a beat.
  ; LogicLib ${Do}/${LoopUntil} on purpose — it mints its own unique labels. A hand-written
  ; label built from ${__LINE__} does NOT work inside a macro (the value is insertion-
  ; dependent, "file.depth.line"), which broke the 1.0.7 Windows build with
  ; `could not resolve label "ow_kill_loop_6559.1.22"`.
  StrCpy $R9 0
  ${Do}
    !if "${INSTALLMODE}" == "currentUser"
      nsis_tauri_utils::FindProcessCurrentUser "${OW_SIDECAR_EXE}"
    !else
      nsis_tauri_utils::FindProcess "${OW_SIDECAR_EXE}"
    !endif
    Pop $R8
    ${If} $R8 <> 0 ; 0 = found; anything else = gone, we're done
      ${ExitDo}
    ${EndIf}
    !if "${INSTALLMODE}" == "currentUser"
      nsis_tauri_utils::KillProcessCurrentUser "${OW_SIDECAR_EXE}"
    !else
      nsis_tauri_utils::KillProcess "${OW_SIDECAR_EXE}"
    !endif
    Pop $R8
    Sleep 500
    IntOp $R9 $R9 + 1
  ${LoopUntil} $R9 >= 6
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro _OpenWorkerKillSidecar
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro _OpenWorkerKillSidecar
!macroend
