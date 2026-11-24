# EEVEE 实时路径追踪架构笔记

本文记录 Blender 5.3 EEVEE 的现状、GPU 硬件光追能力、目标架构和关键风险。结论按“已确认 / 待验证”区分。

## 1. 设计原则

1. **复用 EEVEE，不做壳**：路径追踪必须接入 `eevee::Instance`、`Film`、`RenderBuffers`、`GPU_material` 和节点 closure 体系。
2. **材质单一来源**：路径追踪不能另建材质系统；节点树仍由 Blender GPU material 编译，路径追踪读取同一套 closure/参数。
3. **输出单一来源**：路径追踪结果写入 `Film`/`RenderBuffers`，由现有合成器和视口链路消费。
4. **硬件 RT 优先**：Vulkan/Metal 使用 ray query；OpenGL 无硬件 RT 时安全回退。
5. **分阶段交付**：先三角形 + 基础材质 + 直接光/单 bounce，再扩展多 bounce、体积、毛发、降噪和性能。

## 2. EEVEE 5.3 现状

### 2.1 引擎结构

已确认：

- 5.3 没有独立 `eevee_next` 目录；EEVEE Next 已并入 `source/blender/draw/engines/eevee`。
- `eevee::Instance : DrawEngine` 是引擎实例，聚合 Film、RenderBuffers、Sampling、RayTrace、Pipeline 等模块。
- `eevee_instance.cc` 中 `render_sample()` 编排采样流程，`render_read_result()` 读取渲染结果。
- `eevee_pipeline.hh/.cc` 包含 deferred G-buffer、光照、世界、探针、ray trace 等 pass 组织。
- 现有 ray trace 是屏幕空间方案，依赖深度/法线/历史缓冲，不是路径追踪。
- 现有光照依赖 light probe、irradiance cache、屏幕空间反射/折射等。

已确认的 `render_sample()` 顺序（`eevee_instance.cc` L558-L604）：

```text
if sampling.finished_viewport():
  push uniform -> film.display() -> lookdev.display() -> return

if !is_viewport() && sampling.do_render_sync():
  render_sync() + wait for queued shaders/textures + render_sync() again

DRW_submission_start()
sampling.step()
film.update_sample_table()
uniform_data.push_update()
capture_view.render_world()
lookdev.rotate_world()
capture_view.render_probes()
main_view.render()
lookdev_view.render()
DRW_submission_end()
motion_blur.step()
```

已确认的视口路径（`eevee_instance.cc` L750-L825）：

- `Instance::draw_viewport()`：检查 shader 是否加载；`render_sample()`；`velocity.step_swap()`；若 `is_viewport_compositor_used`，调用 `film.write_viewport_compositor_passes()`；未完成采样且非 playback 时请求重绘。
- `Instance::draw_viewport_image_render()`：循环 `render_sample()` 直到 `sampling.finished_viewport()`，再 `velocity.step_swap()` 和 viewport compositor pass 写出。
- `render_read_result()`（L606）按 `film.enabled_passes_get()` 遍历 pass，`film.read_pass()` 写回 `RenderPass`。

路径追踪接入点：

- `main_view.render()` 前后是路径追踪主 pass 的候选接入点；需要保留 `capture_view`（世界/探针）和 `lookdev_view` 的现有职责。
- 视口合成器依赖 `film.write_viewport_compositor_passes()`，路径追踪 pass 必须先写入 Film。
- 采样完成/重置由 `sampling` 模块控制，路径追踪需要接入 `sampling.step()`/`finished_viewport()` 的生命周期。

已定位的关键符号（`eevee_pipeline.cc`）：

- `BackgroundPipeline::render`（约 L82）、`WorldPipeline::render`（L137）、`WorldVolumePipeline::render`（L177）。
- `ShadowPipeline::render`（L230）、`ForwardPipeline::render`（L629）。
- `DeferredLayer::gbuffer_pass_sync`（L709）、`DeferredLayer::begin_sync`（L777）、`DeferredLayer::render`（L1073）。
- `DeferredPipeline::render`（L1254）、`DeferredProbePipeline::render`（L1566）、`PlanarProbePipeline::render`（L1666）、`CapturePipeline::render`（L1747）。
- Deferred shader 变体包含 `Deferred.NoRaycast.*` / `Deferred.Raycast.*`（约 L738-L739），说明现有 raycast 分支已存在于 deferred 材质 pass。
- `VolumePipeline::render`（L1421）独立处理体积，路径追踪需决定复用还是替换。

已定位的关键符号（`eevee_film.cc`）：

- `Film::init`（L301）读取 `bke::compositor::get_used_passes`，计算 `viewport_compositor_enabled_passes_`（L322-L330）。
- `Film::init_aovs`（L39）、`Film::sync`（L614）、`Film::end_sync`（L722）。
- `Film::accumulate`（L932）、`Film::display`（L962）、`Film::read_pass`（L990）、`Film::get_pass_texture`（L1009）。
- `Film::write_viewport_compositor_passes`（L1072）按 `viewport_compositor_enabled_passes_` 写出 pass。

已定位的关键符号（`eevee_material.cc`）：

- `MaterialModule::material_pass_get`（L140）负责从 `GPU_material` 取得 material pass。
- `MaterialModule::material_sync`（L239）按 `MaterialKey` 缓存材质。
- `GPU_material_flag_get(..., GPU_MATFLAG_TRANSPARENT)`（约 L190）区分透明材质。
- `GPU_material_has_surface_output` / `GPU_material_has_volume_output`（约 L294-L324）区分表面/体积。
- `MAT_PIPE_*`、`MAT_GEOM_*`、`eMaterialPipeline` 决定材质编译变体。

待验证：

- `Film` 与 `RenderBuffers` 的 pass 注册/读取细节。
- `eevee_material.cc` 中 GPU material 编译和 closure 打包细节。
- `main_view.render()` 内部各 pipeline 的精确调用顺序。

