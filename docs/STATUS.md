# 当前状态与未决问题

更新时间：2026-11-24

## 已完成

- Vulkan 硬件 ray query 路径追踪主链路可运行。
- NRD 4.17.1 + NRI + REBLUR diffuse/specular + 最终 TAA 已接入。
- Raytracing 面板新增 `Path Tracing` 方法、Max Bounces、Clamp、通道开关和 Debug View。
- 视口进入 Edit Mode 时自动禁用 PT 并回退普通 EEVEE，不再崩溃。
- 背景/材质基础路径可用；当前仍主要读取 Principled 常量。

## 未解决：视口红弧 / 时间累积鬼影

### 已记录现象

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

### 当前判断

- 单帧 raw path tracing 不是唯一问题：关闭 TAA 后视口干净。
- 红弧不是 NRD 独有：关闭 NRD、只保留 TAA 时 debug 3 仍会出现淡弧。
- NRD history 会显著放大红弧；`NO_NRD_HISTORY=1` 能消除强红弧。
- F12 与视口的差异说明问题与视口的时间累积/重投影路径高度相关，而不是单纯的 shader 采样偏差。
- motion debug 显示静态相机下平台仍有非零 motion，这是下一步的重点怀疑对象。

### 待验证假设

1. 视口 motion vector 在静态相机下错误，导致 TAA/NRD history 被错误重投影，沿平台边缘形成红弧。
2. 视口相机切换/平滑过渡期间产生了错误 history，且 history 权重较高，红弧长时间不消失。
3. NRD 的 diffuse history 对 raw 信号中的边缘/红色间接光产生空间扩散，TAA 再把结果累积成可见弧线。
4. viewport 8 帧 jitter 周期与 NRD/TAA history 权重组合产生采样相关性。

### 下一步

1. 用 `EEVEE_PT_DEBUG_MOTION=1` 对比 4/8/80 redraws 的 motion，确认静态相机下非零 motion 是否持续存在。
2. 用 `EEVEE_PT_DEBUG_FLAGS=8` 强制 motion 为零，观察红弧是否消失；如果消失，优先修 motion/reprojection。
3. 对比 F12 与视口在相同分辨率、相同相机矩阵下的 motion 和 TAA history。
4. 检查相机视图切换/分辨率变化时是否及时重置 history，必要时在 view matrix 变化时使 history 失效。
5. 修复后重新验证：`NO_TAA`、debug 3、正常 NRD+TAA 三条路径。

## 其他未完成

- 材质节点树/纹理尚未接入，M4 仍为调研阶段。
- 多材质、隐藏面场景的 BLAS/primitive 索引映射需要修复。
- 金属 NRD 反射仍偏糊。
- BLAS 对原地 deform 的更新仍是 stale。
- 性能尚未达到实时目标。
- NRD/NRI/libxess 仍是 Windows 原型集成，需要整理为可选的 `WITH_NRD` 模块并做许可证审查。
