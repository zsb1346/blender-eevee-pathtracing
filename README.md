# Blender EEVEE Path Tracing

在 Blender 5.3 EEVEE 中接入 Vulkan 硬件 ray query 的实时路径追踪原型，并使用 NRD 4.17.1 做降噪。

> **状态：研究原型，未达到生产可用。** 2026-11-28 build25（当前补丁）为首交点接入 EEVEE 全材质节点系统后的稳定版本。已修复：视口红弧、间接光近 0 回归、SIGMA 硬阴影、视口 PT 被 `taa_samples` 截断、Debug View 时间累积污染、间接光溢出/青色条纹/点光 firefly/emission 解调、转视角历史被逐帧清空、运动矢量与历史键碰撞（红弧/满地红斑/viewport3 全黄的根因）、动态实例历史键、间接光越弹越亮、MV 屏幕边界历史误用，以及 build24c 切 PATH_TRACING 时 GBuffer 纹理提前 release 导致的崩溃。当前高速移动/旋转视角下 Viewport 3（MV 误差）全程纯黑，累积帧数轨迹与 NRD-Sample 一致。仍需多场景/多 GPU/不同分辨率复验。次级反弹材质、BLAS 索引映射等仍未完成；首交点已接入全材质节点系统（见下）。

这个仓库只包含**源码补丁、文档、测试脚本和测试场景**，不包含完整 Blender 源码或构建产物。完整 Blender 工作区约 16 GB，不适合直接放进 Git 仓库。

## 功能

- Vulkan `VK_KHR_ray_query` 硬件光线追踪路径追踪
- 多 bounce 间接漫反射
- GGX 金属/电介质双 lobe
- 真实阴影 ray
- SIGMA 太阳软阴影
- 世界背景参与间接光
- 面光 BSDF 高光采样
- NRD 4.17.1 REBLUR diffuse + specular 降噪
- 最终 TAA 时间累积（色度加权误差 + 固定最小权重）
- 视口 PT 无限累积采样，不再被 `taa_samples` 截断
- Debug View 单帧直通，绕过 TAA 与 film 两级累积，切回合成时历史干净重启
- 与 EEVEE 运动矢量同源的历史键（`draw::ObjectKey`）：普通物体、CoW、Alt+D 关联复制、集合实例、几何节点动态增删实例均可正确累积
- 运动矢量统一 Y 轴 top-down、DX `[0,1]` 矩阵与 unjittered 投影；屏幕外进入的像素保留真实越界 MV
- 间接光能量守恒：`(1-F_env)` 漫反射补偿 + 高度相关 Smith GGX G2/G1 高光权重
- 性能优化：主相机射线去重、移除冗余 taa_pass、跳过空栅格、TLAS/depsgraph 缓存
- EEVEE Raytracing 面板中的 `Path Tracing` 方法和参数
- 编辑模式自动回退普通 EEVEE，避免崩溃
- NRD `OUT_VALIDATION` 覆盖层（诊断用）
- 材质记录 dump（`pt_materials.json`）

## 当前状态

| 模块 | 状态 |
| --- | --- |
| Vulkan ray query / BLAS / TLAS | 可用；BLAS 按 `const Mesh*` 共享并按 `sync_id_` 回收，TLAS/depsgraph 缓存 |
| 路径追踪 shader | 可用，覆盖基础 diffuse/specular；间接光能量守恒已修 |
| NRD + NRI + TAA | 已接入；红弧、溢出、firefly、历史清空均已修复，build18 稳定 |
| 运动矢量 / 历史键 | 已重构；`draw::ObjectKey` + unjittered DX 矩阵 + 越界 MV，Viewport 3 纯黑 |
| 视口 PT 采样 | 已修复；无限累积，不再被 `taa_samples` 截断，RNG 无 8 帧循环 |
| SIGMA 太阳软阴影 | 已接入；0.5°/10° A/B 可见差异 |
| Raytracing UI | 可用 |
| 编辑模式 | 已修复 |
| 首交点全材质节点系统 | build24/25 已接入：首交点走 EEVEE G-Buffer + 全材质节点求值（Principled/Mix/Diffuse/Glossy/Emission/Glass/Thin Glass/Translucent/SSS/Clearcoat，贴图/UDIM/ColorRamp/Noise/Voronoi/Bump/几何节点属性），省掉主相机 Ray Query；运动矢量优先用原生 `vector_tx`（骨骼/布料动态） |
| 次级反弹材质 | 简化 MaterialRecord（Stage 1 定位，仅首交点接入全节点系统） |
| transmission / emission / volume / hair | 首交点已覆盖 transmission/emission；volume / hair 未完成 |
| DeferredLayer 着色分支 | build24：PT 模式下 prepass_add/material_add 折射并入 opaque_layer_，`DeferredLayer::render` 跑完 GBuffer 写入后提前返回（跳过阴影/SSRT/光照/SSS/Combine）；GBuffer release 推迟到 PT submit 之后 |