### 2.2 渲染数据流（高层）

```text
Blender depsgraph
  -> EEVEE Instance scene sync
  -> GPU material compilation (node tree -> closures)
  -> RenderBuffers / Film allocation
  -> Pipeline passes (G-buffer, lighting, probes, ray trace)
  -> Film resolve / pass output
  -> Viewport display or Compositor
```

路径追踪改造点：

- 在 scene sync 后构建路径追踪场景数据（TLAS/BLAS、材质表、光源表）。
- 用路径追踪 pass 替换/补充现有主光照 pass。
- 继续使用 Film 的 pass/AOV 输出和 compositor 桥接。
- 视口使用渐进累积和重置策略。

### 2.3 材质与节点

已确认：

- 材质通过 `GPU_material` 从节点树编译；`GPU_generate_pass` 按引擎缓存 pass，`GPUCodegenOutput` 输出 `surface/volume/thickness/displacement/composite/material_functions/attr_load`。
- 节点实现只依赖 `gpu/shaders/material/gpu_shader_material_interface.bsl.hh`。该接口由引擎运行时替换，包含 `ShadingData`、`KernelGlobals`、`closure_eval`、坐标/属性/灯光/AO/Raycast 等；EEVEE 的实现位于 `eevee_nodetree_lib.bsl.hh`。
- GPU material shader 位于 `source/blender/gpu/shaders/material`，约 120 个文件；约 50 处调用 `closure_eval`。逐个节点写 PT C++ 不可维护。
- `GPU_MATFLAG_*` 控制材质编译特性（如 raycast、lighting、shader-to-rgba、object info 等）。
- EEVEE 的 `Closure` 是 `float` 句柄，`closure_eval` 通过副作用写 3 个 closure bin/reservoir；`closure_add`/`closure_mix` 是 NOP。**NOP 不代表 Mix Shader 无效**：`ntreeGPUMaterialNodes()` 先调用 `ntree_shader_weight_tree_invert()` 把 Mix/Add 展开为每个 closure 的 `Weight` 输入，`closure_mix/add` 只是权重展开后的终点。实测 EEVEE Mix fac=0/0.5/1 为红/紫/蓝；当前 PT 因只接受 Surface 直连 Principled 而全回退。Cycles `transform_multi_closure()` 采用同一策略。

路径追踪需要：

- 实现 PT 版 engine interface（`KernelGlobals`/`ShadingData`/`Closure`/`closure_eval` 等），复用 `GPU_material` 生成的节点树函数，不重新解释节点树，也不逐节点适配。
- 新增 `GPU_MAT_PATHTRACING` 和 PT 版 `material_create_info_amend`；节点图编译一次，材质记录只保存 GPU 材质/资源句柄、flags 和 closure 索引。
- 定义 PT closure 句柄/list（容量、溢出、闭包权重、MIS）；复用 EEVEE 权重树带来的 `Weight` 语义，不手写 Mix/Add 的 `fac`，也不直接照搬 3-bin reservoir。
- 对不能直接表达的节点定义近似/回退/限制，并在 UI/文档中提示；纹理导数、属性 domain、多材质绑定属于接口级问题。

### 2.4 Film、Pass 与合成器

已确认：

- `Film` 负责 pass/AOV/视口合成器输出。
- 存在 `Film::write_viewport_compositor_passes()`、`viewport_compositor_enabled_passes_`、`init_aovs()`。
- 合成器通过 `bke::compositor::get_used_passes` 等机制决定需要的 pass。
- `RenderBuffers` 管理 pass 纹理。

路径追踪需要：

- 将 Combined、Diffuse、Specular、Depth、Vector、Normal、AOV 等写入 Film/RenderBuffers。
- 保持 pass 名称和语义与 EEVEE 一致，避免合成器节点读不到。
- 视口合成器开启时，确保路径追踪 pass 在正确的生命周期内可用。

## 3. GPU 硬件光追能力

### 3.1 公共 API

已确认：

- `source/blender/gpu/GPU_ray_tracing.hh` 提供 TLAS/BLAS 和 ray query 能力。
- `GPU_ray_tracing_tlas_alloc()` / `GPU_ray_tracing_blas_alloc()` 创建加速结构。
- `GPU_ray_query_support()` 查询后端能力。
- shader 侧可用 `rayQuery` + `ACCELERATION_STRUCTURE`。
- Vulkan 后端实现位于 `source/blender/gpu/vulkan/vk_ray_tracing.cc`。
- Metal 也有 ray query 支持。
- Workbench 的 `workbench_shadow_raytrace.bsl.hh` 是现有硬件 RT 示例。
- 测试：`source/blender/gpu/tests/ray_tracing_test.cc`、`gpu_ray_query_test.glsl`。

公共 API 签名（`GPU_ray_tracing.hh`）：

```cpp
struct InstanceID { int64_t id; };

class TopLevelAS {
  virtual InstanceID add_instance(const BottomLevelAS &blas,
                                  const float4x4 &mat,
                                  uint8_t mask = 0xFF) = 0;
  virtual void update_instance(InstanceID instance_id,
                               const float4x4 &mat,
                               uint8_t mask = 0xFF) = 0;
  virtual void build() = 0;
  virtual void bind(int slot) = 0;
};

class BottomLevelAS {
  virtual void add_geometry(IndexBuf &index_buffer, VertBuf &vertex_buffer) = 0;
  virtual void build() = 0;
};
```

缺口：

- `add_instance()` 没有 `custom_index`、`object_id`、`visibility`、`flags` 参数。
- `update_instance()` 只能更新矩阵/mask。
- `add_geometry()` 只接受 index/vertex buffer，没有 material/object ID、any-hit/opacity、geometry flags。
- `InstanceID` 只是 TLAS 内序号，不是 Blender 对象 ID。

### 3.2 当前 BLAS/TLAS 限制

