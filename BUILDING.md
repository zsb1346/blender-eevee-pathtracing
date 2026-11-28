# Building

> 当前状态（2026-11-28）：本文构建步骤有效，当前补丁与 exe 为 build28（首交点全材质节点 + 玻璃阴影穿透/单光源抽样/次级折射 + HDRI 世界环境间接光 + `NRD` 色彩 View；`D:\build_windows_x64_vc17_Release\bin\Release\blender.exe`，MTIME `11:11:45`，SIZE 124924416，EXITCODE=0 / 0 errors / 0 warnings）。增量构建前须确认无 Blender 进程占用 exe，并注意 Agent shell 中大小写重复环境变量（`PATH`/`Path` 等）会导致 MSBuild `MSB6001`——`$env:Path` 的 `Select-Object -Unique` 因大小写不敏感无效，须用 `[Environment]::GetEnvironmentVariables()` 按 lowercase 分组、对重复组 `SetEnvironmentVariable(name,$null,'Process')` 删除多余键后再 build。

## 1. 获取 Blender 源码

补丁基于 Blender 5.3 release 基线提交 `7463664d`。

```bash
git clone https://projects.blender.org/blender/blender.git
cd blender
git checkout 7463664d
```

如果网络无法访问 projects.blender.org，也可以使用 GitHub 上的 Blender 镜像，但必须确保检出的是同一基线提交。

## 2. 应用补丁

```bash
git apply --3way /path/to/blender-eevee-pathtracing/patches/0001-eevee-pathtracing.patch
```

补丁包含新增的 EEVEE 路径追踪模块、shader、Vulkan/NRD 集成、DNA/RNA 和 UI 修改。

## 3. 准备 NRD / NRI

需要 NRD-Sample 4.17.1：

- `External/NRD/Include`
- `External/NRD/Integration`
- `External/NRIFramework/External/NRI/Include`
- `_Bin/Release/NRD.lib`
- `_Bin/Release/NRI.lib`

将 NRD-Sample 根目录传给 CMake：

```powershell
cmake -S . -B ..\build_windows_x64_vc17_Release `
  -G "Visual Studio 17 2022" -A x64 `
  -DWITH_VULKAN_BACKEND=ON `
  -DNRD_SAMPLE_ROOT="D:/path/to/NRD-Sample-4.17.1"
```

如果 CMake 报 `NRD_SAMPLE_ROOT is not set`，说明路径没有传进去。

> 版本兼容：文档与 README 以 4.17.1 为准；当前实际构建用的是 `D:/下载/nrd418/root`（NRD 4.18）+ NRI，4.17.1 与 4.18 的 API 互相兼容。NRD-Sample 4.17.1（旧固定版）与 `NRD-Sample-main`（面向 4.18 API）都在本地，后者更适合逐帧 dispatch 对照。

## 4. 构建

```powershell
cmake --build ..\build_windows_x64_vc17_Release `
  --target blender --config Release --parallel 1
```

Windows 上建议先用 `--parallel 1`。并行编译在内存较小的机器上容易 OOM。

## 5. 运行依赖

把以下 DLL 放到 `blender.exe` 同目录：

- `NRD.dll`
- `NRI.dll`
- `libxess.dll`（NRI 的运行时依赖）

如果系统找不到 Vulkan ICD，可显式指定 NVIDIA 的 ICD：

```powershell
$env:VK_ICD_FILENAMES = "C:\Windows\System32\DriverStore\FileRepository\<nvidia-icd>\nv-vk64.json"
```

## 6. 启动

```powershell
.\blender.exe --gpu-backend vulkan
```

启动后：

1. Render Properties 中选择 `EEVEE`（内部 ID 为 `BLENDER_EEVEE`）。
2. 打开 Raytracing。
3. 在 Raytracing 面板选择 `Path Tracing`。
4. 视口切到 Rendered，或按 F12。

## 7. 调试环境变量

| 变量 | 作用 |
| --- | --- |
| `EEVEE_PT_NO_TAA=1` | 关闭最终 TAA history |
| `EEVEE_PT_NO_NRD=1` | 跳过 NRD 降噪 |
| `EEVEE_PT_NO_NRD_HISTORY=1` | 每帧重置 NRD history |
| `EEVEE_PT_DEBUG_RESET=1` | 打印采样/history 重置日志 |
| `EEVEE_PT_DEBUG_VIEW=<n>` | 输出 debug 通道 |
| `EEVEE_PT_DEBUG_MOTION=1` | 在 TAA 阶段输出 motion 可视化 |
| `EEVEE_PT_DEBUG_FLAGS=8` | 把 motion 强制清零，用于隔离重投影问题 |
| `EEVEE_PT_NRD_VALIDATE=1` | NRD validation 覆盖层（等价勾选面板里的 `NRD Validation`） |

NRD validation 覆盖层的开关在 Raytracing 面板的 `Channels → NRD Validation`（场景属性 `pathtracing_use_validation`），默认关闭；上面的环境变量是给自动化测试用的 override，两者任一为真即开启。它显示的是 NRD 的**历史健康度染色**（见 NRD `OUT_VALIDATION`），不是图像内容通道，可叠加在任意 Debug View 之上。

Debug View（`pathtracing_debug_view` / `EEVEE_PT_DEBUG_VIEW`）现在是**单帧直通**的：TAA 阶段不再对 debug 通道做时间累积，Raw / Hit Distance 等视图显示的就是当帧原始信号；切回 `Composite` 时 TAA 历史会干净重启。

`EEVEE_PT_DEBUG_VIEW` 主要取值：

- `1`：NRD denoised diffuse
- `2`：NRD denoised specular
- `3`：raw diffuse
- `4`：raw specular
- `5`：diffuse hit distance
- `6`：specular hit distance
- `7`：denoised diffuse + specular
- `8`：direct only
- `0`：正常合成

## 8. 测试场景

`scenes/pt_test_scene.blend` 是一个最小场景，包含一个平面、一个红色球体、一个太阳光和一个相机。测试脚本默认使用该场景。
