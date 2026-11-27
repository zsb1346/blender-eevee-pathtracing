@echo off
setlocal EnableExtensions

if not defined BLENDER_EXE (
  if exist "D:\build_windows_x64_vc17_Release\bin\Release\blender.exe" (
    set "BLENDER_EXE=D:\build_windows_x64_vc17_Release\bin\Release\blender.exe"
  ) else (
    set "BLENDER_EXE=blender.exe"
  )
)

if not exist "%BLENDER_EXE%" (
  where "%BLENDER_EXE%" >nul 2>nul
  if errorlevel 1 (
    echo [EEVEE Path Tracing] Blender executable not found: %BLENDER_EXE%
    echo Set BLENDER_EXE to the Blender build that contains the patch.
    pause
    exit /b 1
  )
)

if not defined VK_ICD_FILENAMES (
  for /d %%D in ("C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_*") do (
    if exist "%%~fD\nv-vk64.json" set "VK_ICD_FILENAMES=%%~fD\nv-vk64.json"
  )
)

if not defined VK_ICD_FILENAMES (
  echo [EEVEE Path Tracing] NVIDIA Vulkan ICD manifest was not found.
  echo Set VK_ICD_FILENAMES to your Vulkan ICD manifest, then run this file again.
  pause
  exit /b 1
)

echo [EEVEE Path Tracing] Using Vulkan ICD: %VK_ICD_FILENAMES%
start "" "%BLENDER_EXE%" --gpu-backend vulkan %*
