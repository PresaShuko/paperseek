import { defineConfig, type DefaultTheme } from 'vitepress'

const base = process.env.DOCS_BASE || '/'
const groups = [
  ['Start here', '开始使用', [['Introduction', '认识 PaperSeek', 'guide/'], ['Quick start', '快速开始', 'guide/quick-start']]],
  ['Using PaperSeek', '使用 PaperSeek', [['Workspace & history', '工作区与历史', 'guide/workspace'], ['Search', '文献检索', 'guide/search'], ['Bibliometrics', '文献计量', 'guide/bibliometrics'], ['Data sources', '数据源', 'guide/sources'], ['Models & ranking', '模型与排序', 'guide/models'], ['Results & history', '结果与历史', 'guide/results'], ['Citation maps', '引用图谱', 'guide/citation-map'], ['Reviews · Experimental', '综述 · 实验性', 'guide/reviews']]],
  ['PaperSeek online', '在线版', [['Service, keys & credits', '服务、密钥与积分', 'online/'], ['Your account', '账户与登录', 'online/account']]],
  ['Run it yourself', '自托管与集成', [['Local & Docker', '本地与 Docker', 'self-hosting/'], ['Upgrade to 1.0.0-beta1', '升级至 1.0.0-beta1', 'self-hosting/upgrade'], ['Command line', '命令行', 'integrations/cli'], ['Agent Skill', 'Agent Skill', 'integrations/skill'], ['MCP', 'MCP', 'integrations/mcp'], ['HTTP API', 'HTTP API', 'integrations/api']]],
  ['Reference', '参考', [['Configuration', '配置参考', 'reference/configuration'], ['Troubleshooting', '常见问题', 'reference/troubleshooting'], ['Contributing', '参与贡献', 'contributing']]],
  ['Changelog', '更新日志', [['All releases', '版本记录', 'changelog']]]
] as const

function navigation(zh = false): DefaultTheme.Config {
  const prefix = zh ? '/zh/' : '/'
  return {
    nav: [
      { text: zh ? '文档' : 'Documentation', link: `${prefix}guide/`, activeMatch: `${prefix}(guide|self-hosting|integrations|reference|contributing)` },
      { text: zh ? '在线版' : 'Online guide', link: `${prefix}online/`, activeMatch: `${prefix}online/` },
      { text: 'v1.0.0-beta1', link: `${prefix}changelog` },
      { text: zh ? '打开 PaperSeek' : 'Open PaperSeek', link: 'https://paperseek.app/' }
    ],
    sidebar: groups.map(([en, cn, pages]) => ({
      text: zh ? cn : en,
      collapsed: false,
      items: pages.map(([english, chinese, path]) => ({ text: zh ? chinese : english, link: prefix + path }))
    })),
    editLink: { pattern: 'https://github.com/paperseek/paperseek/edit/main/docs/:path', text: zh ? '在 GitHub 上编辑此页' : 'Edit this page on GitHub' },
    outline: { label: zh ? '本页目录' : 'On this page', level: [2, 3] },
    docFooter: { prev: zh ? '上一页' : 'Previous page', next: zh ? '下一页' : 'Next page' },
    lastUpdated: { text: zh ? '最后更新' : 'Last updated' },
    returnToTopLabel: zh ? '回到顶部' : 'Back to top',
    sidebarMenuLabel: zh ? '目录' : 'Menu',
    darkModeSwitchLabel: zh ? '外观' : 'Appearance',
    lightModeSwitchTitle: zh ? '切换为浅色' : 'Switch to light theme',
    darkModeSwitchTitle: zh ? '切换为深色' : 'Switch to dark theme',
    langMenuLabel: zh ? '语言' : 'Language',
    skipToContentLabel: zh ? '跳到正文' : 'Skip to content',
    footer: { message: zh ? '开放源码，自由探索。Apache-2.0 许可。' : 'Open source. Open to exploration. Apache-2.0 licensed.', copyright: '© 2026 PaperSeek contributors' }
  }
}

export default defineConfig({
  title: 'PaperSeek',
  description: 'From a research question to a reading list. Open-source literature search, citation maps, and abstract-based reviews.',
  base,
  cleanUrls: true,
  lastUpdated: true,
  srcExclude: ['README.md', 'public/**/*.md'],
  outDir: process.env.DOCS_OUT_DIR,
  cacheDir: process.env.DOCS_CACHE_DIR,
  sitemap: { hostname: 'https://docs.paperseek.app' },
  markdown: { theme: { light: 'github-light', dark: 'github-dark' } },
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}paperseek-mark.svg` }],
    ['meta', { name: 'theme-color', content: '#fafafa' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:site_name', content: 'PaperSeek' }]
  ],
  transformHead({ pageData }) {
    const path = pageData.relativePath.replace(/index\.md$/, '').replace(/\.md$/, '')
    return [['link', { rel: 'canonical', href: `https://docs.paperseek.app/${path}` }]]
  },
  locales: {
    root: { label: 'English', lang: 'en', themeConfig: navigation() },
    zh: { label: '简体中文', lang: 'zh-CN', description: '从研究问题到阅读清单。开源文献检索、引用图谱与基于摘要的文献综述。', themeConfig: navigation(true) }
  },
  themeConfig: {
    logo: { light: '/paperseek-lockup.svg', dark: '/paperseek-lockup-dark.svg', alt: 'PaperSeek' },
    siteTitle: false,
    socialLinks: [{ icon: 'github', link: 'https://github.com/paperseek/paperseek' }],
    search: { provider: 'local', options: { miniSearch: { options: {
      tokenize(text) {
        return Array.from(new Intl.Segmenter('zh', { granularity: 'word' }).segment(text))
          .filter(part => part.isWordLike).map(part => part.segment)
      }
    } }, locales: { zh: { translations: {
      button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
      modal: { displayDetails: '显示详情', resetButtonTitle: '清除', backButtonTitle: '返回', noResultsText: '未找到相关内容', footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' } }
    } } } } }
  }
})
