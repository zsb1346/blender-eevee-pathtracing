# EEVEE PT 修复清单（v3）

更新时间：2026-11-27（build18，当前 exe 稳定健康）

范围：NRD 契约、路径追踪物理正确性、TAA 时间累积、诊断工具与测试场景。阶段 4/5（材质 Atlas、程序化 Bake）不在本次范围。

> 进度说明：阶段 0/1/2/3/3.5/3.6/3.7 与 0b/0c 的修复均已编译进当前 exe（build18，`15:53:18`）并经 GUI 验证；下文早期条目标题中的「等待编译验证 / buildN 待验证」是当时的记录，不代表当前状态。build11–build18 的新增修复见阶段 0d。

## 阶段 0b：调试通道 UI 与语义修正（2026-11-27）

- [x] NRD validation 接入 UI 主控
  - `DNA_scene_types.h`：新增 `PATHTRACING_EEVEE_CHANNEL_VALIDATION = (1 << 4)`；默认 15 不含该位，老文件 versioning 到 15 天然关闭，无需改 `versioning_503.cc`。
  - `rna_scene.cc`：新增 `pathtracing_use_validation` 布尔属性，绑定到该位。
  - `properties_render.py`：Raytracing 面板 Channels 组加 `NRD Validation` 勾选。
  - `eevee_pathtracing.cc`：`validation_enabled = UI 位 || EEVEE_PT_NRD_VALIDATE`（后者保留为测试 override）。
  - `vk_nrd.cc`：删除 `g_nrd.validation_enabled` 与环境变量读取，`enableValidation` 仅由 `input.validation != nullptr` 决定（EEVEE 侧为唯一真源）。
  - 语义澄清：`OUT_VALIDATION` 是 NRD 历史健康度 overlay（violet zone），不是图像内容通道，与 `pathtracing_debug_view` 的 9 个通道正交，可叠加。
- [x] Debug View 绕过 TAA 时间累积
  - `eevee_pathtracing_taa.bsl.hh`：新增 `bypass_taa` push constant；为真时把 composed 像素直接写入 `out_history_img` 和 `frag_color`，不做重投影/邻域钳制/历史混合。
  - `eevee_pathtracing.cc`：按 `debug_view > 0.5` push `bypass_taa`；新增 `debug_view_` / `debug_view_was_active_` 成员，debug 期间及退出首帧令 `taa_history_valid_ = false`，避免 debug 帧污染正常累积。
  - 效果：Raw / Hit Distance / Denoised 等视图显示单帧原始信号；切回 Composite 时 TAA 历史干净重启。
  - 验证待办：重新编译后 GUI 检查 `DEBUG_VIEW=1..8` 无拖影，切回 0 累积正常；勾选/取消 NRD Validation 覆盖层生效。

## 阶段 0c：三项视觉 bug 修复（2026-11-27，已编译验证）

- [x] Debug View 绕过 film 层第二级时间累积
  - 根因：PT 内部 TAA 已 bypass，但 `Film::accumulate()` 还有一层 YCoCg reprojection 累积。Raw Diffuse 因此持续收敛；hit-distance 等非颜色量被当颜色重投影，相机移动时出条纹。
  - `eevee_film.hh`：`accumulate(..., bool bypass = false)`。
  - `eevee_film.cc`：`bypass` 时设 `display_only_ = true`，submit 后立即还原；不 swap combined/weight，不改 `use_history`，历史缓冲保持干净。
  - `eevee_pathtracing.hh`：新增 `debug_view_active()`。
  - `eevee_view.cc`：`ShadingView::render()` 把 `debug_view_active()` 传给 film accumulate。
  - 视口路径有效（`FILM_FRAG` shader 支持 `display_only` push constant，与 `Film::render()` 既有用法一致）。
  - 已知限制：F12 / compute 路径的 `accumulate_comp` 不读 `display_only`；Debug View 主要按视口工具使用，F12 下 debug 通道仍会走 film 累积。
  - **build5 后 GUI 回归发现 bug（2026-11-27 10:56）**：切 debug 通道画面没反应，只有 Composite 变。根因：`display_only=true` 时 shader 读 `film.in_combined_tx`（= `combined_tx_.current()`，TAA 历史缓冲），而不是当前帧 `combined_final_tx_`。所以 bypass 一直在显示旧历史帧，切通道自然无变化。
  - 修复：`FilmDisplay` 新增 `display_current` push constant；`eevee_film.bsl.hh:1351` 的 `display_id==-1` 分支按它选择读 `film.combined_tx`（当前帧，`combined_final_tx_` 绑定）还是 `in_combined_tx`（历史）。C++ 侧 `Film` 加 `display_current_`，`sync()` push 绑定，`accumulate()` bypass 时置 true/结束置 false，`display()` 置 false（保持"重复显示历史帧"语义）。build6 EXITCODE=0，GUI 确认通道切换已恢复。
