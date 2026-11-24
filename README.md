# Blender EEVEE Path Tracing

在 Blender 5.3 EEVEE 中接入 Vulkan 硬件 ray query 的实时路径追踪原型，并使用 NRD 4.17.1 做降噪。

> **状态：研究原型，未达到生产可用。** 当前主要未解决问题是视口 Rendered 模式的红弧/时间累积鬼影。F12 的 debug 3 渲染干净，关闭 TAA 后视口也干净；问题集中在视口 TAA/NRD history 与 motion vector 路径。

这个仓库只包含**源码补丁、文档、测试脚本和测试场景**，不包含完整 Blender 源码或构建产物。完整 Blender 工作区约 16 GB，不适合直接放进 Git 仓库。

## 功能

- Vulkan `VK_KHR_ray_query` 硬件光线追踪路径追踪
- 多 bounce 间接漫反射
- GGX 金属/电介质双 lobe
- 真实阴影 ray
- 世界背景参与间接光
- 面光 BSDF 高光采样
- NRD 4.17.1 REBLUR diffuse + specular 降噪
- 最终 TAA 时间累积
- EEVEE Raytracing 面板中的 `Path Tracing` 方法和参数
- 编辑模式自动回退普通 EEVEE，避免崩溃

## 当前状态

| 模块 | 状态 |
| --- | --- |
| Vulkan ray query / BLAS / TLAS | 可用 |
| 路径追踪 shader | 可用，覆盖基础 diffuse/specular |
| NRD + NRI + TAA | 已接入，仍有视口红弧 |
| Raytracing UI | 可用 |
| 编辑模式 | 已修复 |
| 纹理/节点树材质 | 未完成 |
| transmission / emission / volume / hair | 未完成 |

已知问题：

- 视口静止 Rendered 仍有红弧/鬼影；`EEVEE_PT_NO_TAA=1` 时干净，F12 debug 3 干净。
- `EEVEE_PT_NO_NRD_HISTORY=1` 可消除强红弧，说明 NRD history 是主要放大器之一；但 TAA history 也能在 debug 3 中显现更淡的弧。
- 当前正在排查 viewport motion vector 与 history 重投影；详见 `docs/STATUS.md`。
- 多材质或存在隐藏面时，BLAS 与 primitive 表的索引映射仍可能不一致。
- NRD/NRI/libxess 目前是 Windows 原型集成，尚未做成正式的可选模块。

## 快速开始

完整步骤见 `BUILDING.md`。简要流程：

1. 获取 Blender 5.3 源码并切到基线提交 `7463664d`。
2. 应用补丁：

   ```bash
   git apply --3way patches/0001-eevee-pathtracing.patch
   ```

3. 准备 NRD-Sample 4.17.1，并配置 `NRD_SAMPLE_ROOT`。
4. 使用 Visual Studio 2022 和 Vulkan 后端构建。
5. 把 `NRD.dll`、`NRI.dll`、`libxess.dll` 放到 `blender.exe` 同目录。
6. 用 `--gpu-backend vulkan` 启动，Raytracing 面板选择 `Path Tracing`。

## 仓库结构

```text
patches/0001-eevee-pathtracing.patch   # 应用到 Blender 5.3 的源码补丁
docs/ARCHITECTURE.md                   # EEVEE / NRD 数据流与架构
docs/REFERENCE_NOTES.md                # 参考实现与许可证边界
docs/STATUS.md                         # 当前验证状态和未决问题
tools/pt_test.ps1                      # 构建/批量渲染测试入口
tools/pt_auto_test.py                  # Blender 内测试 case
tools/run_eevee_pt.bat                 # Vulkan 启动脚本
scenes/pt_test_scene.blend             # 最小测试场景
```

## 测试

```powershell
.\tools\pt_test.ps1 -Blender "C:\path\to\blender.exe" `
  -Scene ".\scenes\pt_test_scene.blend" -Cases normal,no_history,raw
```

查看所有 case：

```powershell
.\tools\pt_test.ps1 -Blender "C:\path\to\blender.exe" -ListCases
```

## 许可证

本项目作为 Blender 的衍生工作，按 GNU GPL v2 或更高版本发布，见 `LICENSE`。NRD、NRI、libxess 等第三方组件遵循各自许可证，不包含在本仓库中。

## 参考

- Blender GPU / EEVEE 源码
- [NVIDIA NRD](https://github.com/NVIDIA-RTX/NRD)
- [NVIDIA NRI](https://github.com/NVIDIA-RTX/NRI)
- NRD-Sample 4.17.1