已确认：

- BLAS 主要从 mesh 的 position IBO/VBO 构建，见 `draw_cache_impl_mesh.cc` 中 `surface_blas->add_geometry(...)`。
- `VKBottomLevelAS::add_geometry()` 只创建 `VK_GEOMETRY_TYPE_TRIANGLES_KHR`，并固定 `VK_GEOMETRY_OPAQUE_BIT_KHR`；没有 any-hit、alpha 测试或 per-triangle material ID。
- `VKTopLevelAS::add_instance()` 的 `instanceCustomIndex` 固定为 `0`，`instanceShaderBindingTableRecordOffset` 和 `flags` 也为 `0`；只支持 BLAS、矩阵和 8-bit mask。
- TLAS 构建后不能继续 add instance，只能通过 `update_instance()` 更新矩阵/mask。
- 公共 `TopLevelAS::add_instance()` 未暴露 per-instance custom index/object metadata。
- 现有 ray query 测试可以读取 instance custom index，但生产 API 未提供完整元数据链路。
- **Primitive 顺序不一致（2026-11-16 确认）**：BLAS 使用 `IBOType::Tris`；该 IBO 在多材质或存在 `hide_poly` 时由 `extract_tris_mesh()` 按 `SortedFaceData.face_tri_offsets` 按材质重排并过滤隐藏面。PT 的 `PrimitiveRecord` 按原始 `Mesh::corner_tris()` 生成，且 `corner_tris()` 包含隐藏面。因此 `rayQueryGetIntersectionPrimitiveIndex()` 与 PT primitive 表错位，材质/法线/后续三角形会错，甚至跨入相邻实例的 primitive 范围。
- **Material table 对齐**：`mr.materials_num` 来自 `BKE_object_material_used_with_fallback_eval()`，是最大已用材质索引 +1；PT `material_base` 按 `ob->totcol` 递增，clamp 到 `materials_num-1`。多 slot/空 slot 时两者不一致。

影响：

- 路径追踪命中三角形后，无法直接知道材质/对象。
- 需要扩展 BLAS 或额外缓冲，把 primitive ID 映射到材质/对象。
- 在修复映射前，必须让 PT primitive 表与 BLAS 实际三角形顺序完全一致（同材质排序、同隐藏面过滤），或为 PT 单独建 BLAS；否则多材质/隐藏面场景无法正确着色。可复现 `extract_tris_mesh()`：按 `clamp(material_index, 0, materials_num-1)` 稳定分组、组内保持 face 顺序、跳过 `hide_poly`。注意 `materials_num` 可能大于 `ob->totcol`，分组键与材质记录索引必须同规则。
- 需要扩展 TLAS instance，把 instance ID 映射到变换、对象、可见性等。
- `VK_GEOMETRY_OPAQUE_BIT_KHR` 会阻止 alpha/透明材质走 any-hit；必须新增非 opaque 几何或手动继续追踪。
- 动态实例只能更新矩阵/mask，不能更新 custom index；需要重新设计 TLAS 更新接口。

### 3.3 几何类型限制

- 硬件 ray query 以三角形为主。
- Hair/Curve 需要自定义相交（曲线段/胶囊体）或转换为三角形代理。
- Volume 需要体积积分/ voxel/SDF 方案，不能只靠三角形 ray query。
- 透明/alpha 需要 any-hit 或手动继续追踪；硬件 API 是否支持可配置 any-hit 需验证。
- 动态网格需要 BLAS 重建/更新策略；实例化需要 TLAS 更新。

## 4. 目标架构

### 4.1 模块划分

建议在 EEVEE 内新增路径追踪模块，而不是独立引擎：

```text
eevee/
  eevee_instance.*          # 生命周期、模式选择
  eevee_pipeline.*          # 现有 deferred 路径
  eevee_pathtracing.*       # 新增：路径追踪编排
  eevee_pathtracing_scene.* # 新增：TLAS/BLAS、材质表、光源表
  eevee_pathtracing_shading.*# 新增：closure 求值、NEE/MIS
  eevee_pathtracing_denoise.*# 新增：降噪/时序接口
  shaders/
    eevee_pathtracing_*.bsl.hh
```

模块职责：

- `PathTracingModule`：每帧准备、dispatch、输出、重置。
- `PathTracingScene`：场景数据同步、加速结构、材质/光源缓冲。
- `PathTracingIntegrator`：路径采样、bounce、MIS、RR。
- `PathTracingDenoiser`：降噪后端抽象、历史管理。
- `PathTracingFilmBridge`：写入 Film/RenderBuffers/pass。

### 4.2 每帧数据流

```text
1. Scene sync
   - 收集可见 mesh/instance/light/material
   - 更新 BLAS（几何变化）
   - 更新 TLAS（变换/可见性）
   - 上传 MaterialRecord / LightRecord / InstanceRecord

2. Prepare
   - 相机参数、分辨率、jitter、采样数
   - 分配/复用 history、guiding buffers
   - 检查能力与回退

3. Trace
   - camera ray
   - NEE / MIS
   - indirect bounce
   - environment / volume / hair

4. Resolve
   - 写入 radiance、depth、normal、vector、AOV
   - 时序累积
   - 降噪
   - Film pass 输出

5. Display / Compositor
   - viewport display
   - viewport compositor
   - final render readback
```

### 4.3 GPU 数据结构（草案；M4 后材质 ABI 调整）

EEVEE 的 GPU closure 布局是参考，不是 PT 必须照搬的 ABI。EEVEE 的 `Closure` 实际是 `float` 句柄，`closure_eval` 写 3-bin reservoir；`closure_add`/`closure_mix` 是权重树展开后的 NOP，Mix Shader 的 `fac` 已在预处理阶段写入各闭包的 `Weight`。PT 需要自己的 closure list/句柄语义，但应复用同一权重树，而不是重新实现 Mix/Add。closure 类型和参数布局可复用，定义位于
`source/blender/gpu/shaders/gpu_shader_codegen_lib.glsl`：