- [x] **红光溢出 / 青色条纹（2026-11-27，build7 待验证）**
  - 现象：Denoised Diffuse / Indirect 通道地面大片红斑 + 青色横条纹；Raw Diffuse/Raw Specular 干净（NRD 输入本身正常）。红色立方体被后方灯光照亮，经间接路径 bounce 到地面。
  - 用户对照：`clamp_indirect` 从 10→1→0.25 红斑只减轻不消失 → 排除纯参数问题。
  - 根因：clamp 施加在 **demodulation 之前**。喂给 NRD 的信号是 `diff_radiance / diff_factor`，`diff_factor` 下限 0.02 → 最多放大 50x。clamp 到 0.25 除以 0.02 后仍达 12.5，NRD 看到 inflated firefly，REBLUR spatial filter 把它 smear 成红斑，YCoCg 色度在边界振铃成青/红条纹。
  - 修复（build7）：`eevee_pathtracing_debug.bsl.hh` 在 imageStore 之前对 demodulated 信号**再 clamp 一次**到 `clamp_indirect`（<=0 时用 1000 兜底），让 UI 的 clamp 值精确对应 NRD 实际看到的亮度上限。
  - 排除项（未改）：YCoCg 编解码系数与 NRD 一致；nrd_material_factors 与官方 NRD_MaterialFactors 一致（都 0.02/0.1 min scale）；点光距离下限已生效；`minMaterialForSpecular` 我们是 0.0 而 NRD-Sample 是 1.0（material ID 分类阈值，非 firefly 主因，暂不动）。
  - **单位核对（2026-11-27，确认无 bug）**：曾怀疑 `light->energy`（BKE_light_power = radiant flux W）换算漏了 `1/area`。完整推导后确认正确：官方 `area.size = la->area_size·scale/2`（半边长），`shape_radiance_get` 的 `area = size.x·size.y·4` = 全边长²；radiance = `energy/(area·π)`， irradiance = radiance × 立体角(`area·cos_light/d²`) = `energy·cos_light/(π·d²)`，与 shader 733 行一致（area 抵消）。点光：强度 `energy/(4π)` / d² = `energy/(4π·d²)`，与 751 行一致。**单位换算无 bug**，不要改。
  - build7 GUI：红斑从离散鲜红点阵变为均匀淡雾，青条纹消失，但合成视图地面仍有粉红雾 → 用户判定仍不可用。
  - **build8（待验证）**：用户对照实验证明 clamp 降到 2 红斑明显减少，而 build7 的 NRD 输入 clamp 用的是 UI 值 10，量级过高。改 `nrd_firefly_clamp = min(clamp_indirect, 2.0f)`：UI 的 clamp_indirect 仍控制最终 radiance，但 NRD 实际看到的 diffuse/specular 输入亮度上限压到 2。这是用户亲手验证的有效量级，不再靠推测。
  - 本轮排除的误判（都核对过，均未改）：material ID `/3.0` 打包与 NRD 解码 `p.w*3.0` 匹配、非 bug；`minMaterialForSpecular` 差异是 ID 阈值非亮度；NRD 官方 material factor 下限就是 0.02（改 0.04 是错的）；灯光单位换算 radiance→irradiance 面积抵消、无 bug。
  - **build8 无效 → 真正根因（2026-11-27，逐项源码对照 NRD 4.18 + NRD-Sample 后确认）**：粉雾在 Denoised Diffuse / Indirect / Denoised Specular，Raw 通道干净。排除项（全部对照后确认一致/等价）：motion（`(prev_uv-curr_uv)·res - prev_jitter + curr_jitter` 等于 NRD-Sample unjittered motion）、normal octahedral 编码（与 `_NRD_EncodeNormalRoughness101010` 逐字节一致）、viewZ 符号（NRD 内部 `abs(z*viewZScale)`）、hitDist 参数（两边都 A=3,B=0.1,C=20）、YCoCg、factor 下限、材质 ID。
  - **根因**：`USE_MOVING_EMISSION_FIX` 的 emission proxy 加错了位置。我们是 `diff_radiance += emission_proxy` 然后整体 `1/diff_factor` 解调；红色发光体的 `diff_factor` G/B≈0.02，emission 被放大 ~50x，REBLUR 把极端色度 smear 到邻近地面 = 粉红雾。NRD-Sample（`TraceOpaque.cs.hlsl:544-548`）是 `demodulatedRadiance = radiance/factor; demodulatedRadiance += Lemi/(2π)`——proxy 加在**解调后**。
  - **修复（build9）**：`eevee_pathtracing_debug.bsl.hh` 把 emission proxy 从调制空间移到解调空间：`denoised_*_input = clamp(diff_radiance/diff_factor + emission_proxy, indirect_clamp)`。撤销 build8 的 `min(indirect_clamp,2.0)` 硬编码（基于错误推测），恢复用 UI 的 clamp_indirect。`frag_out.color` 显式加回 `2×emission_proxy` 保持最终图像 emission 能量不变。DirectEmission 通道（`primary_emission - 2×proxy`）不变。
