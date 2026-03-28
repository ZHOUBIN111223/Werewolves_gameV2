# RPG Audio（Kenney）使用说明

本目录素材来自 Kenney「RPG Audio」包，包含偏“动作/技能/道具”的短音效（拔刀、翻书、开门、掉落等），适合狼人杀中“女巫用药 / 预言家验人 / 猎人开枪”等特殊动作的反馈音效。

## 许可（License）

- 本包为 **CC0（Creative Commons Zero）**：可商用、可修改、可再分发、无需署名。
- 以本目录内 `License.txt` 为准。

## 目录结构说明

- `Audio/`：音效文件（`*.ogg`）
  - 示例：`drawKnife1.ogg`、`bookOpen.ogg`、`doorOpen_1.ogg`、`chop.ogg`

## 在本 React/Vite 项目中如何引用

本包位于 `public/` 目录下，运行时通过绝对路径访问：

- 示例：`/assets/kenney/rpg-audio/Audio/drawKnife1.ogg`

## React 中播放音效（推荐复用对象）

```js
const knife = new Audio("/assets/kenney/rpg-audio/Audio/drawKnife1.ogg");
knife.preload = "auto";

export function playKnife(){
  knife.currentTime = 0;
  void knife.play();
}
```

## 浏览器兼容性提醒（重要）

- **iOS/Safari 通常不支持 OGG**：需要转码 `mp3/m4a` 并做回退，或只面向支持 OGG 的平台。
- 建议在游戏开始按钮点击时预加载/解锁音频，避免关键时刻静音或延迟。

## 狼人杀动作音效映射建议

- 狼人击杀：`drawKnife*.ogg` / `chop.ogg`
- 预言家“翻书/查看”：`bookOpen.ogg` / `bookFlip*.ogg`
- 房间门开合/阶段切换：`doorOpen_*.ogg` / `doorClose_*.ogg`

