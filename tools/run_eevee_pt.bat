@echo off
setlocal EnableExtensions

if not defined BLENDER_EXE set "BLENDER_EXE=blender.exe"

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
