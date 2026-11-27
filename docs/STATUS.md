# 当前状态与未决问题

更新时间：2026-11-27（build18 后，当前 exe 稳定健康）

## 已完成

- Vulkan 硬件 ray query 路径追踪主链路可运行。
- NRD 4.17.1 + NRI + REBLUR diffuse/specular + 最终 TAA 已接入。
- Raytracing 面板新增 `Path Tracing` 方法、Max Bounces、Clamp、通道开关和 Debug View。
- 视口进入 Edit Mode 时自动禁用 PT 并回退普通 EEVEE，不再崩溃。
- 背景/材质基础路径可用；当前仍主要读取 Principled 常量。
- 新增 NRD `OUT_VALIDATION` 覆盖层、材质 dump、测试场景与 baseline。
- 修复 NRD 概率契约、luminance-preserving clamp、TAA 色度误差与动态历史权重。
- 视口 Path Tracing 不再被 `taa_samples`（默认 16）截断，改为无限累积采样。
- Debug View 改为单帧直通：TAA 阶段和 film 层第二级累积均对 debug 通道 bypass；切回 Composite 时历史干净重启。
- 修复间接光溢出、青色条纹、点光 firefly、emission 解调位置、转视角历史被逐帧清空等一批 NRD/物理正确性问题（详见 `docs/FIX_CHECKLIST.md`）。
- 运动矢量（IN_MV）与历史键重构：统一 Y 轴、矩阵改 DX `[0,1]` 且用 unjittered，history key 用 Blender 原生 `draw::ObjectKey`（对齐 EEVEE VelocityModule），屏幕外像素用 unbounded 投影保留真实越界 MV；高速移动/转视角下 Viewport 3（MV 误差）全程纯黑，Viewport 8/11 累积帧数呈正确渐进轨迹。
- 间接光能量守恒：补 `(1-F_env)` 漫反射能量补偿、高光 G1→高度相关 Smith G2/G1，消除反弹次数越多越亮。
- 性能优化：移除冗余 taa_pass、主相机射线去重、跳过空栅格、TLAS/depsgraph 缓存。当前 exe 为 build18（`15:53:18`）。

## 视口红弧 / 时间累积鬼影

### 修复前记录

| 测试 | 结果 |
| --- | --- |
| 视口正常渲染，静止相机，80 redraws | 平台前缘出现红弧，边缘有红色亮线 |
| 视口 `DEBUG_VIEW=3`（raw diffuse） | 4/8/16/80 redraws 逐渐出现淡红弧 |
| 视口 `DEBUG_VIEW=3; NO_TAA=1` | 干净 |
| 视口 `DEBUG_VIEW=3; NO_NRD=1` | 仍有淡红弧 |
| 视口 `NO_NRD_HISTORY=1` | 强红弧消失 |
| 视口 `NO_TAA=1` + NRD | 仍有强红环 |
| F12 64 samples `DEBUG_VIEW=3` | 干净 |
| 视口 motion debug（4/80 redraws） | 天空为零；平台/球体出现非零、随屏幕位置变化的 motion |

### 2026-11-25 修复与验证

- TAA 误差保持色度加权，避免红色间接光在 history 中被过度累积。
- `min_weight` 固定为 `0.0606f`；删除 motion/variance 动态 distrust（会放大闪烁），`sigma` 仅用于 `ClampAabb`。
- 相机/场景变化时显式重置 NRD/TAA history，避免旧 motion vector 重投影。
- NRD 概率、Bayer dither、AREA_3X3、anti-firefly、prepass 半径已对齐 NRD-Sample。
- 所有 radiance clamp 改为亮度保持缩放，避免高亮红色被压成白色。
- GUI 验证：静止相机 80 redraws、移动相机后 80 redraws，均未复现红弧。
  - 截图：`C:\Users\q1553\AppData\Local\Temp\opencode\pt_gui\after_80_static.png`、`after_80_moved.png`。
- 批量 case：`normal/no_history/raw` 在 room 场景 64 spp 下无异常，`red%` 约 0.058%，与场景中的红球一致。
- `validation` case 正常输出 4x4 NRD validation 覆盖层。
- `rr` case 与 normal 有可测差异（mean 0.003），确认 `EEVEE_PT_USE_RR` 生效。

结论：红弧在本次 GUI 测试中未复现，初步认为已修复；仍需多场景/多 GPU/不同分辨率复验。

## 间接光近 0 回归（2026-11-26 已修复）