```text
ClosureType:
  CLOSURE_NONE_ID                         = 0
  CLOSURE_BSDF_DIFFUSE_ID                 = 1
  CLOSURE_BSDF_TRANSLUCENT_ID             = 6
  CLOSURE_BSDF_MICROFACET_GGX_REFLECTION_ID = 7
  CLOSURE_BSDF_MICROFACET_GGX_REFRACTION_ID = 12
  CLOSURE_BSDF_THIN_GLASS_TRANSMISSION_ID = 13
  CLOSURE_BSSRDF_BURLEY_ID                = 15

ClosureUndetermined:
  packed_float3 color
  packed_float3 N
  uchar         type
  packed_float4 data
```

`GPU_MATFLAG_*` 到 `eClosureBits` 的映射在 `eevee_material.hh` L146-L183；材质同步时应复用该映射，不另建一套语义。

建议的路径追踪 GPU 记录：

```text
PathTracingData:
  uint2  resolution
  uint   instance_count
  uint   primitive_count
  uint   material_count
  uint   light_count
  uint   sample_index
  uint   pad0
  float4 background             // 16B aligned
  uint   max_bounces            // 0 由 CPU 兜底为 8，范围 1..64
  float  clamp_direct           // <=0 表示关闭
  float  clamp_indirect         // <=0 表示关闭
  uint   pad1                   // 64 bytes total

InstanceRecord:
  float4x4 object_to_world
  uint     primitive_offset
  uint     primitive_count
  uint     material_table_offset
  uint     object_id
  uint     visibility_mask
  uint     flags
  uint     pad[2]

PrimitiveRecord:
  float4 normal                 // object-space geometric normal
  uint   material_id
  uint   object_id
  uint   geometry_index
  uint   flags
  float  area
  uint   uv_layer_offset
  uint   attribute_offset
  uint   pad[1]

MaterialRecord:
  uint   gpu_material_id        // GPU_material/资源表索引
  uint   closure_offset
  uint   closure_count
  uint   texture_offset
  uint   object_info_offset
  uint   aov_offset
  uint   flags                  // GPU_MATFLAG_* 子集
  uint   pad[1]
  // 目标：删除 float4 base_color/params 逐 socket 常量；
  // 当前 MVP 仍保留这两个字段，M4 迁移后移除。

LightRecord:
  float4 position_type          // xyz=world position, w=eLightType
  float4 direction_power        // xyz=forward, w=power/sun strength
  float4 color_radius           // rgb=color, a=radius/area size
  float4 spot_flags             // x=spot size, y=spot blend, z=flags, w=pad
```

数据来源与更新时机：

| 数据 | 来源 | 更新时机 |
|---|---|---|
| `InstanceRecord` | `Object`/`ObjectRef`/draw sync | 对象变换、可见性、材质变化 |
| `PrimitiveRecord` | mesh loops/polys、材质槽 | 几何或材质槽变化 |
| `MaterialRecord` | `Material`、`GPU_material` | 材质节点或编译结果变化 |
| `LightRecord` | `Light` 对象、世界光 | 光源参数/变换变化 |
| `closure buffer` | `GPU_MAT_PATHTRACING`/PT 材质求值 | 每个 shading point 求值 |
| TLAS/BLAS | `InstanceRecord`/`PrimitiveRecord` | 变换、几何、可见性变化 |
| Film pass | integrator 输出 | 每个 sample |

说明：

- `InstanceRecord` 在数组中的下标就是 TLAS `instanceCustomIndex`；shader 用它直接索引 instance buffer。
- `rayQueryGetIntersectionPrimitiveIndex(query, true)` 返回 geometry-local 索引；每个 BLAS geometry 必须额外保存 `primitive_offset`/`primitive_count`，不能假设全局 primitive ID。
- `instanceCustomIndex` 只有 24 bit，必须校验场景实例数并做上限检查。
- `ClosureUndetermined` 不是天然 std430 对齐；上传前按 16 字节补齐，或使用与 shader 完全一致的 packed 布局。
- 透明/alpha：不依赖 any-hit shader，使用 inline ray query 的 candidate 循环，命中后取 UV/属性做 alpha 判断，不通过则继续 `rayQueryProceed()`。
- Hair/Curve/Volume 不走三角形 BLAS；先保留代理几何/自定义相交接口，后续单独实现。

#### 4.3.1 材质求值方式（关键决策）

不能从 ray query 直接调用 EEVEE 的 fragment shader，也不能逐节点解析 `bNode`/`bNodeSocket`。路径追踪需要新增统一材质求值路径：

```text
GPU_material (同一节点树, PT engine)
  -> PT material shader: KernelGlobals + ShadingData + PT Closure
  -> 命中点按 material ID 分组 dispatch
  -> 输出 PT closure list / closure buffer
  -> integrator 采样 closure 并做 MIS
```

已确认：