- [x] 点光源贴近几何体时 firefly 爆炸
  - 根因：`irradiance = power / max(4π·distance², 1e-3)`，距离趋 0 时发散。
  - `eevee_pathtracing_debug.bsl.hh`：加 `min_distance_sq = max(radius², 1e-4)`，`radius` 取 `light.color_radius.a`（point/spot radius），下限再套 1e-4 防 radius=0。
- [x] UI 的 `clamp_indirect` 对最终间接信号不生效
  - 根因：最终 safety clamp 硬编码 1000，UI 值只影响部分直接/背景项。
  - `eevee_pathtracing_debug.bsl.hh`：最终 `diff_radiance` / `spec_radiance` 改用 `clamp_indirect`（`clamp <= 0` 语义仍是"不 clamp"）。
  - 附带修复一处乱码注释（Fresnel 能量补偿）。
  - 验证待办：重新编译后 GUI 检查 Raw/Hit Distance 单帧无拖影、相机移动无条纹、间接红光溢出消失、点光放入场景后 firefly 收敛、NRD Validation 仍可叠加。
  - **build9 GUI（2026-11-27 12:21）**：地面大面积粉红雾基本消失，只剩发光方块边缘局部亮晕（正常）。emission 解调位置根因确认。残留：画面上方一排离散红色 firefly 小点。
