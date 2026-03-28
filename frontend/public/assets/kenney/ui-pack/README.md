# UI Pack（Kenney）使用说明

本目录素材来自 Kenney「UI Pack」包，包含按钮、面板、箭头、进度条、窗口框等大量 UI 组件素材（PNG + SVG），可直接用来搭建狼人杀的 React 交互界面。

## 许可（License）

- 本包为 **CC0（Creative Commons Zero）**：可商用、可修改、可再分发、无需署名。
- 以本目录内 `License.txt` 为准。

## 目录结构说明

- `PNG/`：PNG 位图 UI（按配色分类）
  - `Grey/`、`Blue/`、`Green/`、`Red/`、`Yellow/`、`Extra/`
  - 每个配色下通常有 `Default/` 与 `Double/`（不同分辨率/尺寸）
- `Vector/`：SVG 矢量 UI（适合做响应式/可缩放 UI）
- `Sounds/`：少量 UI 音效（`*.ogg`）
  - 例如：`click-a.ogg`、`switch-a.ogg`、`tap-a.ogg`
- `Font/`：字体（`*.ttf`）

## 在本 React/Vite 项目中如何引用

本包位于 `public/` 目录下，运行时通过绝对路径访问：

- PNG 示例：`/assets/kenney/ui-pack/PNG/Grey/Default/button_rectangle_flat.png`
- 音效示例：`/assets/kenney/ui-pack/Sounds/click-a.ogg`

> 注意：字体文件名包含空格（如 `Kenney Future.ttf`），URL 里要把空格写成 `%20`。

## React 里做 UI 的推荐用法

### 1) 面板/按钮当背景图

```jsx
<button className="kenneyBtn">开始游戏</button>
```

```css
.kenneyBtn{
  background: transparent url("/assets/kenney/ui-pack/PNG/Grey/Default/button_rectangle_flat.png") no-repeat center / 100% 100%;
  border: 0;
  padding: 12px 18px;
  color: #fff;
}
```

### 2) 用 SVG 做可缩放图形（更适合不同分辨率）

优先从 `Vector/` 里找对应按钮/面板，再根据项目主题做统一颜色/描边。

### 3) 9-slice / 拉伸的注意事项

很多 UI 底板适合“中间拉伸、边角不变”。简单做法：

- 先挑“边框更宽”的素材（更不容易拉坏）
- 用 `background-size: 100% 100%` 直接拉伸（成本最低）

如果后期追求更精致，可以考虑：

- CSS `border-image`（对某些素材合适）
- 在设计工具里做 9-slice 后导出多块图片

## 字体使用（可选）

如果你想使用 `Font/` 里的字体，可以在全局 CSS 加 `@font-face`：

```css
@font-face{
  font-family: "KenneyFuture";
  src: url("/assets/kenney/ui-pack/Font/Kenney%20Future.ttf") format("truetype");
  font-display: swap;
}
```

## UI 音效使用（可选）

同目录下 `Sounds/` 提供少量点击/切换音效：

```js
const sfx = new Audio("/assets/kenney/ui-pack/Sounds/click-a.ogg");
sfx.volume = 0.6;
sfx.play();
```

> iOS/Safari 通常不支持 OGG：如果需要兼容，建议转一份 MP3/AAC 并做多格式回退。

