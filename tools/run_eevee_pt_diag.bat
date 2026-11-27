@echo off
setlocal EnableExtensions

if not defined BLENDER_EXE (
  set "BLENDER_EXE=D:\build_windows_x64_vc17_Release\bin\Release\blender.exe"
)

if not defined VK_ICD_FILENAMES (
  for /d %%D in ("C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_*") do (
    if exist "%%~fD\nv-vk64.json" set "VK_ICD_FILENAMES=%%~fD\nv-vk64.json"
  )
)

set "EEVEE_PT_DEBUG_RESET=1"
set "LOG=D:\下载\_reset_diag.log"
if exist "%LOG%" del "%LOG%"

echo [DIAG] Logging to %LOG%
echo [DIAG] Launching Blender. Rotate the view once, then leave it static for ~10 seconds, then close Blender.
echo [DIAG] Fields: sample / pending / sampling_reset / new_session / res_changed / frame_jump
"%BLENDER_EXE%" --gpu-backend vulkan %* > "%LOG%" 2>&1

echo [DIAG] Blender exited. Log saved to %LOG%
pause