- 节点实现只依赖 `gpu_shader_material_interface.bsl.hh`；PT 实现该接口即可覆盖绝大多数节点，不需要逐节点写 C++。
- `GPU_material_from_nodetree`/`GPU_generate_pass` 已按引擎缓存材质 pass；`GPUCodegenOutput` 已包含 surface/volume/thickness/displacement/composite/material_functions。
- `GPUCodegen::generate_attribs()` 默认生成 vertex input/StageInterface；PT compute 需要 hit-domain 属性读取或 fragment `attrib_load` 变体。参考 `eevee_shader.cc:1239` 的 world/volume fragment 路径。
- `PassBase::material_set` 按 `GPU_material` 绑定 UBO/纹理；多材质命中必须 material-major 分组 dispatch，或改用 bindless 资源表。
- 纹理 LOD/bump 依赖 `gpu_dfdx/gpu_dfdy`；compute 中导数退化。PT 需要 ray differential/tangent frame，首版允许 LOD0/bump 近似但必须显式标注。
- `FrontFacing` 在非 fragment 阶段被定义为 `true`（`gpu_shader_codegen_lib.glsl:77-81`），但 `normal_map.bsl.hh:38`、`bump.bsl.hh:39` 依赖它；PT compute 必须改用 `sd.front_facing`（preamble `#undef`/重定义）或做接口级修正，否则背面法线/凹凸错误。
- `node_bump()` 的非 fragment 分支直接 `result=N`，`dF_impl()` 在非 fragment 返回 0；PT 的 Bump 需要 ray differential 或替代实现，不能只靠增加 samples。
- `Closure` 句柄可保持 dummy（EEVEE 就是 `float`）。节点通过 `closure_eval()` 副作用写 `ShadingData`，`closure_add/mix` 返回 NOP，Output 只传递 dummy；PT 可照此把闭包追加到 `sd` 的 list，不需要闭包树句柄。
- EEVEE 在 `eevee_shader.cc:1395-1401` 生成 `nodetree_surface()`：先 `closure_weights_reset()`，再插入 `codegen.surface.serialized`。PT 应生成同名包装函数，但重置/收集到自己的 closure list，不复制 EEVEE fragment/GBuffer 管线。
- EEVEE 的 `codegen.attr_load` 在 `eevee_shader.cc:1238-1304` 根据 geometry/pipeline 决定放 vertex 还是 fragment；PT 需要新的 hit-domain 分支，把属性读改写为全局属性 buffer/资源表，不能直接沿用 vertex input。

设计要求：

- 新增 `GPU_MAT_PATHTRACING` 和 PT 版 `material_create_info_amend`，不修改 EEVEE fragment 变体；`target_engine_` 需决定使用 `SHD_OUTPUT_EEVEE` 还是独立输出。
- PT `Closure` 使用固定容量 list（首版候选 8）+ emission/transmittance/volume；`closure_eval` 追加带权闭包，溢出用加权 reservoir 或明确回退。**不要实现 Mix/Add 的 fac**：EEVEE/Cycles 都已把 Mix/Add 展开为每个闭包的 `Weight`，PT 只消费该权重；EEVEE 的 3-bin reservoir 不直接复用。
- **前置修复**：PT primitive 表必须与 BLAS 的材质排序/隐藏面过滤一致（或 PT 单独 BLAS），并让 `material_base`/`materials_num` 与 `MaterialRecord` 对齐；否则统一材质求值仍会读错 primitive 和材质。
- `MaterialRecord` 从 `base_color/params` 改为 `gpu_material_id`、资源表索引、flags、closure 能力标志；逐 socket 常量路径删除。
- Primary hit 可先复用 deferred G-buffer；secondary hit 走 PT material pass；最终统一所有 hit。
- Material-major 执行模型：每 bounce 先 trace/写 hit record，再按 `material_id` 分桶/排序，每个材质一次 `PassBase::material_set()` + compute dispatch，只处理该材质的 hit 队列；输出下一 bounce ray/累积。primary hit 可直接用 deferred G-buffer 分材质 shading。这样不需要 bindless 多材质资源表，也避免 mega-shader 编译爆炸；代价是队列/排序/多次 dispatch。混合 mega-shader（所有材质一个 shader）只作为小场景备选。
- 队列方案要求 hit record 包含 `material_id`、`object_id`/`instance_id`、primitive/三角形、barycentric、UV/属性索引和 ray throughput；`PassBase` 的 compute dispatch 可逐材质绑定 UBO/纹理。
- 仅对 Shader to RGB、Raycast、Light Path、Volume/Hair 等语义不同类别定义近似/回退；节点兼容矩阵用于验证语义，不是实现清单。

#### 4.3.2 Film pass 映射（草案）

优先复用现有 `eViewLayerEEVEEPassType`，不新增 pass enum：

| 路径追踪输出 | Film pass |
|---|---|
| Combined | `EEVEE_RENDER_PASS_COMBINED` |
| Depth | `EEVEE_RENDER_PASS_DEPTH` |
| Normal | `EEVEE_RENDER_PASS_NORMAL` |
| Position | `EEVEE_RENDER_PASS_POSITION` |
| Vector | `EEVEE_RENDER_PASS_VECTOR` |
| Diffuse Light | `EEVEE_RENDER_PASS_DIFFUSE_LIGHT` |
| Diffuse Color | `EEVEE_RENDER_PASS_DIFFUSE_COLOR` |
| Specular Light | `EEVEE_RENDER_PASS_SPECULAR_LIGHT` |
| Specular Color | `EEVEE_RENDER_PASS_SPECULAR_COLOR` |
| Volume Light | `EEVEE_RENDER_PASS_VOLUME_LIGHT` |
| Emission | `EEVEE_RENDER_PASS_EMIT` |
| Environment | `EEVEE_RENDER_PASS_ENVIRONMENT` |
| Shadow | `EEVEE_RENDER_PASS_SHADOW` |
| AO | `EEVEE_RENDER_PASS_AO` |
| Transparent | `EEVEE_RENDER_PASS_TRANSPARENT` |
| Denoising Depth/Normal/Roughness/Albedo | `EEVEE_RENDER_PASS_DENOISING_*` |
| AOV | 现有 AOV 路径 |

`Film::pass_storage_type()`、`Film::pass_id_get()`、`Film::pass_to_render_pass_names()` 已覆盖上述类型；只有新增专属 pass 时才需要改这三个 switch。

### 4.4 采样与积分

MVP：

- Camera ray + jitter。
- 直接光：光源采样 + MIS + 阴影 ray。
- 间接光：漫反射/镜面/玻璃 bounce。
- Russian roulette。
- 最大 bounce 可配置。
- 环境光重要性采样。

后续：