- 现象：修复过程中间版本出现间接光照几乎消失，画面接近 direct-only。
- 根因：`PathTracingModule::aux_buf_` 在 `end_sync()` 中用 `inst_.render_buffers.extent_get()` 决定大小，但该阶段 extent 仍为 0，`std::max<size_t>(1, 0)` 只分配 1 个元素。路径追踪 shader 中除像素 0 外所有 `diff_factor`/`spec_factor` 写入越界被丢弃，composite 读到的 factor 接近全 0。
- 修复：把 `aux_buf_.resize(...)` 移到 `render()` 中 `const int2 extent = inst_.render_buffers.extent_get();` 之后；`data_buf_.resolution` 使用同一 extent。修复后无需额外 barrier，path pass 结尾的 `GPU_finish()` 已保证 composite 读取可见性。
- 验证：
  - 临时 debug view 9/10（raw diffuse/specular，不乘 factor）均值 186.577/192.694；view 11/12（factor）均值 0.088/0.083，且只有左下 2x2 像素有非零 factor，证实 SSBO 只有 1 元素。
  - 修复后 `normal` mean 190.076、间接光视图 173.947、factor 视图 171.198；金属球反射与间接光恢复。
  - GUI 80 redraws 截图 `C:\Users\q1553\AppData\Local\Temp\opencode\pt_gui\after_80_fixed.png`，中心 869x646 区域 RGB mean 190.708/181.203/179.908，无红弧，间接光与噪点收敛正常。
  - Headless 32 spp 仍噪是每帧 `sample_index==0` 重置 NRD/TAA history 所致，不作为验收依据。

## SIGMA 太阳软阴影（2026-11-26 已修复）

- 现象：SIGMA 输出已接入，但太阳阴影始终是硬边，0.5° 与 10° 太阳角几乎无差异。
- 根因：主路径直接光循环对主命中点的太阳也执行硬阴影 visibility ray，被遮挡的像素在写入 direct 前就被 `continue` 丢弃；composite 中 `sun_fraction=0`，SIGMA 的 `shadow` 没有可调制的太阳份额。
- 修复：仅对局部光源和 `bounce > 0` 的间接太阳做 visibility ray；主命中点太阳直接光保持 unshadowed，由 composite `direct.rgb * mix(1, SIGMA_shadow, sun_fraction)` 统一调制。
- 验证：`pt_test_scene.blend` 派生 0.5°/10° 两个太阳角、暗世界场景；修复后 10° 阴影边缘明显比 0.5° 更软更大。`sharp_dark_final` vs `soft_dark_final` normal 图差异 mean 0.161/0.145/0.145、rms 1.872/2.137/2.137、最大通道差 83。
- `raw` case 因 composite 将 `shadow` 置 1，两角度图像相同是预期行为，SIGMA 验收统一使用 `normal`。
- 临时 debug view 13/14（`nrd_shadow_output_tx`、`sun_fraction`）已删除，最终 clean build 通过。

## 视口 PT 采样上限（2026-11-26 已修复）

- 现象：视口 Path Tracing 在约 16 个 sample 后停止收敛，画面长期保留明显噪声；用户容易误以为是 `run_eevee_pt.bat` 启动方式有问题。
- 根因：`Sampling::init` 对视口统一使用 `scene->eevee.taa_samples`（默认 16），`finished_viewport()` 达到该值即停止请求新 sample；PT 的 NRD/TAA 时间累积因此只有约 16 帧可用。`run_eevee_pt.bat` 仅负责设置 Vulkan ICD 和启动参数，不是噪声根因。
- 修复：`eevee_sampling.cc` 在“视口 + GPU 支持 ray query + 开启 SSR + 方法为 Path Tracing”时改用 `infinite_sample_count_`；普通 EEVEE 视口仍按 `taa_samples` 停止。`Sampling::init` 早于 `path_tracing.begin_sync()`，因此直接用场景标志判断，并加 `GPU_ray_query_support()` 防止不支持 ray query 时回退普通 EEVEE 却无限累积。
- 验证：GUI 80 redraws，`EEVEE_PT_DEBUG_RESET=1` 日志显示 sample 连续到 81（`scene.eevee.taa_samples=64`），`sampling_reset=0`、`new_session=0`，没有在 64 或 16 处停止。另以 `taa_samples=16`、30 redraws 复验当前二进制，sample 到 31，无 reset；截图 `C:\Users\q1553\AppData\Local\Temp\opencode\pt_gui\verify_sample_gt_16.png`，31 spp 画面已明显收敛且无红弧。
- 补充观察：8 spp 隔离测试中 `nrd_only` 与 `raw` 仍有明显噪声，`diffuse_nrd_only` 比 `diffuse_raw` 更平滑，说明 NRD 空间降噪在工作；低 spp 下剩余噪声主要来自间接光时间累积不足，继续累积即可收敛，不应通过提高 sample 数掩盖。

