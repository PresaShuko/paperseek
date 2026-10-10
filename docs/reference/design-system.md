# PaperSeek 界面规范与维护入口

2026-10-08 起，以维护者提供的 `PaperSeek Design System` 为视觉来源，采用其 shadcn/ui new-york-v4 中性风格。现有 Vue 3 组件继续负责真实交互，不引入参考套件的 React bundle、CDN、模拟数据或 Library/Ask 等示例功能。

## 页面与组件

| 层级 | 规则 | 维护位置（web/src 下） |
| --- | --- | --- |
| 设计变量 | Geist 本地字体、黑白中性色、4px 间距；30px 桌面标题、24px 窄屏标题、16px 分组、14px 正文/控件、12px 元信息 | styles/tokens.css |
| 基础控件 | 普通按钮/输入框 36px，小按钮 32px；窄屏主要点击目标至少 44px；输入框圆角 8px，卡片 14px，菜单 8px | styles/components.css、dialog.css、features/navigation.css |
| 页面骨架 | 顶栏 48px；侧栏 256px / 折叠 64px；桌面页面边距 24px，窄屏 16px；内容左对齐，表单最大 960px、页面最大 1400px | styles/pages.css、features/workspace-shell.css |
| 检索 | 问题输入为首要操作区，文字提交按钮；数据源与凭据桌面分列，窄屏叠放；接近字数上限才显示计数 | features/search/SearchComposer.vue、SearchWorkspace.vue；styles/features/search*.css |
| 设置 | 独立路由，模型/数据源/通用；卡片内分组，凭据靠近模型，协议和地址折叠展开；高级设置展示当前初排序摘要 | features/workspace/WorkspacePreferences.vue、SourceSettings.vue；features/search/SearchModelSettings.vue |
| 内容 | 结果采用独立阅读卡片；记录采用有边界的列表；计量统计卡与蓝色分布图；综述选文献、编辑和阅读继续按任务布局 | styles/features/results.css、workspace.css、bibliometrics.css、review.css |

普通页面只由 `.app-main` 滚动；侧栏历史独立滚动。图谱交互区、弹窗和受限列表可拥有自己的必要滚动，不给整张表单再加固定高度。页面头在窄屏变为纵向时，不得保留会转成高度的固定 `flex-basis`。

## 有意保留的产品差异

- 保留已有 PaperSeek 标志；参考包的“未提供 logo”描述不适用于本项目已有资产。
- 字体随发行物本地提供，不依赖 Google Fonts 或 CDN。中文使用系统无衬线字体。
- 折叠侧栏保留 64px，容纳设置/账户与足够点击区域；手机使用抽屉。
- 专业网络图继续用分类颜色辨别节点语义，统计条形图采用设计系统蓝色。不会为了装饰改变图例含义。
- 暂不新增深色主题开关。参考包的深色变量不代表项目已完成深色模式验收。
- 综述长文仍使用适合阅读的字号/行距。参考中的卡片密度不直接套用于正文。

## 维护约束与验证

只在共享 Community 源码维护上述视觉规则。Hosted 通过锁定 wheel 中的 `web_source.zip` 消费同一实现，在线认证和服务设置仍在 Hosted；禁止手改 `.community` 生成目录。

新增页面复用 `.page-view`、`.page-header`、`.field`、`.button` 和现有菜单/对话框。间距与尺寸变更先改所属样式文件，避免每次增加末尾覆盖层。颜色不能替代错误、状态或选中项的文字/图标提示。

验证入口：`npm run typecheck`、`npm run build`、`npm run test:browser`。浏览器回归覆盖窄屏滚动、菜单焦点、草稿与凭据、检索提交/取消、结果选择、图谱和综述。视觉检查必须看真实渲染；功能测试通过不等于维护者接受视觉效果。
