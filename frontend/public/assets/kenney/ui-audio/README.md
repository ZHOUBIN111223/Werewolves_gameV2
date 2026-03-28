# UI Audio（Kenney）使用说明

本目录素材来自 Kenney「UI Audio / UI SFX Set」包，包含大量界面交互音效（点击、hover、切换、开关等），适合狼人杀前端的按钮反馈、阶段切换、倒计时提示等。

## 许可（License）

- 本包为 **CC0（Creative Commons Zero）**：可商用、可修改、可再分发、无需署名。
- 以本目录内 `License.txt` 为准。

## 目录结构说明

- `Audio/`：音效文件（`*.ogg`）
  - 示例：`click1.ogg`、`rollover1.ogg`、`switch1.ogg`、`mouseclick1.ogg`

## 在本 React/Vite 项目中如何引用

本包位于 `public/` 目录下，运行时通过绝对路径访问：

- 示例：`/assets/kenney/ui-audio/Audio/click1.ogg`

## React 中播放音效的两种常见方式

### 方式 A：HTMLAudio（简单）

```js
export function playClick(){
  const a = new Audio("/assets/kenney/ui-audio/Audio/click1.ogg");
  a.volume = 0.6;
  void a.play();
}
```

适合：按钮点击、偶发音效、开发期快速接入。

### 方式 B：复用 Audio 对象（减少延迟）

```js
const click = new Audio("/assets/kenney/ui-audio/Audio/click1.ogg");
click.preload = "auto";

export function playClick(){
  click.currentTime = 0;
  void click.play();
}
```

适合：高频交互（hover、列表快速点击）。

## 浏览器兼容性提醒（重要）

- **iOS/Safari 通常不支持 OGG**。如果你需要兼容移动端 Safari：
  - 建议将常用音效转换一份 `mp3` 或 `m4a(aac)`，并在播放时做格式回退；
  - 或统一用构建脚本生成多格式资源。
- 多数浏览器要求在**用户手势**（点击/触摸）之后才能播放声音；初始化阶段建议先“解锁音频”。

## 使用场景建议（狼人杀）

- 按钮点击：`click*.ogg`
- hover/聚焦：`rollover*.ogg`
- 开关/阶段切换：`switch*.ogg`

