<script setup lang="ts">
import { computed } from 'vue'
import { useData, withBase } from 'vitepress'
import ProductTour from './ProductTour.vue'

const { lang } = useData()
const zh = computed(() => lang.value.startsWith('zh'))
const t = (en: string, cn: string) => zh.value ? cn : en
const link = (path: string) => withBase((zh.value ? '/zh/' : '/') + path)
const sources = ['OpenAlex', 'arXiv', 'Crossref', 'Semantic Scholar', 'PubMed', 'Google Scholar', 'PaperHub', 'Web of Science']
</script>

<template>
  <main class="ps-home" id="main-content">
    <section class="ps-hero ps-container" aria-labelledby="hero-heading">
      <div class="ps-hero-copy">
        <a class="ps-release" :href="link('changelog')"><span class="ps-release-dot" />{{ t('Introducing PaperSeek 1.0.0-beta', '认识 PaperSeek 1.0.0-beta') }}<span aria-hidden="true">↗</span></a>
        <h1 id="hero-heading">{{ t('Follow the question.', '从问题出发，') }}<br><span>{{ t('Find the evidence.', '找到研究的线索。') }}</span></h1>
        <p class="ps-hero-description">{{ t('A thoughtful way through the literature. Turn your research question into a reading list, explore how papers connect, and bring the evidence together.', '把研究问题变成值得阅读的文献清单，沿着引用发现新的线索，再将分散的证据整理成综述。让文献探索更有条理。') }}</p>
        <div class="ps-actions">
          <a class="ps-button ps-button-primary" href="https://paperseek.app/">{{ t('Start researching', '开始研究') }}<span aria-hidden="true">↗</span></a>
          <a class="ps-button" :href="link('guide/quick-start')">{{ t('Run it yourself', '在本地运行') }}<span aria-hidden="true">→</span></a>
        </div>
        <p class="ps-hero-note">{{ t('Open source · Your choice of models · Built for research', '开放源码 · 自由选择模型 · 为文献研究而设计') }}</p>
      </div>
    </section>


    <section class="ps-section ps-container" aria-labelledby="tour-heading">
      <h2 id="tour-heading" class="ps-sr-only">{{ t("Explore the research workspace", "探索文献研究工作区") }}</h2>
      <ProductTour :zh="zh" />
      <p class="ps-tour-caption">{{ t('An illustrative look at the workflow. Your results depend on the question, source, and model you choose.', '流程示意。实际结果取决于研究问题、数据源和所选模型。') }}</p>
      <div class="ps-principles">
        <article><span class="ps-step-number">01 / {{ t('SEARCH', '检索') }}</span><h3>{{ t('Go beyond a single query.', '不止于一次关键词检索。') }}</h3><p>{{ t('PaperSeek plans queries, refines the search, and combines complementary retrieval paths before ranking the candidates.', '从问题理解到检索式迭代，综合不同召回路径，再对候选文献排序。你可以查看每一步进展。') }}</p><a :href="link('guide/search')">{{ t('How search works', '了解检索流程') }} →</a></article>
        <article><span class="ps-step-number">02 / {{ t('ANALYZE', '计量') }}</span><h3>{{ t('Explore the whole retrieved corpus.', '观察完整候选集。') }}</h3><p>{{ t('Inspect distributions, keyword co-occurrence, and shared references using the full retrieved corpus. Keep model scoring focused on its subset.', '用实际获取的候选集分析分布、关键词共现和共同参考文献，模型评分仍只针对原子集。') }}</p><a :href="link('guide/bibliometrics')">{{ t('Explore bibliometrics', '了解文献计量') }} →</a></article>
        <article><span class="ps-step-number">03 / {{ t('SYNTHESIZE', '综合') }}</span><h3>{{ t('Write with the evidence.', '带着证据，开始写作。') }}</h3><p>{{ t('Select papers, shape an outline, and draft an abstract-based review with linked citations. Review writing is experimental.', '选择文献、调整大纲，再从摘要证据生成带引用的综述。综述功能目前为实验性。') }}</p><a :href="link('guide/reviews')">{{ t('Meet the review workflow', '了解综述流程') }} →</a></article>
      </div>
    </section>

    <section class="ps-sources" :aria-label="t('Supported scholarly source integrations', '学术数据源集成')">
      <div class="ps-container">
        <p class="ps-eyebrow">{{ t('A wider view of the literature', '让文献视野更开阔') }}</p>
        <div class="ps-source-list"><span v-for="source in sources" :key="source">{{ source }}</span></div>
        <a :href="link('guide/sources')">{{ t('Explore the sources and availability', '了解数据源与可用性') }} <span aria-hidden="true">→</span></a>
      </div>
    </section>

    <section class="ps-choice-section">
      <div class="ps-container">
        <div class="ps-section-heading"><div><p class="ps-eyebrow">{{ t('MAKE IT YOURS', '选择适合你的方式') }}</p><h2>{{ t('Your research.', '你的研究，') }}<br><span>{{ t('Your way of working.', '用你习惯的方式。') }}</span></h2></div><p>{{ t('Use PaperSeek in your browser, or keep the workspace on your own machine. The same search foundation, with a different home for your data.', '直接打开在线版，或在自己的设备上运行。相同的检索基础，不同的数据存储与模型配置方式。') }}</p></div>
        <div class="ps-choice-grid">
          <article class="ps-choice"><div class="ps-choice-icon" aria-hidden="true">↗</div><p class="ps-eyebrow">PAPERSEEK ONLINE</p><h3>{{ t('Open a tab. Follow an idea.', '打开浏览器，开始探索。') }}</h3><p>{{ t('Choose PaperSeek Service or Bring Your Own Key. Sign in to keep history and work on reviews.', '选择 PaperSeek 服务或 Bring Your Own Key。登录后保存检索历史，并继续整理综述。') }}</p><a class="ps-button ps-button-primary" href="https://paperseek.app/">{{ t('Open PaperSeek', '打开 PaperSeek') }} ↗</a><a class="ps-text-link" :href="link('online/')">{{ t('Read the online guide', '阅读在线版指南') }} →</a></article>
          <article class="ps-choice"><div class="ps-choice-icon" aria-hidden="true">⌘</div><p class="ps-eyebrow">COMMUNITY EDITION</p><h3>{{ t('A workspace of your own.', '在自己的设备上研究。') }}</h3><p>{{ t('Run the open-source app locally or with Docker. Bring your model credentials and keep history in local storage.', '本地安装或使用 Docker 部署。配置自己的模型，把历史与文件保存在自己管理的存储中。') }}</p><a class="ps-button" :href="link('guide/quick-start')">{{ t('Install Community', '安装社区版') }} →</a><a class="ps-text-link" :href="link('integrations/skill')">{{ t('Use the Agent Skill', '使用 Agent Skill') }} →</a></article>
        </div>
      </div>
    </section>

    <section class="ps-section ps-container ps-resources" aria-labelledby="resources-heading">
      <div><p class="ps-eyebrow">{{ t('A GOOD PLACE TO START', '从这里继续') }}</p><h2 id="resources-heading">{{ t('A little guidance.', '一点指引，') }}<br><span>{{ t('A lot to discover.', '更多发现。') }}</span></h2><p>{{ t('Learn the workflow at your own pace, then make it part of your research practice.', '按自己的节奏了解工作流程，再把 PaperSeek 融入日常研究。') }}</p><a class="ps-text-link" href="https://github.com/MingfengHong/paperseek">{{ t('Built in the open. Join us on GitHub.', '在开放中成长。欢迎在 GitHub 参与贡献。') }} ↗</a></div>
      <div class="ps-resource-links">
        <a :href="link('guide/quick-start')"><span><small>01</small><strong>{{ t('Your first search', '开始第一次检索') }}</strong><em>{{ t('Installation, configuration, and your first question.', '安装、配置，提出你的第一个问题。') }}</em></span><b aria-hidden="true">↗</b></a>
        <a :href="link('guide/models')"><span><small>02</small><strong>{{ t('Find your model setup', '选择模型与排序方式') }}</strong><em>{{ t('Local fusion, embedding, reranking, and decision models.', '理解本地融合、Embedding、Rerank 与决策模型。') }}</em></span><b aria-hidden="true">↗</b></a>
        <a :href="link('reference/troubleshooting')"><span><small>03</small><strong>{{ t('Get unstuck', '遇到问题时') }}</strong><em>{{ t('Practical answers to common search and setup questions.', '查找检索、配置与写作中的常见问题。') }}</em></span><b aria-hidden="true">↗</b></a>
      </div>
    </section>
  </main>
</template>
