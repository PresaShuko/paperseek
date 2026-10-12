# 界面规范

工作区参考 [shadcn/ui](https://ui.shadcn.com/) 的 new-york 与 neutral 风格，使用原生 CSS 和 Vue 3 组件实现，不依赖 CSS 框架或 React 运行时。

## 文件归属

以下路径均相对于 `web/src`。

| 层次 | 内容 | 文件 |
| --- | --- | --- |
| 设计变量 | 颜色、图表配色、圆角、阴影、字体，如 `--background`、`--muted-foreground`、`--radius-md` | `styles/ui.css` 的 `:root` |
| 基础控件 | 按钮、输入、选择、卡片、徽标、标签、表格、列表、侧栏、统计与进度条 | `styles/ui.css` |
| 外壳与浮层 | 滚动、侧栏收起、移动端抽屉、弹窗、菜单、列表框、提示与骨架屏 | `styles/app.css` |
| 字体 | 自托管 Geist 与 Geist Mono，中文回退到系统无衬线字体 | `styles/fonts.css` |
| 共享组件 | `UiSelect`、`UiMenu`、`UiSheet`、`AppDialog`、`Disclosure`、`StatusBadge`、`Toaster`、`Icon` | `components/` |

## 规则

- 复用设计变量，不在业务模块中硬编码颜色、圆角或阴影。
- 新增类名前先复用基础样式（`.btn`、`.input`、`.select`、`.card`、`.field`、`.page`、`.hdr`）和共享组件。页面专属样式靠近页面代码放置，不在样式表末尾堆叠覆盖规则。
- 正文与控件为 14px／20px，元数据为 12px。小于 900px 的屏幕将输入字号改为 16px，避免移动浏览器自动缩放。
- 侧栏宽 288px，可完全收起；小于 900px 时使用抽屉。主内容区滚动，侧栏历史、弹窗、图谱及有界列表可各自滚动。
- 不仅依靠颜色传递含义：错误、状态和选择还需文本或图标。网络图按节点角色分类着色，分布图使用蓝色图表配色。
- 长篇综述保留适合阅读的字号和行高，不沿用密集卡片样式。
- 工作区仅提供浅色主题。

在线版使用相同 Web 源码，因此共享视觉变更应在社区版完成。

## 检查变更

在 `web/` 中运行 `npm run typecheck`、`npm run build` 和 `npm run test:browser`，并在真实浏览器中检查桌面与手机宽度。
