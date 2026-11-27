# 参考实现与许可证笔记

本文记录 NRD-Sample、UnityPathTracing 和 Blender 自身 GPU RT 的可借鉴内容与不可复制内容。所有结论需在实现前复核。

## 1. NRD-Sample 4.17.1

路径：`<NRD-Sample-4.17.1>`（本地依赖，不随仓库分发）

状态：

- 已编译。
- 已用 `NRD_MODE=SH` 做冒烟测试。
- 使用 NRI 抽象层，支持 D3D12/Vulkan。
- 使用 inline ray tracing。
- 包含 NRD（REBLUR/RELAX/SIGMA）、SHARC、DLSS-RR、透明玻璃、半分辨率/概率追踪等。

可借鉴：

- 路径追踪与降噪的 pass 拆分。
- NRD 输入/输出资源组织：MV、normal/roughness、viewZ、diffuse/specular radiance、hit distance、confidence。
- 半分辨率/概率追踪与 hit distance reconstruction。
- 直接光/间接光分离、MIS、重要性采样。
- 透明/玻璃的追踪策略。
- 性能档位和调试视图组织。
- SHARC 类缓存的分层思路。

不可直接复制：

- NRD、RTXDI、SHARC 等 NVIDIA RTX SDK 源码。
- NVIDIA 专有 shader 源码。
- 示例中的品牌/资产（除非许可证允许）。

集成建议：

- 优先借鉴算法和资源布局，不复制代码。
- 如果使用 NRD，必须作为可选外部模块，动态加载或独立进程，并遵守 NVIDIA RTX SDK License。
- 默认降噪后端应选择许可证兼容方案；NRD 仅作为可选增强。

## 2. UnityPathTracing

路径：`Kuan-Mi/UnityPathTracing`（仅作架构参考，不随仓库分发）

规模：约 259 MB。

组成：

- `UnityProject`：Unity 工程、场景、资源。
- `RenderingPlugin`：C++ D3D12 渲染插件。
- `Packages/com.kuanmi.path-tracing`：URP 路径追踪包。
- 使用 NRD、DLSS、NIS、RTXMU、RTXCR 等。
- 根目录未发现 LICENSE；包含 NVIDIA 专有 shader 源码。

可借鉴：

- C++ 渲染插件与引擎渲染图的集成方式。
- 路径追踪 pass 拆分：初始采样、着色、时序/空间重采样、次级表面、最终着色。
- 场景数据构建：instance buffer、primitive buffer、材质参数、纹理表。
- NRD 作为独立 denoiser pass 的接入方式。
- 半分辨率/概率追踪、透明/玻璃、毛发/皮肤特殊路径。
- 调试视图和性能开关组织。

不可直接复制：

- NVIDIA 专有 NRD/RTXDI/SHARC shader 源码。
- RTXPT 资产（声明仅限 RTXPT 使用）。
- 缺少明确许可证的代码/资源。
- Unity 专用 C#/HLSL 代码不能直接用于 Blender C++/GPU shader。

## 3. Blender 自身 GPU RT 参考

已确认：

- `source/blender/gpu/GPU_ray_tracing.hh`：TLAS/BLAS/ray query API。
- `source/blender/gpu/vulkan/vk_ray_tracing.cc`：Vulkan 实现。
- `source/blender/gpu/tests/ray_tracing_test.cc`：TLAS/BLAS/ray query 测试。
- `source/blender/gpu/tests/shaders/gpu_ray_query_test.glsl`：compute shader ray query 示例。
- `source/blender/draw/engines/workbench/workbench_shadow_raytrace.bsl.hh`：Workbench 硬件 RT 阴影。
- `source/blender/draw/intern/draw_cache_impl_mesh.cc`：mesh BLAS 构建。

用途：

- 作为 API 用法和 shader 语法基准。
- 作为 Vulkan/Metal 能力检测参考。
- 作为 BLAS/TLAS 扩展的起点。

限制：

