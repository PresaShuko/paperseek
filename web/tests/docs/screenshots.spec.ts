// Regenerates the documentation screenshots from the real UI against the in-memory API:
//   node tests/browser/run.mjs --config playwright.docs.config.ts
// The papers below are illustrative, not real publications.
import { test } from "@playwright/test";
import { analysis, createState, ids, paper, reviewDetail, withDocument } from "../browser/mock-backend";
import { open } from "../browser/workspace-helpers";

const out = "../docs/public/images";
const pages = [
  ["search", "/search"],
  ["results", `/runs/${ids.done}/results`],
  ["bibliometrics", `/bibliometrics/${ids.analysis}`],
  ["review", `/reviews/${ids.review}?tab=document`],
] as const;
const questions = {
  en: ["LLM screening for systematic reviews", "Long-term stability of perovskite solar cells", "Gut microbiome and depression"],
  zh: ["大语言模型辅助系统综述的文献筛选", "钙钛矿太阳能电池的长期稳定性", "肠道菌群与抑郁症的关联机制"],
};
const papers = [
  ["Large language models for title and abstract screening: a comparative evaluation", "Recall, workload saved and agreement with two human reviewers across twelve systematic reviews."],
  ["Prompt design and calibration for automated citation screening", "How instructions, examples and a held-out calibration set change sensitivity and specificity."],
  ["Workload reduction in systematic reviews with machine-assisted screening", "A prospective study of reviewer time and missed studies when a model ranks abstracts first."],
  ["Reproducibility of model-based eligibility decisions", "Repeated runs, model updates and their effect on which studies are included."],
  ["Active learning versus zero-shot screening for evidence synthesis", "Comparing two common automation strategies on medical and social science reviews."],
  ["Reporting standards for AI-assisted literature reviews", "A checklist for documenting models, prompts and human oversight in published reviews."],
].map(([title, abstract], index) => paper(index + 1, { title, abstract, authors: [["Lin", "Okafor", "Müller", "Silva", "Tanaka", "Haddad"][index] + " A", "Reyes M"],
  reasoning: "Directly evaluates screening accuracy and reviewer workload.", doi: "", url: "" }));

test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });

for (const language of ["en", "zh"] as const) {
  test(`workspace screenshots (${language})`, async ({ page }) => {
    const state = createState();
    state.results[ids.done] = papers;
    [ids.done, ids.small, ids.failed].forEach((id, index) => { state.runs[id].question = questions[language][index]; });
    state.analyses = [analysis(state, ids.done)];
    const review = withDocument(reviewDetail(state, { source_run_id: ids.done, paper_uids: ["uid-1", "uid-2", "uid-3"],
      topic: questions[language][0], language, length: "standard", section_count: 2 }));
    const cite = (number: number) => ({ citation: { number, label: `[${number}]`, paper_id: `p${number}`, evidence_ids: [`e-p${number}`] } });
    review.document.sections[0].paragraphs = [{ citation_warnings: [], spans: [
      { text: "Across the included evaluations, model-assisted screening reached recall comparable to a single human reviewer while reducing the abstracts that needed manual reading " }, cite(1), { text: ". Savings were largest when the model ranked abstracts before human review " }, cite(3), { text: "." }] }];
    review.document.sections[1].paragraphs = [{ citation_warnings: [], spans: [
      { text: "Performance varied with prompt design and topic; studies that calibrated on a held-out set reported more stable decisions " }, cite(2), { text: "." }] }];
    review.document.references = papers.slice(0, 3).map((item, index) => ({ number: index + 1, text: `${item.authors[0]}, ${item.authors[1]}. ${item.title}. ${item.venue}. ${item.publish_year}.`, url: "", doi: "" }));
    state.reviews = [review];
    for (const [name, path] of pages) {
      await open(page, path, state, language);
      await page.waitForLoadState("networkidle");
      if (name === "search") await page.locator("textarea").first().fill(questions[language][0]);
      await page.screenshot({ path: `${out}/workspace-${name}-${language}.png` });
    }
  });
}