- 半分辨率/概率追踪。
- ReSTIR/SHARC 类缓存。
- 体积/毛发专用采样。
- 自适应采样/降噪引导。

### 4.5 降噪与超分

原则：

- 降噪后端必须可替换。
- 默认方案优先使用 Blender 可用、许可证兼容的降噪。
- NRD 作为可选外部模块时，不能直接链接专有源码到 GPL 二进制；需动态加载/独立进程/许可证审查。
- 时序缓冲需要 motion vector、normal/roughness、viewZ、hit distance、confidence。
- 超分后置，避免首阶段复杂化。

#### 4.5.1 NRD 原型契约（2026-11-17）

状态：IN_PROGRESS。NRD 4.17.1 + NRI + `RELAX_DIFFUSE` 已接入；能编译并在 F12 出图，但世界背景全黑和相机旋转鬼影未解决。

数据流：

```text
PT debug pass
  -> nrd_diffuse_tx (RGBA16F, rgb=radiance, a=world hit distance)
  -> nrd_normal_roughness_tx (R10G10B10A2, NRD packed normal/roughness)
  -> nrd_viewz_tx (R32F, +INF on miss)
  -> nrd_motion_tx (RGBA16F, xy=pixel motion, prevUV-currUV)
  -> NRD RELAX_DIFFUSE
  -> nrd_output_tx (RGBA16F)
  -> copy to combined_tx
```

执行位置与同步：

- 在 `PathTracingModule::render()` 中、PT pass submit 之后调用 NRD。
- 原型每帧 `GPU_finish()`，提交一次性 command buffer，等待 fence；成功后才 copy 回 `combined_tx`。
- NRD `NewFrame()` 必须在 `SetCommonSettings()` 之前调用。
- 资源以 `vk::Image` 包装给 NRD，usage 为 `SAMPLED|STORAGE`，因此 PT 输出纹理必须带 storage usage。

NRD 输入约定：

- `IN_DIFF_RADIANCE_HITDIST`：rgb 为路径追踪辐射度，a 为世界空间 hit distance；天空的 hit distance 为 0。
- `IN_NORMAL_ROUGHNESS`：必须使用与 NRD `_NRD_EncodeNormalRoughness101010` 一致的 R10G10B10A2 packed 编码；不能用 RGBA8 裸法线。
- `IN_VIEWZ`：view 空间正深度；miss/sky 必须为 `+INF`（`uintBitsToFloat(0x7F800000u)`），NRD composition 用 `abs(viewZ) >= INF` 判定天空。
- `IN_MV`：像素位移 `(prev_uv - curr_uv) * resolution`；`commonSettings.motionVectorScale = (1/width, 1/height, 0)`，与 NRD-Sample 的 `GetMotion` 约定一致。
- `CommonSettings`：当前和上一帧 view-to-clip/world-to-view 矩阵必须成对正确；历史累积用 `CONTINUE`，重置用 `CLEAR_AND_RESTART`。

历史重置：

- 视口：`Sampling::is_reset()`。
- F12：`sample_index() == 0`。
- `Sampling::is_reset()`/`reset()` 内部断言仅 viewport 可用，F12 调用会触发 `BLI_assert`，必须分支处理。
- 不再使用“相机变化就跳过 NRD”的方案；该方案会消除鬼影但失去时序累积，达不到参考项目效果。

构建/分发：

- `NRD.lib` 仅导出核心 API；`nrd::Integration` 是 header-only，必须编译 `NRDIntegration.hpp`。
- `NRI.dll` 静态依赖 `libxess.dll`；`NRD.dll`、`NRI.dll`、`libxess.dll` 必须与 `blender.exe` 同目录。
- 当前 CMake 为原型硬编码本机路径；最终必须改为可选 `WITH_NRD`，object-code 动态库分发并经过许可证审查。

已知缺陷：

- F12 世界背景纯黑；EEVEE-only 对照正常，问题在 PT/NRD 路径。
- 相机旋转鬼影；运动矢量、prev 矩阵和 reset 时序仍需验证。
- 诊断期间曾临时把 copy 目标改成 `nrd_diffuse_tx`，下一步必须先还原 `nrd_output_tx`。

### 4.6 视口与合成器

视口：

- 渐进累积，静止时增加样本。
- 相机移动/场景变化/材质变化时重置。
- 支持分辨率缩放和性能档位。
- 与 viewport compositor 兼容。

合成器：

- 写入 Film 的标准 pass。
- AOV 通过现有 AOV 机制。
- 确保最终渲染与视口一致。
- 对缺失 pass 提供明确回退。

## 5. 关键改造点

### 5.1 GPU 模块

已确认 `gpu_ray_query_custom_index_test.glsl` 和 `ray_tracing_instance_custom_index` 测试存在，但当前只验证默认值 0；Vulkan/Metal 都硬编码 `instanceCustomIndex/userID=0`。最小改造：

```cpp
struct InstanceInfo {
  uint32_t custom_index;
  uint8_t mask;
};

virtual InstanceID add_instance(const BottomLevelAS &blas,
                                const float4x4 &mat,
                                const InstanceInfo &info = {}) = 0;
virtual void update_instance(InstanceID id,
                             const float4x4 &mat,
                             const InstanceInfo &info = {}) = 0;
```

- Vulkan：把 `instanceCustomIndex` 写入 `VkAccelerationStructureInstanceKHR`。
- Metal：把 `custom_index` 写入 `MTLAccelerationStructureUserIDInstanceDescriptor.userID`。
- 保留旧签名重载或默认参数，避免一次性改所有调用点。
- 校验 `custom_index < (1 << 24)`，超限时报错并回退。
- 首阶段不扩展 BLAS API：Blender 每个 mesh BLAS 当前只有一个 geometry，`rayQueryGetIntersectionPrimitiveIndex(query, true)` 可直接作为该 mesh 的三角形索引；用全局 `PrimitiveRecord` buffer + `InstanceRecord.primitive_offset` 查材质/对象信息。
- 如果后续按材质拆分 BLAS geometry，再增加 `GeometryInfo { primitive_offset, primitive_count, material_id }` 和 `geometry_index` 查表。
- 透明/alpha：使用 inline ray query candidate 循环，读取 UV/属性后决定是否继续；不依赖 any-hit shader。
- 增加能力查询和限制上报：`maxInstanceCount`、`maxGeometryCount`、`maxPrimitiveCount`、custom index 位宽、是否支持 candidate 循环。
- Vulkan 优先，Metal 对齐，OpenGL 回退。

