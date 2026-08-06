import unittest

from tests.helpers import read_text


class StaticAppTraceTest(unittest.TestCase):
    def test_final_result_renders_loop_and_recovery_audits(self):
        app_js = read_text("paperseek/static/app.js")
        index_html = read_text("paperseek/static/index.html")
        styles = read_text("paperseek/static/styles.css")

        self.assertIn("function renderSearchLoopAudit", app_js)
        self.assertIn('renderSearchLoopAudit(item.auditData, "search")', app_js)
        self.assertIn('renderSearchLoopAudit(item.auditData, "ranking")', app_js)
        self.assertIn("Ranking recovery", app_js)
        self.assertIn("Citation recovery", app_js)
        self.assertIn("Candidate queue", app_js)
        self.assertIn("ledger_summary", app_js)
        self.assertIn("LEDGER CANDIDATES", app_js)
        self.assertIn("SELECTED FOR LLM", app_js)
        self.assertIn("FINAL OUTPUT", app_js)
        self.assertIn("FUSED CANDIDATES", app_js)
        self.assertIn('label: "FUSED CANDIDATES"', app_js)
        self.assertNotIn('label: "CANDIDATES SCORED"', app_js)
        self.assertIn("Citation-aware candidate fusion", app_js)
        self.assertIn("Initial query target:", app_js)
        self.assertIn('"Candidate ledger": "候选账本"', app_js)
        self.assertIn("FRONTIER ITEMS", app_js)
        self.assertIn("FRONTIER REQUESTS", app_js)
        self.assertIn('"Citation frontier": "引用前沿"', app_js)
        self.assertIn(".loop-audit .metric-row", styles)

        self.assertIn("function createDisclosureState", app_js)
        self.assertIn("stageManual", app_js)
        self.assertIn("data-stage-toggle", app_js)
        self.assertIn("data-section-toggle", app_js)
        self.assertIn("data.search_plan", app_js)
        self.assertIn("function renderQueryPortfolio", app_js)
        self.assertIn("query_portfolio", app_js)
        self.assertIn("Truncated before LLM", app_js)
        self.assertIn('class="right-pane log-collapsed"', index_html)
        self.assertIn('id="logToggle"', index_html)
        self.assertIn('aria-expanded="false"', index_html)
        self.assertIn(".workflow-card-toggle:focus-visible", styles)
        self.assertIn(".log-toggle:focus-visible", styles)
        self.assertIn('name="searchBudget" value="fast" checked', index_html)
        self.assertIn('name="searchBudget" value="max"', index_html)
        self.assertNotIn('id="exportCsvButton"', index_html)
        self.assertIn("search_budget: selectedSearchBudget()", app_js)
        self.assertIn("function updateSearchBudgetHelp()", app_js)
        self.assertIn('data-action="export-results-csv"', app_js)
        self.assertIn("function exportResultsCsv()", app_js)
        self.assertIn('fast: "Fewest requests for faster searches."', app_js)
        self.assertIn('"Fewest requests for faster searches.": "请求次数最少，检索更快。"', app_js)
        self.assertIn(".budget-segmented input:focus-visible + span", styles)


if __name__ == "__main__":
    unittest.main()
