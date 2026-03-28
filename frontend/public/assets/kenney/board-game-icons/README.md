# Board Game Icons（Kenney）使用说明

本目录素材来自 Kenney「Board Game Icons」包，提供大量桌游/卡牌风格的图标，适合狼人杀 UI（昼夜、投票、击杀、女巫药水、倒计时等）。

## 许可（License）

- 本包为 **CC0（Creative Commons Zero）**：可商用、可修改、可再分发、无需署名。
- 以本目录内 `License.txt` 为准。

## 目录结构说明

- `Vector/Icons/`：**SVG 矢量图标**（推荐 UI 使用）
  - 示例：`campfire.svg`、`skull.svg`、`sword.svg`、`flask_full.svg`、`timer_0.svg`
- `PNG/Default (64px)/`：64px PNG（适合低成本直接用）
- `PNG/Double (128px)/`：128px PNG
- `Tilesheet/`：整张图集（spritesheet）
  - `iconsDefault.png`、`iconsDouble.png`、`Tilesheet.txt`（对应切图坐标说明）

## 在本 React/Vite 项目中如何引用

本包位于 `public/` 目录下，运行时通过绝对路径访问：

- SVG：`/assets/kenney/board-game-icons/Vector/Icons/skull.svg`
- PNG：`/assets/kenney/board-game-icons/PNG/Default%20(64px)/skull.png`

> 注意：`Default (64px)` 这类目录名有空格和括号，URL 中空格要写 `%20`。

### 直接用 `<img>`（最省事）

```jsx
<img alt="death" src="/assets/kenney/board-game-icons/Vector/Icons/skull.svg" />
```

### 想改 SVG 颜色（推荐两种做法）

1) **把需要的 SVG 拷贝到 `src/assets/` 再用 SVGR**  
这样可以当 React 组件用，颜色/大小更好控（例如通过 `fill="currentColor"`）。

2) **在构建阶段统一处理 SVG**  
例如写脚本把常用图标复制到一个无空格目录，并做清理/改色（适合规模化）。

## 狼人杀 UI 图标选型建议

你可以在 `Vector/Icons/` 用文件名快速筛选：

- 死亡/出局：`skull.svg`
- 击杀/攻击：`sword.svg`、`dice_sword.svg`
- 女巫药水：`flask_full.svg`、`flask_half.svg`、`flask_empty.svg`
- 倒计时：`timer_0.svg` / `timer_100.svg` / `timer_CW_*` / `timer_CCW_*`
- 围火/场景提示：`campfire.svg`

在 PowerShell 里搜索示例：

```powershell
Get-ChildItem .\\Vector\\Icons -Filter *flask*.svg
```