### 5.2 EEVEE 模块

- 增加路径追踪模式开关和设置。
- 在 `Instance` 生命周期中初始化/释放路径追踪模块。
- 在 `render_sample()` 中接入路径追踪 dispatch。
- 在 `Film` 中注册/写入路径追踪 pass。
- 在 viewport 路径中处理累积和重置。

### 5.3 材质模块

- 复用 `GPU_material`/`GPUCodegen` 生成的节点树函数；优先不改节点源码。`FrontFacing` 和 Bump 导数属于现有接口泄漏，先用 PT preamble/接口级修正，避免逐节点分叉。
- 新增 `GPU_MAT_PATHTRACING` 和 PT 版 `material_create_info_amend`，输出 PT closure list 到 closure buffer。
- 实现 PT engine interface：`KernelGlobals`、`ShadingData`、`Closure`/`closure_eval`、`closure_add`/`closure_mix`、坐标/属性/纹理/灯光/AO/Raycast/AOV。
- 定义 closure 容量、溢出、闭包权重和 MIS；复用 EEVEE 权重树的 `Weight`，不手写 Mix/Add `fac`，不复用 EEVEE 的 NOP add/mix 作为混合实现。
- 修复 BLAS/PT primitive 顺序与隐藏面过滤；`material_base`/`materials_num` 必须与排序后 primitive 的材质索引一致。
- `MaterialRecord` 改为 GPU 材质/资源句柄 + flags；按 material ID 分组绑定 UBO/纹理并 dispatch。
- Primary hit 优先复用 deferred G-buffer；secondary hit 走 PT material pass。
- 对 Shader to RGB、Raycast、Light Path、Volume/Hair 等语义差异定义近似/回退；节点矩阵只做验证。
- 增加 PT 材质测试场景：Principled、Image Texture、Geometry、Bump、Mix/Add、嵌套节点组。

## 6. 风险与验证

| 风险 | 影响 | 验证/缓解 |
|---|---|---|
| BLAS 无材质 ID | 命中后无法着色 | TC-003 扩展并测试 |
| TLAS 无 custom index | 无法映射实例/对象 | TC-003 扩展并测试 |
| Hair/Volume 非三角形 | 无法直接 ray query | 自定义相交/代理/后置 |
| 透明 any-hit | 透射/alpha 错误 | 验证后端能力，手动继续追踪 |
| NRD 许可证 | 不能直接集成 | 外部模块/自研/许可证审查 |
| OpenGL 无 RT | 后端不可用 | 能力检测 + 回退 |
| 性能不足 | 无法实时 | 半分辨率/降噪/缓存/调度 |
| 节点语义差异 | 材质错误 | 兼容矩阵 + 回退 |
| 材质求值不能直接调用 fragment shader | 二次命中无法着色 | 新增 `GPU_MAT_PATHTRACING` 材质变体 + PT engine interface + closure buffer |
| Secondary hit 属性/UV 缺失 | 纹理和节点错误 | hit-domain 属性读取或 fragment `attrib_load`；缺失时明确回退 |
| 逐节点适配导致维护灾难 | 新节点永远补不完 | 只实现 engine interface，禁止逐节点 PT C++ |
| 误读 `closure_add/mix` NOP | 误以为 Mix fac 无效，重复实现混合 | EEVEE 已用权重树展开 Mix/Add；PT 复用 `Weight`，实测 fac 0/0.5/1 红/紫/蓝 |
| BLAS/PT primitive 顺序错位 | 多材质/隐藏面错色、错误法线 | PT primitive 表与 BLAS 排序/过滤一致，或 PT 单独 BLAS；`pt_multimat.png` 复现 |
| 相机无 jitter | 样本增加仍无 AA | 像素 jitter + 累积；`pt_aa_64.png` 仅有黑白两值 |
| compute 无 `dFdx/dFdy` | Bump/纹理 mip 错误 | ray differential/tangent frame；首版 LOD0 近似并标注 |
| 多材质 UBO/纹理绑定 | 单 dispatch 资源冲突 | material-major 分组 dispatch 或 bindless 资源表 |

## 7. 待补充调研

- `eevee_pipeline.cc` 的精确 pass 顺序和 render/viewport 分支。
- `eevee_film.cc` 的 pass 注册、AOV、viewport compositor 生命周期。
- `eevee_material.cc` 的 GPU material 编译和 closure 打包。
- `GPU_ray_tracing.hh` 的 BLAS/TLAS 完整接口和后端限制。
- Vulkan `vk_ray_tracing.cc` 的 instance custom index/any-hit 支持。
- `draw_cache_impl_mesh.cc` 的 BLAS 更新策略。
- EEVEE 现有 ray trace 的降噪/时序实现，哪些可复用。
- M4 材质：PT engine interface 的完整函数清单、compute hit-domain 属性读取、纹理导数、多材质资源绑定、closure 容量/MIS、`target_engine_` 选择。

## 13. 2026-11-15 更新：Vulkan 激活与 GGX