## 2026-11-27 build11–build18：运动矢量/历史键重构、性能优化与能量守恒（当前稳定状态）

本节记录 11-27 下午从 build11 到 build18 的一整轮修复。用户逐项给出方案、逐字落地，每个 build 均 `EXITCODE=0`/0 errors。最终 build18 经 GUI 验证「很稳定很健康」。

### build11：history key 与 MV 正确性

- **根因**：`ob->index` 是 Pass Index（默认 0，旁证 `primitive.object_id = ob->index + 1`），全场景物体 history key 碰撞 → `prev_object_to_world_` 全拿同一物体矩阵 → 静止时 IN_MV 狂乱 → 红弧、1px 红边、满地红斑、Viewport 3 全黄、NRD 历史每帧重置。
- 修复：`eevee_pathtracing.cc` 的历史键从 `ob->index` 改为 `ob->id.session_uid`（DNA_ID.h，会话唯一稳定）。
- **Y 轴 top-down 统一**：6 张 NRD 纹理（normal/viewz/diff/spec/motion/shadow）写入用 `nrd_texel=(frag.x, H-1-frag.y)`，direct+aux 保持 raster；composite 读这 6 张、validation 读 validation、taa 读 motion/viewz 均用翻转 texel，taa 的 `motion.y` 取反。
- **矩阵 DX `[0,1]` + unjittered**：`nrd_view_to_clip` 从 winmat 转 DX（只改 Z 行，`col-major [col][2]=0.5*z+0.5*w`，clip.xy/w UV 不受影响）；`PathTracingData` 加 `curr_world_to_view`/`curr_view_to_clip`；prev/curr 矩阵全存 main_view 的 unjittered 矩阵；debug shader 用两帧 unjittered 矩阵投影 hit 算 MV，去掉手动 jitter delta，`camera_jitter.y` 取反。
- **sample_index 去 8 帧循环**：`data_buf_.sample_index` 改用模块自增 `frame_counter_`，EEVEE 自己的 sample_index 存局部变量供 reset/frame_jump 判断，RNG 不再每 8 帧重复。
- `sun_penumbra` 去掉多余的 `*0.5f`。

### build12 / build13：底层诊断与射线去重

- build12（诊断实验）：`vk_nrd.cc` 临时把 `motionVectorScale[0/1/2]` 全设 0、`isMotionVectorInWorldSpace=true`（NRD 官方初始集成步骤）。结果 viewport3 几何区 100% 纯黑、橙棋盘消失、红球底座大红弧消失——**证明 build11 的底层修复已全部正确**。该实验的 4 行已在 build14 回退。
- build13：修复通道口放射状扇形噪点 + 地板右下 1px 红线。根因是 lobe 循环外初始化 `ray_origin/direction`，lobe==1 继承了 diffuse lobe 弹射后的 ray 并从随机点起跳、在 bounce==0 覆写主交点 G-Buffer。修复：保存 `primary_ray_origin/direction` 常量并在 lobe 循环内每轮重置；两处 `if (bounce==0u)` 改为 `if (lobe==0u && bounce==0u)`。

### build14 / build15：性能优化与 TLAS 缓存

- **移除 taa_pass**：composite shader 加 `CompositeFragOut` 直出 `frag_color(0)`（alpha=0 不透射）；cc 的 `render()` 删 taa ping-pong 提交、validation base 改 `taa_composed_tx_`、删 `taa_history_a/b` 的 ensure_2d。消除 1px 红边、省 1 个 pass + 2 张 RGBA16F。
- **主射线去重**：debug shader 的 `frag()` 主体整段重写——主相机 ray 只 trace 1 次（`primary_query`），主交点/direct light 只算 1 次，`direct_samples` 4→1、`bsdf_samples` 4→1，indirect lobe 从 `bounce=1` 起。保留 emission proxy / NRD YCoCg / viewZ Y 翻转 / motion / 8 通道 debug / sun penumbra。
- **跳过空栅格**：`eevee_instance.cc` 用 `!path_tracing.enabled()` 包住 `capture_view.render_world/rotate_world/render_probes` + `lookdev_view.render`；`eevee_view.cc` 用 `pt_enabled` 包住 background/volume/AO/forward/debug draw，**保留 `deferred.render` 写深度**（网格/选中框遮挡）。
- **TLAS 缓存**：hh 加 `last_depsgraph_update_`/`skip_sync_`/`has_moving_instance_`；`begin_sync()` 用 depsgraph update count + `has_moving_instance_` 判 skip；`end_sync()` 的 `tlas_->build` + buffer 上传包在 `if(!skip_sync_)` 内；`render()` 末尾 `prev_object_to_world_ = current_object_to_world_` 也包在 `if(!skip_sync_)` 内。
- **回退 build12 诊断**：`motionVectorScale` 恢复 `(1/w, 1/h, 1)`、`isMotionVectorInWorldSpace` 恢复 `false`，重新启用已修好的应用 MV。