- 现有 API 主要服务阴影/简单查询，不是完整路径追踪。
- BLAS 缺少 per-triangle material ID。
- TLAS 缺少完整 per-instance metadata。
- 需要扩展 GPU 模块，而不是在 EEVEE 内绕开。

## 4. 许可证矩阵

| 组件 | 许可证/状态 | 能否直接进入 Blender GPL 代码 |
|---|---|---|
| Blender | GPL-2.0-or-later | 是（自身） |
| NRD | NVIDIA RTX SDK License | 否，需可选外部模块/独立进程/法律审查 |
| RTXDI | NVIDIA RTX SDK License | 否 |
| SHARC | NVIDIA RTX SDK License | 否 |
| DLSS | NVIDIA RTX SDK License | 否，需可选外部模块 |
| RTXMU | MIT | 可参考/可用，但需确认整体依赖 |
| RTXCR | MIT | 可参考/可用，但需确认整体依赖 |
| UnityPathTracing 根目录 | 未发现 LICENSE | 不能直接复制 |
| RTXPT 资产 | 仅限 RTXPT 使用 | 不能搬入 |
| Blender GPU RT API | GPL-2.0-or-later | 是 |

## 5. 借鉴边界

可以借鉴：

- 架构、pass 顺序、资源布局、采样策略、降噪输入输出、性能优化思路。
- 公开论文/文档中的算法。
- MIT 许可代码（保留版权/许可声明）。

不可以：

- 复制 NVIDIA 专有源码到 GPL 文件。
- 把 NRD/RTXDI/SHARC 静态链接进 Blender 发布版。
- 复制缺少许可证的 UnityPathTracing 代码/资产。
- 把 RTXPT 资产用于其他项目。

## 6. 对任务卡的影响

- TC-003 需要自建 BLAS/TLAS 元数据扩展，不能依赖 UnityPathTracing 的 Unity API。
- TC-004 可以借鉴 NRD-Sample 的 pass 拆分和采样策略，但用 Blender GPU API 重写。
- TC-006 必须先做降噪后端抽象；NRD 只能是可选后端。
- TC-009 必须记录外部依赖和许可证。

## 7. NRD 4.17.1 实际集成接口（原型，2026-11-17；2026-11-27 适用说明）

> 版本说明：本文与 README 以 NRD 4.17.1 为参考基准；当前构建实际使用 NRD 4.18（`D:/下载/nrd418/root`）+ NRI，两者 API 兼容。对照逐帧 dispatch 优先看 `NRD-Sample-main`（面向 4.18），`NRD-Sample-4.17.1` 为旧固定版。许可证边界（NRD/NRI 不可进 GPL 源码树、须可选外部模块 + 动态库分发 + 许可证审查）不随版本变化。

已实际链接并运行的组合：

- NRD 4.17.1（RELAX_DIFFUSE）+ NRI 178 + `libxess.dll`。
- `NRD.lib` 是核心 API 导入库；`nrd::Integration` 为 header-only，使用 `NRDIntegration.hpp`。
- `NRI.dll` 静态依赖 `libxess.dll`；三者必须与 `blender.exe` 同目录。
- 使用已有 VkDevice/VkInstance 通过 `RecreateVK` 包装，NRD 自己管理 command buffer/fence；原型每帧等待完成后再 copy。
- 资源 usage 需要 `SAMPLED|STORAGE`；PT 纹理必须带 storage usage。
- 颜色可读 `NRD` 官方 sample 的 `NRDSample.cpp`、`Shaders/Include/Shared.hlsli`、`External/NRD/Shaders/Composition.cs.hlsl`、`External/NRD/Shaders/NRD.hlsli`，用于核对 motion、sky viewZ、normal/roughness pack。

不可直接复制：

- NRD/NRI 源码和 shader 不能进入 GPL 源码树；当前只是本机原型。
- 最终分发必须 object-code 动态库、可选 `WITH_NRD`、同目录 DLL，并完成 NVIDIA RTX SDK License 审查。
- 默认构建不能依赖 NRD 存在；缺失时应安全回退普通 PT 或 EEVEE 降噪方案。