- 路径追踪激活条件：`GPU_ray_query_support()` 为 true 且 EEVEE Raytracing 开关打开。ray query 只在 Vulkan/Metal 后端可用；OpenGL 会回退普通 EEVEE，并打印一次警告。
- `MaterialRecord` 现为 64 字节：`float4 base_color` + `float4 params`（x=roughness，y=metallic，zw 保留）+ 8 个 `uint`。C++ 从 `Material::r/g/b`、`roughness`、`metallic` 读取。
- 直接光照：Lambert 漫反射 + GGX specular（dielectric F0=0.04，metal F0=base_color）；金属间接光使用 GGX half-vector 采样，dielectric 间接光仍为余弦漫反射。
- `Mesh::corner_tris()` 是 face-corner 索引，不是 vertex 索引；同步 triangle 时必须经 `corner_verts()` 映射。
- 灯光同步由 `Instance::object_sync()` 对所有可见对象调用 `path_tracing.object_sync()`，路径追踪模块内部按 `OB_MESH`/`OB_LIGHT` 过滤。
- 启动必须使用 Vulkan：设置 `VK_ICD_FILENAMES` 指向 NVIDIA `nv-vk64.json`，并传 `--gpu-backend vulkan`；项目提供 `run_eevee_pt.bat`。

## 14. 2026-11-15 更新：P0 设置、世界光与世界光缺失修复

- `SceneEEVEE.pathtracing_max_bounces` 为新增 DNA 字段，默认 8；新增字段必须保持 `SceneEEVEE` 的 8 字节对齐，当前用 `char _pad3[4]` 补齐。
- 旧 `.blend` 读取时新字段为 0；若直接 `std::clamp(value, 1, 64)`，会得到 1 bounce。积分器只在相机 ray miss 时累加背景，因此表面不再获得世界环境光，阴影区全黑。修复分两层：
  - `blenloader/intern/versioning_503.cc` 在加载时把 `<=0` 补成 8；
  - `PathTracingModule::begin_sync()` 对 `<=0` 兜底为 8，再 clamp 到 1..64。
- `PathTracingData` 尾部现为 `max_bounces`、`clamp_direct`、`clamp_indirect`、`pad1`，总大小仍为 64B；`float4 background` 必须保持 16B 对齐。
- shader 使用动态 `max_bounces` 循环；背景和直接光按 `bounce==0`/`bounce>0` 分别应用 direct/indirect clamp；最终安全 clamp 为 1000。
- 阴影/法线：法线矩阵改为 `transpose(inverse(object_matrix))`；`ray_epsilon=max(0.005, hit_distance*1e-4)`；阴影 ray 使用 `tmin=ray_epsilon*0.5`、`shadow_distance=max(distance-ray_epsilon,0)`；玻璃后续 ray 起点使用 `wi*ray_epsilon*2`。C++ 对退化三角形使用固定 fallback normal。
- 编辑模式：`Instance::begin_sync()` 通过 `draw_ctx->object_edit` 检测编辑模式，`PathTracingModule` 在此期间禁用并回退普通 EEVEE。
- 验证：`m7-world-only-0001.png` 删除所有灯光，仅保留 World Background，物体和阴影正常受光；`m6-glass-0001.png` 阴影区有环境填充，不再死黑。
- 当前残留：玻璃顶部/边缘 TIR 困光；`m7` 球顶少量黑点，疑似二次 ray 自交或退化三角形，待后续处理。

## 15. 2026-11-16 主射线 flag 与黑边修复

- 根因：主射线误用 `gpu_RayFlagsTerminateOnFirstHit`。该 flag 只适合 shadow/occlusion ray；Vulkan 不保证返回最近 committed hit，可能命中薄壁内侧/背面，路径被困在几何体内部。
- 修复：主射线 `gpu_RayFlagsNone` + tmin `1e-4f`；shadow ray 保留 `TerminateOnFirstHit`。同时保留 `safe_normalize`、normal alignment、动态 `ray_epsilon`、shadow 近距自交过滤、`(1-fresnel)` diffuse、metallic 概率采样、throughput/NaN clamp。
- Bisect：`m13`/`m14`/`m15` 回退均不导致黑墙；`m16` 只回退主射线 flag 后复现；`m17` 改回后消失。证据见 `RESEARCH_LOG.md` R-027。
- 验证：`m12-frame-pt-user.png` 与 Cycles 一致；`m8-b8.png`、`m8-nosun.png` 黑月牙/轮廓黑边/接缝黑线消失。
- 结论：主射线 flag 是原 m8 黑边和 frame 黑墙的共同根因；shadow ray 的 `TerminateOnFirstHit` 不是问题。

## 16. 2026-11-16 材质节点架构更新

- 不再从 `eevee_pathtracing.cc` 读取 `bNode`/`bNodeSocket` 的 Principled 常量；该路径只作为过渡。
- 复用 `GPU_material`/`GPUCodegen` 的节点树生成，新增 `GPU_MAT_PATHTRACING` 和 PT 版 `material_create_info_amend`。
- 实现 `gpu_shader_material_interface.bsl.hh` 的 PT 版本；节点文件不改，禁止逐节点 C++ 适配。
- PT 自定义 `Closure` 句柄/list 和闭包权重采样；**复用 EEVEE 权重树**，不手写 `closure_add`/`closure_mix` 的 fac。实测 EEVEE Mix 正常、PT 当前全回退，证明问题在 PT 入口而非 EEVEE 语义。
- `MaterialRecord` 目标字段：`gpu_material_id`、资源表索引、flags、closure 能力；删除 `base_color`/`params`。
- 前置修复：BLAS 使用排序/隐藏面过滤后的 IBO，PT primitive 表必须一致；`materials_num` 与 `totcol`/`material_base` 对齐。实测多材质红蓝面交换。
- 独立风险：Checker Texture 接 Base Color 当前变纯绿；64 样本无 AA；`rayQueryProceed` 只调用一次，未按 Vulkan 规范循环。
- 主要未决：compute 属性 domain、纹理/bump 导数、多材质资源绑定、closure 容量/MIS、`target_engine_` 选择。详见 `RESEARCH_LOG.md` R-028/R-030。