- [x] **转视角时 NRD 历史被逐帧清空，视图永不收敛（2026-11-27，build10 待验证）**
  - 用户对照 NRD-Sample：静止/转视角 validation 各通道（MV、Spec Frames）都正常持续；Blender 转视角时 MV 等调试短暂消失、Spec Frames 永远停在初始状态、视图一直噪点。
  - 根因链：转视角 → `velocity.camera_has_motion()` → `sampling.reset()`（`eevee_instance.cc:409`）→ `history_reset_pending_=true`（`pathtracing.cc:427`）→ `sampling_reset=true` → 旧的 `new_session` 包含 `sampling_reset` → `nrd_input.reset_history=true`（`pathtracing.cc:706`）→ `accumulationMode=CLEAR_AND_RESTART`（`vk_nrd.cc:293`）→ NRD 历史每帧清空，frame counter 永远归零。
  - 对照 NRD-Sample：`PrepareFrame` 每帧 `m_ForceHistoryReset=false`，相机移动**不**触发 reset（只有 frameIndex==0 / 改设置 / emission 突变才 reset）；`frameIndex` 连续递增，`accumulationMode` 恒为 CONTINUE，靠 motion vector + normal/depth 拒绝失效历史（`NRDSample.cpp:3469-3470, 940-942, 1764`）。
  - 关键背景：`pathtracing.cc:592-595` 旧注释承认"转视角清空历史是为了掩盖红球周围红色光晕"——该 workaround 掩盖的正是 build9 已修的 emission proxy 解调 bug，现已成为"视图永不收敛"的元凶，必须移除。
  - 修复（`eevee_pathtracing.cc`）：`new_session` 去掉 `sampling_reset`，只保留 `!started || resolution_changed || frame_jump`，供 NRD reset 用；TAA 双缓冲仍用 `new_session || sampling_reset` 重置（无拖影）；`prev_jitter_` 只在真正 new_session 时设为当前 jitter，转视角保留真实上一帧 jitter 供 NRD jitter delta 用。NRD motion vector 本就正确生成（`debug.bsl.hh:1159-1188`），失效历史由它拒绝，安全。

## 阶段 0d：MV / 历史键重构、性能优化与能量守恒（2026-11-27，build11–build18，已全部编译并 GUI 验证）

- [x] **build11：history key 碰撞导致 IN_MV 狂乱（红弧/红斑/viewport3 全黄）**
  - 根因：`ob->index` 是 Pass Index（默认 0），全场景物体 history key 碰撞 → `prev_object_to_world_` 全拿同一矩阵。
  - `eevee_pathtracing.cc:395` 历史键改 `ob->id.session_uid`。
  - **Y 轴 top-down 统一**：6 张 NRD 纹理写入 `nrd_texel=(frag.x, H-1-frag.y)`（normal/viewz/diff/spec/motion/shadow），direct+aux 保持 raster；composite/validation/taa 读侧配对翻转，`motion.y` 取反。
  - **矩阵 DX `[0,1]` + unjittered**：`nrd_view_to_clip` 转 DX（Z 行 `0.5*z+0.5*w`）；`PathTracingData` 加 `curr_world_to_view`/`curr_view_to_clip`；prev/curr 全存 main_view 的 unjittered 矩阵；debug shader 用两帧矩阵投影 hit 算 MV，去掉手动 jitter delta，`camera_jitter.y` 取反。
  - `data_buf_.sample_index` 改用模块 `frame_counter_`（去 8 帧循环）；`sun_penumbra` 去多余 `*0.5f`。
