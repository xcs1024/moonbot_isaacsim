# GLB 衣服柔性布料仿真流程

这个流程用于把一个 `.glb` 衣服资产变成 Isaac Sim 可用的柔性布料 USD，并降低仿真网格面数。

核心思路不要把高模视觉衣服直接当布料仿真网格。正确结构是：

```text
/World/clothes
  deformable root

/World/clothes/model
  视觉网格，负责显示衣服、贴图、材质

/World/clothes/simulationMesh
  隐藏仿真网格，负责 PhysX cloth/deformable surface 计算
```

这样视觉质量和仿真计算量可以分开控制。

## 文件

脚本：

```bash
scripts/glb_cloth_pipeline.py
```

输出：

```text
clothes.usd
clothes_base_color.png
```

## 环境

在 DGX/Isaac Sim 的 conda 环境中运行，例如：

```bash
conda activate env_isaacsim
```

需要 Python 包：

```bash
pip install trimesh fast-simplification pillow numpy
```

如果是 ARM/DGX Spark，运行 Isaac 相关脚本时可能需要：

```bash
export LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1:$LD_PRELOAD
```

## 推荐用法

默认推荐：保留原始视觉网格和 UV 贴图，只降低隐藏仿真网格。

```bash
python scripts/glb_cloth_pipeline.py \
  --input /home/nvidia/isaacsim_realworld/assets/cloth/base_basic_pbr.glb \
  --output /home/nvidia/isaacsim_realworld/assets/cloth/clothes_cloth.usd \
  --sim-mode grid \
  --grid-x 33 \
  --grid-y 45 \
  --solver-iterations 3
```

这个配置大约生成：

```text
simulationMesh: 1485 vertices / 2816 triangles
```

视觉模型仍然保留原始 UV 和 baseColor 贴图。

## 更轻的配置

如果还是卡，可以继续降低代理网格：

```bash
python scripts/glb_cloth_pipeline.py \
  --input /home/nvidia/isaacsim_realworld/assets/cloth/base_basic_pbr.glb \
  --output /home/nvidia/isaacsim_realworld/assets/cloth/clothes_cloth_light.usd \
  --sim-mode grid \
  --grid-x 25 \
  --grid-y 35 \
  --solver-iterations 2 \
  --linear-damping 10 \
  --settling-damping 16 \
  --max-linear-velocity 0.6
```

大约：

```text
simulationMesh: 875 vertices / 1632 triangles
```

## 保留贴图 vs 降低视觉网格

默认 `--visual-target-faces 0`：

- 不简化视觉衣服
- 保留原始 UV
- 导出 baseColor 贴图
- 视觉最可靠
- 但渲染和视觉变形仍然有高模开销

如果设置 `--visual-target-faces > 0`：

```bash
python scripts/glb_cloth_pipeline.py \
  --input clothes.glb \
  --output clothes_lod.usd \
  --visual-target-faces 35000 \
  --sim-mode grid \
  --grid-x 33 \
  --grid-y 45
```

脚本会简化视觉网格，并尽量保留原始纹理颜色。注意：很多 GLB 在三角网格简化后 UV 不再稳定，所以脚本会退化为“贴图烘焙到顶点颜色”。这会降低视觉精度，但性能更好。

## 关键参数

`--sim-mode grid`

使用规则代理网格，性能最稳定，推荐用于实时。

`--sim-mode decimate`

尝试从原始衣服拓扑简化出仿真网格。形状更贴近衣服，但某些模型会简化不到目标面数。

`--grid-x / --grid-y`

控制隐藏仿真网格大小。面数约等于：

```text
(grid_x - 1) * (grid_y - 1) * 2
```

`--solver-iterations`

布料求解迭代次数。越大越稳定，越小越快。实时建议 `2-5`。

`--self-collision`

默认关闭。衣服高模通常自交较多，打开会明显变慢，也更容易炸。

`--linear-damping / --settling-damping`

阻尼。调高可以减少抖动和不稳定，也能降低视觉上过激的运动。

## 在主场景中引用

如果要把输出 USD 放进现有场景：

```python
from pxr import Usd

stage = Usd.Stage.Open("/home/nvidia/isaacsim_realworld/assets/sim_world.usd")
clothes = stage.GetPrimAtPath("/World/clothes")
clothes.GetPayloads().ClearPayloads()
clothes.GetPayloads().AddPayload("./cloth/clothes_cloth.usd", "/World/clothes")
stage.GetRootLayer().Save()
```

如果你已经在主场景里有 `/World/clothes`，也可以直接把输出 USD 作为单独 asset 参考进来。

## 验证

打开 Isaac Sim 后检查：

```text
/World/clothes
  有 OmniPhysicsDeformableBodyAPI

/World/clothes/model
  有 MaterialBindingAPI
  材质绑定到 /World/clothes/Looks/model

/World/clothes/simulationMesh
  有 OmniPhysicsSurfaceDeformableSimAPI
  purpose = guide
```

播放时不应该出现：

```text
PxValidateTriangleMesh for PxDeformableSurface failed
```

如果出现这个错误，说明仿真网格不符合 PhysX cloth 要求，优先改用：

```bash
--sim-mode grid
```

## 推荐调参顺序

1. 先保持 `--visual-target-faces 0`，确认贴图和视觉正确。
2. 调低 `--grid-x / --grid-y`，先优化仿真开销。
3. 调低 `--solver-iterations` 到 `2-3`。
4. 仍然卡，再考虑设置 `--visual-target-faces` 降低视觉网格。
5. 不建议直接拿 100 万面视觉衣服做 PhysX cloth，容易 cook 失败或非常卡。