### build16 / build17：动态实例历史键（Alt+D / 集合实例 / 几何节点）

- build16 修两个坑：①评估态 CoW 对象 `session_uid==0` 导致 history key 碰撞 → 用 `DEG_get_original(ob)` 解析 uid 并加 occurrence 计数；②BLAS 用 `const Object*` 做 key 导致关联复制重复建/每帧重建 → 改 `const Mesh*` 共享 BLAS + `last_used_sync` 按 `sync_id_` 自动回收。自写 `HistoryKey{object_uid, occurrence, instance_index}`。
- build17 用 Blender 原生 **`draw::ObjectKey(ob_ref, i)`**（`draw/intern/draw_handle.hh`，EEVEE VelocityModule 同款，内部 `DEG_get_original` + `DupliObject::persistent_id` + `sub_key_`，自带 `hash()`/`==`）替换自写 HistoryKey，与 EEVEE 原生运动矢量 100% 同一套标准。普通物体、CoW、Alt+D 关联复制、集合实例化、几何节点动态增删实例全部对齐。`sync_id_`（BLAS 回收）和 `Map<const Mesh*, ObjectGeometry>`（共享 BLAS）保留。

### build18：能量守恒与 MV 边界（当前 exe，`15:53:18`）

- **能量守恒**：间接漫反射漏乘 `(1-F)` 是「反弹次数越多越亮 / 隧道阴影比 Cycles 亮」的根因（非金属掠射角 F 达 0.3–0.9，镜面 lobe 反射 F 后漫反射 lobe 又按 100% 反射，总反照率 >1）。修复：加 `smith_lambda`/`smith_g2_over_g1`（高度相关 Smith GGX G2/G1），主交点与次级反弹的 specular lobe 权重用 G2/G1、diffuse lobe 乘 `(1-f_env)`。**直接光 geometry 项仍用 `smith_g1`，按方案不动**（:716/:831/:1111）。`nrd_material_factors` 的 diff/spec factor 是解调因子，与采样权重用途不同，未改。
- **MV 边界**：`project_screen_uv` 的 `[0,1]` 截断会让屏幕外进入的新像素 prev_uv 越界时返回 false、`nrd_motion` 被留成 (0,0)、NRD 误用边缘旧历史。新增 `project_screen_uv_unbounded`（只检查 `clip.w>1e-6`），nrd_motion 的 prev/curr 都改调它，越界像素带真实 MV（如 -25px），由 NRD 自行判定丢弃历史。原 `project_screen_uv`/`previous_screen_uv` 保留。
- 验证：高速前后移动/旋转视角下 Viewport 3（MV 误差）全程 100% 纯黑；Viewport 8/11（Diff/Spec 累积帧数）呈现与 NRD-Sample 一致的 深蓝(0)→紫→青→绿→黄 渐进轨迹。

### 待做（用户尚未给具体方案，未擅自改动）

- `eevee_pipeline.cc` 跳过 DeferredLayer 着色（只留 depth prepass）：用户多次提到可加以提升帧率，但未提供具体改法。当前 `deferred.render()` 的着色阶段仍在跑，按「别自己猜」原则未动。

## 其他未完成

- 材质节点树/纹理尚未接入，M4 仍为调研阶段。
- 多材质、隐藏面场景的 BLAS/primitive 索引映射需要修复。
- 金属 NRD 反射仍偏糊。
- BLAS 对原地 deform 的更新仍是 stale。
- 性能尚未达到实时目标。
- NRD/NRI/libxess 仍是 Windows 原型集成，需要整理为可选的 `WITH_NRD` 模块并做许可证审查。
- 玻璃球仍因 transmission 未实现而发白。
- 材质 dump 每次 `end_sync` 都会重写文件，后续可加限流。

## 相关文档

- `docs/FIX_CHECKLIST.md`：本次 v3 修复的逐项清单与回归命令。
- `docs/ARCHITECTURE.md`：EEVEE / NRD 数据流与架构。
- `docs/REFERENCE_NOTES.md`：参考实现与许可证边界。