- [x] **build12 诊断 + build13 射线去重**：build12 临时禁用应用 MV（scale=0）证明底层坑全通（viewport3 纯黑、橙棋盘消失、红弧消失），4 行已在 build14 回退。build13 修通道口扇形噪点/1px 红线：`primary_ray_origin/direction` 保存为常量、lobe 循环内每轮重置；两处 `if (bounce==0u)` 改 `if (lobe==0u && bounce==0u)`。
- [x] **build14/15 性能优化 + TLAS 缓存**：移除 taa_pass（composite 直出 `CompositeFragOut`，省 1 pass + 2 张 RGBA16F，消 1px 红边）；主相机射线去重（trace 1 次、direct/bsdf samples 4→1、indirect 从 bounce=1）；跳过空栅格（`!path_tracing.enabled()` 包 capture/lookdev/background/volume/AO/forward/debug，保留 `deferred.render` 写深度）；TLAS 缓存（`last_depsgraph_update_`/`skip_sync_`/`has_moving_instance_`，`end_sync` 的 build+上传与 `render` 末尾 prev=current 拷贝包在 `if(!skip_sync_)`）；回退 build12 的 4 行诊断。
- [x] **build16/17 动态实例历史键**：build16 修 CoW `session_uid==0` 碰撞（用 `DEG_get_original`）和 BLAS key 从 `const Object*` 改 `const Mesh*`（共享 BLAS + `last_used_sync` 按 `sync_id_` 回收），自写 `HistoryKey{object_uid, occurrence, instance_index}`。build17 用 Blender 原生 `draw::ObjectKey(ob_ref, i)`（VelocityModule 同款，内部 `DEG_get_original`+`DupliObject::persistent_id`+`sub_key_`）替换，普通物体/CoW/Alt+D/集合实例/几何节点动态实例全部与 EEVEE 原生 MV 对齐；`sync_id_` 和 `Map<const Mesh*, ObjectGeometry>` 保留。
- [x] **build18 能量守恒 + MV 边界（当前 exe）**：
  - 能量守恒：间接漫反射漏乘 `(1-F)` 导致越弹越亮。加 `smith_lambda`/`smith_g2_over_g1`（高度相关 Smith GGX G2/G1）；主交点与次级反弹的 specular lobe 权重用 G2/G1、diffuse lobe 乘 `(1-f_env)`。**直接光 geometry 项仍用 `smith_g1`，按方案不动**。`nrd_material_factors` 的 diff/spec factor 是解调因子，未改。
  - MV 边界：新增 `project_screen_uv_unbounded`（去掉 `[0,1]` clamp），`nrd_motion` 的 prev/curr 都改调它，屏幕外进入的像素带真实越界 MV 由 NRD 丢弃历史；原 `project_screen_uv`/`previous_screen_uv` 保留。
  - 验证：高速前后移动/旋转视角下 Viewport 3（MV 误差）全程 100% 纯黑；Viewport 8/11 累积帧数与 NRD-Sample 一致（深蓝→紫→青→绿→黄渐进）。
- [ ] **待做（用户未给具体方案，未擅自改动）**：`eevee_pipeline.cc` 跳过 DeferredLayer 着色（只留 depth prepass）提升帧率。当前 `deferred.render()` 着色阶段仍在跑。

## 阶段 0：可观测性与测试基线

- [x] NRD `OUT_VALIDATION` 覆盖层
  - `GPU_nrd.hh`：`NrdDenoiseInput::validation`。
  - `vk_nrd.cc`：`EEVEE_PT_NRD_VALIDATE`、`enableValidation`、`OUT_VALIDATION` 快照。
  - `eevee_renderbuffers.*`：`nrd_validation_tx`（RGBA8 UNORM）。
  - 新增 `eevee_pathtracing_validation.bsl.hh`，在 TAA 后、flip 前叠加到 `combined_fb`。
  - 验证：4x4 viewport 覆盖层可见，`lerp(base, validation.rgb, validation.a)` 与 NRD `Final.cs.hlsl` 一致。
- [x] 材质记录 dump
  - `EEVEE_PT_DUMP_MATERIALS=1` 或指定路径；输出 `pt_materials.json`。
  - 字段：index/name/fallback/base_color/roughness/metallic/transmission/ior/closure_offset/closure_count/flags/texture_offset/object_info_offset/aov_offset。
  - 验证：material 场景 5 个材质，中文名正常，`ConvertFrom-Json` 通过；默认材质 `ior=1.5`。
- [x] 测试场景
  - `scenes/pt_test_room.blend`：红金属球、玻璃球、粗糙球、面光。
  - `scenes/pt_test_motion.blend`：10 帧移动球 + 相机旋转。
  - `scenes/pt_test_material.blend`：Image Texture 立方体 + 程序化节点球。
- [x] Baseline
  - `baseline/pt_test_motion/`：10 帧，320x240，16 spp。
  - `baseline/pt_test_room/`：3 帧，320x240，32 spp。
  - `baseline/pt_test_material/`：3 帧，320x240，32 spp。
- [x] 测试入口
  - `tools/pt_test.ps1` 自动查找 NVIDIA Vulkan ICD。
  - `tools/pt_auto_test.py` 支持 `normal/no_history/raw/validation/rr` 等 case，并清理 `EEVEE_PT_*` 环境变量。

## 阶段 1：NRD 契约与概率

- [x] `EstimateDiffuseProbability()` 对齐 NRD-Sample
  - `lumDiff / max(lumDiff + lumSpec, eps)`，clamp `[0.05, 0.95]`。
  - `<0.005` 返回 0，`>0.995` 返回 1。