已知问题：

- 首交点已接入全材质节点系统，但次级反弹（bounce≥1）仍走简化 MaterialRecord，未读到完整节点树。
- 多材质或存在隐藏面时，BLAS 与 primitive 表的索引映射仍可能不一致。
- 金属 NRD 反射仍偏糊；BLAS 对原地 deform 的更新仍是 stale。
- NRD/NRI/libxess 目前是 Windows 原型集成，尚未做成正式的可选模块。
- Headless still 每次从 sample 0 开始，跨帧 TAA history 不连续；跨帧验证需要 GUI viewport 或多 redraw harness。
- build25 只做了编译与启动验证（切 PATH_TRACING 不再崩溃），首交点贴图/玻璃/清漆的画质与实际帧率仍需多场景复验。

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
docs/FIX_CHECKLIST.md                  # v3 修复清单、验证与回归命令
docs/REFERENCE_NOTES.md                # 参考实现与许可证边界
docs/STATUS.md                         # 当前验证状态和未决问题
tools/pt_test.ps1                      # 构建/批量渲染测试入口
tools/pt_auto_test.py                  # Blender 内测试 case
tools/create_pt_test_scenes.py         # 生成 room/motion/material 测试场景
tools/render_pt_baseline.py            # 渲染确定性 baseline
tools/run_eevee_pt.bat                 # Vulkan 启动脚本
scenes/pt_test_scene.blend             # 最小测试场景
scenes/pt_test_room.blend              # 房间 + 三种材质球
scenes/pt_test_motion.blend            # 10 帧运动/相机测试
scenes/pt_test_material.blend          # 纹理与程序化材质测试
baseline/                              # motion/room/material 基线
```

## 测试

```powershell
.\tools\pt_test.ps1 -Blender "C:\path\to\blender.exe" `
  -Scene ".\scenes\pt_test_room.blend" -Cases normal,no_history,raw,validation,rr
```

查看所有 case：

```powershell
.\tools\pt_test.ps1 -Blender "C:\path\to\blender.exe" -ListCases
```

渲染 baseline：

```powershell
& "C:\path\to\blender.exe" --background --factory-startup --gpu-backend vulkan `
  ".\scenes\pt_test_motion.blend" --python ".\tools\render_pt_baseline.py" -- `
  --out ".\baseline\pt_test_motion" --frames 1-10 --samples 16 --percent 50
```

诊断环境变量：

| 变量 | 作用 |
| --- | --- |
| `EEVEE_PT_NO_TAA=1` | 关闭最终 TAA |
| `EEVEE_PT_NO_NRD=1` | 关闭 NRD |
| `EEVEE_PT_NO_NRD_HISTORY=1` | 禁用 NRD history |
| `EEVEE_PT_DEBUG_VIEW=3` | raw diffuse 视图 |
| `EEVEE_PT_DEBUG_FLAGS=8` | 强制 motion 为零 |
| `EEVEE_PT_USE_RR=1` | 启用 Russian Roulette（A/B） |
| `EEVEE_PT_NRD_VALIDATE=1` | NRD validation 覆盖层（等价于勾选面板 `NRD Validation`）|
| `EEVEE_PT_DEBUG_RESET=1` | 输出 `PTDBG` 视口采样/重置日志，用于验证累积 |
| `EEVEE_PT_DUMP_MATERIALS=1` | 写 `pt_materials.json` |

## 许可证

本项目作为 Blender 的衍生工作，按 GNU GPL v2 或更高版本发布，见 `LICENSE`。NRD、NRI、libxess 等第三方组件遵循各自许可证，不包含在本仓库中。

## 参考

- Blender GPU / EEVEE 源码
- [NVIDIA NRD](https://github.com/NVIDIA-RTX/NRD)
- [NVIDIA NRI](https://github.com/NVIDIA-RTX/NRI)
- NRD-Sample 4.17.1
