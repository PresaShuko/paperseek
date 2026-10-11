# 数据源

选择适合研究问题的文献索引，不同提供方的覆盖、元数据、访问要求和筛选能力并不相同。

## 数据源目录

| 数据源 | 社区版 / 自带密钥访问要求 | 侧重 |
| --- | --- | --- |
| [OpenAlex](https://openalex.org/) | 建议配置 Key | 广泛学术发现与引用扩展 |
| [arXiv](https://arxiv.org/) | 无需 Key | 科学预印本 |
| [Crossref](https://www.crossref.org/) | 无需 Key | DOI 与出版元数据 |
| [Semantic Scholar](https://www.semanticscholar.org/) | Key 可选 | 论文与学术图谱元数据 |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | NCBI Key 可选 | 生物医学与生命科学 |
| Google Scholar / [Serper](https://serper.dev/) | 必须配置 Serper Key | 通过受支持 API 检索 Scholar |
| PaperHub 计算机顶会 | 无需 Key | PaperHub 提供的顶会集合 |
| [Web of Science Starter](https://developer.clarivate.com/apis/wos-starter) | 需要 Clarivate Key | 受支持的 WoS 集合 |



PaperSeek 服务的数据源访问由 PaperSeek 管理。自带密钥模式下在设置中填写数据源密钥；除 arXiv、Crossref、PaperHub 等无需密钥的数据源外，其余数据源（包括 OpenAlex、PubMed、Semantic Scholar）都必须提供密钥。模型 Key 与数据源 Key 并不通用。

## 申请凭据

- [OpenAlex API 设置](https://openalex.org/settings/api)。
- [Semantic Scholar Key 申请](https://www.semanticscholar.org/product/api#api-key-form)。
- [NCBI API 指南](https://www.ncbi.nlm.nih.gov/books/NBK25497/)。
- [Serper 账户](https://serper.dev/)。
- [WoS Starter 应用](https://developer.clarivate.com/apis/wos-starter)。

上游订阅和速率限制，与 PaperSeek 账户及积分分别管理。

## 领域与分类

OpenAlex 使用受支持的学科选项，语义通道按支持的方式执行筛选；arXiv 使用 Category；WoS 学科与 WoS 数据库选择独立。其他来源使用文本领域提示。

限制领域可能排除跨学科文献，除非研究设计要求，否则可先不限制。

## 元数据缺失

记录可能没有摘要、年份、引用数或开放 PDF。信息缺失不是质量判断。

1.0.0-beta1 不再提供独立的跨源摘要补全或引用数补全开关。写综述时请选择摘要信息充分的文献。

## 多 Key 轮询

OpenAlex 与 Serper 支持用空白、逗号或分号分隔的 Key 池。请求会轮换起始 Key，鉴权失败与临时错误分别处理。

轮询不会改变提供方的条款，也不保证仍有余额，详见[配置参考](../reference/configuration.md)。