- [x] Primary bounce 概率 clamp
  - `bounce==1` 使用 `[0.25, 0.75]`；`bounce>1` 使用原始概率。
  - 与 NRD-Sample `gMinProbability`（AREA_3X3=0.25）一致。
- [x] Bayer 4x4 dither
  - `bayer4x4(pixel, frame)` + `rnd / 16.0`，仅在 NRD 采样点使用。
- [x] NRD 设置
  - `HitDistanceReconstructionMode::AREA_3X3`。
  - `enableAntiFirefly = true`。
  - `diffusePrepassBlurRadius = 30.0f`，`specularPrepassBlurRadius = 50.0f`。
- [x] Russian Roulette 默认关闭
  - 仅 `EEVEE_PT_USE_RR=1`（映射到 debug flag bit 16）启用，用于 A/B。
  - 不再做旧 RR 分支里那套间接 diffuse 的 `(1-F)` 能量补偿（那是 11-25 移除的旧写法）。**注意与 build18 的区别**：build18 补回的 `(1-F_env)` 是主交点/次级 bounce 的 lobe 采样权重能量守恒（漫反射 lobe 乘 `1-f_env`），用于修"越弹越亮"，两者作用位置不同，不矛盾。见阶段 0d。
- [x] 移除旧的 `MAX_DIFFUSE_DEPTH` / 概率截断假设，避免与 NRD 契约冲突。

## 阶段 2：能量与 clamp

- [x] 新增 `luminance()`、`clamp_radiance_luminance_preserving()`、`valid_radiance()`。
- [x] 背景、fallback、direct、BSDF specular、最终 1000 安全 clamp 全部改为亮度保持缩放，避免高亮红色光源被压成白色。
- [x] `throughput` 阈值 `0.001`；RR 分支按存活概率除以 `p`。
- [x] 最终 accumulation 做 NaN/INF sanitization。
- [x] 保留 `PT_MAX_FIREFLY_RELATIVE_INTENSITY=20`、`PT_EVIL_TWIN_LOBE_TOLERANCE=0.005` 语义（由 NRD 与 clamp 路径覆盖）。

## 阶段 3：TAA

- [x] 误差改为 chroma 加权：`luma*0.5 + length(chroma)*2.0`。
- [x] `min_weight` 固定为 `0.0606f`。
- [x] 删除 motion/variance 动态 distrust（会放大闪烁）；`sigma` 仅用于 `ClampAabb`。
- [x] 相机/场景变化时重置 NRD/TAA history，避免旧 motion vector 重投影。
- [x] 视口验证：静止相机 80 redraws、移动相机后 80 redraws，均未复现红弧。
  - 证据：`C:\Users\q1553\AppData\Local\Temp\opencode\pt_gui\after_80_static.png`、`after_80_moved.png`。
  - 仍需在多场景、多 GPU、不同分辨率下复验。

## 阶段 3.5：间接光回归修复（2026-11-26）

- [x] 定位 `aux_buf_` 只分配 1 个元素
  - `end_sync()` 中 `render_buffers.extent_get()` 仍为 0，`aux_buf_.resize(max(1, 0))` 导致除像素 0 外全部越界写。
  - 证据：factor 视图均值 0.088/0.083，仅左下 2x2 像素非零；raw diffuse/specular 视图正常。
- [x] 将 `aux_buf_.resize(...)` 移到 `render()` 的 `extent_get()` 之后，并用同一 extent 写入 `data_buf_.resolution`。
- [x] 验证移除额外 barrier 不影响结果；path pass 末尾 `GPU_finish()` 已提供可见性。
- [x] 删除临时 debug view 9-12 与 barrier 实验代码，clean build 通过。
- [x] 修复后回归：`normal` 190.076、间接光视图 173.947、factor 视图 171.198；GUI 80 redraws 中心区域 RGB mean 190.708/181.203/179.908，无红弧。
  - 证据：`C:\Users\q1553\AppData\Local\Temp\opencode\pt_gui\after_80_fixed.png`。

