# Survival Kit（Kenney）使用说明

本目录素材来自 Kenney「Survival Kit」包，包含营地/道具/家具等低多边形 3D 模型（含篝火、木箱、桶、工具等），非常适合狼人杀“围火舞台”的中心道具搭建。

## 许可（License）

- 本包为 **CC0（Creative Commons Zero）**：可商用、可修改、可再分发、无需署名。
- 以本目录内 `License.txt` 为准。

## 目录结构说明

- `Models/`
  - `GLB format/`：Web 推荐（`*.glb`），直接给 three.js / react-three-fiber 用。
  - `FBX format/`：`*.fbx`。
  - `OBJ format/`：`*.obj` + `*.mtl`（常用于离线工具/管线）。
  - `Textures/`：贴图（通常为 `*.png`），主要给 OBJ/FBX 管线使用。
- `Previews/`：预览图（帮助快速挑素材）。
- `Overview.html`：Kenney 自带概览页（本地打开即可浏览内容）。

## 在本 React/Vite 项目中如何引用

本包位于 Vite 的 `public/` 目录下，运行时通过**绝对路径**访问：

- GLB 示例：`/assets/kenney/survival-kit/Models/GLB%20format/campfire-pit.glb`

> 注意：目录名包含空格（如 `GLB format`），URL 中要写成 `%20`（`GLB%20format`）。

## 3D 用法（推荐 GLB）

### react-three-fiber 示例

```tsx
import { useGLTF } from "@react-three/drei";

export function PitFire() {
  const { scene } = useGLTF("/assets/kenney/survival-kit/Models/GLB%20format/campfire-pit.glb");
  return <primitive object={scene} />;
}
```

### 常见建议

- **道具复用**：椅子/木箱等常见物件可以多次放置；数量多时优先 instancing。
- **统一风格**：尽量在同一个 Kenney 系列里选模型（与 `nature-kit` 搭配风格一致）。
- **光照氛围**：夜晚围火可以用点光源模拟火光（`pointLight` + 暖色）。

## OBJ/FBX 何时使用

- 需要在 Blender 等工具里二次编辑、合并网格、重新烘焙贴图时用 `FBX/OBJ` 更方便。
- Web 运行时仍建议最终导出为 `GLB/GLTF` 再放到 `public/` 里加载。

## 快速挑选狼人杀常用道具

可以直接在 `Models/GLB format/` 按文件名搜索：

- 篝火/营地：`campfire-*`
- 木箱/桶：`box*`、`barrel*`、`bucket*`
- 刀具/工具：`knife*`、`axe*`（如果存在）

也可以先看 `Previews/` 或打开 `Overview.html` 进行可视化浏览。