## 阶段 3.6：SIGMA 太阳软阴影修复（2026-11-26）

- [x] 定位主命中点太阳被硬阴影提前剔除：直接光循环对 `bounce==0 && light_type==1` 也做 shadow ray，命中即 `continue`，导致 composite 的 `sun_fraction=0`，SIGMA 无内容可调制。
- [x] 改为仅对局部光源和 `bounce>0` 的间接太阳做 visibility ray；主命中点太阳 direct 保持 unshadowed，由 SIGMA `shadow` 调制。
- [x] 太阳角度 A/B（0.5° vs 10°，暗世界）验证：10° 阴影边缘明显更软。`sharp_dark_final` vs `soft_dark_final` normal 差异 mean 0.161/0.145/0.145、rms 1.872/2.137/2.137、最大通道差 83。
- [x] 删除临时 debug view 13/14，最终 clean build `build_final_sigma.log` 通过。
- [x] `raw` case 两角度图像相同，确认是 `shadow=1` 的预期行为，SIGMA 验收统一使用 `normal`。

## 阶段 3.7：视口 PT 采样上限修复（2026-11-26）

- [x] 定位视口 PT 只累积约 16 sample：`Sampling::init` 对视口使用 `scene->eevee.taa_samples`（默认 16），`finished_viewport()` 到值即停止。
- [x] 在 `eevee_sampling.cc` 增加 `pathtracing_viewport` 判断（视口 + `GPU_ray_query_support()` + SSR 开启 + `RAYTRACE_EEVEE_METHOD_PATH_TRACING`），命中时使用 `infinite_sample_count_`。
- [x] 保持普通 EEVEE 视口行为不变，仍按 `taa_samples` 停止；避免 ray query 不支持时回退普通 EEVEE 却无限累积。
- [x] 验证：GUI 80 redraws，`EEVEE_PT_DEBUG_RESET=1` 输出 sample 81，`scene.eevee.taa_samples=64`，确认超过 64 且无 sampling reset。
- [x] 8 spp 隔离确认 NRD 空间降噪有效（`diffuse_nrd_only` 比 `diffuse_raw` 平滑）；低 spp 剩余噪声属于时间累积不足，不通过提高 samples 掩盖。

## 阶段 4/5（暂缓）

- [ ] 材质 Atlas / 纹理节点树 / PT closure list。
- [ ] 程序化 Bake 与 AOV。
- [ ] transmission / emission / volume / hair。
- [ ] BLAS/primitive 索引映射修复。
- [ ] `WITH_NRD` 可选模块与许可证审查。

## 回归命令

```powershell
# 批量 case
.\tools\pt_test.ps1 -Blender "D:\build_windows_x64_vc17_Release\bin\Release\blender.exe" `
  -Scene ".\scenes\pt_test_room.blend" -Cases normal,no_history,raw,validation,rr `
  -Samples 64 -Percent 50 -NoCycles

# baseline
& "D:\build_windows_x64_vc17_Release\bin\Release\blender.exe" --background --factory-startup `
  --gpu-backend vulkan ".\scenes\pt_test_motion.blend" `
  --python ".\tools\render_pt_baseline.py" -- `
  --out ".\baseline\pt_test_motion" --frames 1-10 --samples 16 --percent 50

# 材质 dump
.\tools\pt_test.ps1 -Blender "D:\build_windows_x64_vc17_Release\bin\Release\blender.exe" `
  -Scene ".\scenes\pt_test_material.blend" `
  -ExtraCase "dump=EEVEE_PT_DUMP_MATERIALS=$PWD\pt_materials.json" `
  -Cases dump -Samples 1 -Percent 25 -NoCycles
```

## 已知限制

- Headless still 每次 `bpy.ops.render.render()` 从 sample 0 开始，跨帧 TAA history 不连续；跨帧验证需要 GUI viewport 或多 redraw harness。
- `EEVEE_PT_NRD_VALIDATE` 覆盖层会遮挡中心画面，只用于诊断。
- 玻璃球仍因 transmission 未实现而发白。
- 材质 dump 每次 `end_sync` 都会重写文件，后续可加限流。
