import unittest
from types import SimpleNamespace

from paperseek_core.agent import PaperSeekAgent
from paperseek_core.planning import ConceptGroup, QueryView, fallback_search_plan, parse_search_plan
from paperseek_core.query_compiler import ArxivQueryCompiler, OpenAlexQueryCompiler
from paperseek_core.sources.providers import PaperRecord, ProviderSearchResult, SearchMetadata


class SequencedLlm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.last_response_info = {}

    def chat(self, messages, temperature=0.3):
        self.calls.append({"messages": messages, "temperature": temperature})
        return self.responses.pop(0)


class PortfolioArxivProvider:
    def __init__(self):
        self.queries = []
        self.last_response_info = {}

    def search(self, query, limit=50, page=1, lane="relevance"):
        self.queries.append(query)
        if "cross-modal retrieval" in query:
            hits = [PaperRecord(uid="arxiv:1909.11740", title="UNITER: UNiversal Image-TExt Representation Learning", provider="arxiv")]
            return ProviderSearchResult(metadata=SearchMetadata(total=120, page=page, limit=limit), hits=hits)
        if "content-based image retrieval" in query:
            hits = [PaperRecord(uid="arxiv:core-image-retrieval", title="Deep Content-Based Image Retrieval", provider="arxiv")]
            return ProviderSearchResult(metadata=SearchMetadata(total=40, page=page, limit=limit), hits=hits)
        hits = [PaperRecord(uid="arxiv:initial", title="Image Retrieval Survey", provider="arxiv")]
        return ProviderSearchResult(metadata=SearchMetadata(total=30, page=page, limit=limit), hits=hits)


class SearchPlanTest(unittest.TestCase):
    def test_parse_typed_search_plan_with_query_views(self):
        plan = parse_search_plan(
            """
            {
              "intent": "Find representative work across image retrieval and cross-modal retrieval.",
              "question_type": "broad_landscape",
              "core_concepts": ["image retrieval"],
              "must_have_facets": ["image retrieval"],
              "optional_facets": ["benchmark evaluation"],
              "required_relation": "",
              "likely_synonyms": ["content-based image retrieval"],
              "adjacent_concepts": ["image-text retrieval", "cross-modal retrieval"],
              "boundaries": ["image generation"],
              "adjustment_strategy": "Use complementary terminology instead of title-only narrowing.",
              "query_views": [
                {
                  "view_id": "core_lexical",
                  "purpose": "Direct field terminology",
                  "concept_groups": [
                    {"label": "field", "terms": ["image retrieval", "content-based image retrieval"], "required": true, "field_hint": "all"}
                  ]
                },
                {
                  "id": "cross_modal",
                  "purpose": "Cross-modal naming family",
                  "groups": [
                    {"label": "cross modal", "terms": ["image-text retrieval", "cross-modal retrieval", "vision-language retrieval"]}
                  ]
                },
                {
                  "id": "representation_methods",
                  "view_type": "mechanism_method",
                  "purpose": "Representation learning methods",
                  "groups": [
                    {"label": "method", "terms": ["visual representation learning", "image embedding"]}
                  ]
                }
              ]
            }
            """,
            "What works are related to the field of image retrieval?",
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.question_type, "broad_landscape")
        self.assertEqual([view.view_id for view in plan.query_views], ["core_lexical", "cross_modal", "representation_methods"])
        self.assertEqual(plan.query_views[0].view_type, "direct_terminology")
        self.assertEqual(plan.query_views[1].view_type, "successor_paradigm")
        self.assertEqual(plan.must_have_facets, ["image retrieval"])
        self.assertEqual(plan.optional_facets, ["benchmark evaluation"])
        self.assertEqual(plan.required_relation, "")
        self.assertEqual(plan.coverage_gaps(), [])
        self.assertIn("must_have_facets: image retrieval", plan.audit_summary())
        self.assertIn("query_views: core_lexical", plan.audit_summary())

    def test_broad_plan_reports_missing_successor_paradigm(self):
        plan = parse_search_plan(
            """
            {
              "intent": "Survey image retrieval.",
              "question_type": "broad_landscape",
              "query_views": [
                {
                  "view_id": "direct_field",
                  "view_type": "direct_terminology",
                  "purpose": "Direct terminology",
                  "concept_groups": [{"label": "field", "terms": ["image retrieval"]}]
                }
              ]
            }
            """,
            "What works are related to image retrieval?",
        )

        self.assertTrue(any("successor_paradigm" in gap for gap in plan.coverage_gaps()))

    def test_plan_with_fewer_than_three_views_reports_portfolio_gap(self):
        plan = parse_search_plan(
            """
            {
              "intent": "Find region-based semantic segmentation methods.",
              "question_type": "method_application",
              "query_views": [
                {
                  "view_id": "direct",
                  "view_type": "direct_terminology",
                  "purpose": "Direct terminology",
                  "concept_groups": [{"label": "task", "terms": ["region-based semantic segmentation"]}]
                }
              ]
            }
            """,
            "Find region-based semantic segmentation methods.",
        )

        self.assertIn("at least three valid complementary query views", plan.coverage_gaps()[0])

    def test_legacy_intent_json_remains_valid_without_enabling_portfolio(self):
        plan = parse_search_plan(
            '{"intent":"Find graph neural network papers","core_concepts":["graph neural networks"],"likely_synonyms":["GNN"]}',
            "Find graph neural network papers",
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.core_concepts, ["graph neural networks"])
        self.assertEqual(plan.must_have_facets, ["graph neural networks"])
        self.assertEqual(plan.optional_facets, [])
        self.assertEqual(plan.query_views, [])

    def test_optional_facets_do_not_duplicate_required_facets(self):
        plan = parse_search_plan(
            '{"intent":"Find causal effects of AI governance",'
            '"core_concepts":["AI governance","causal effects"],'
            '"must_have_facets":["AI governance"],'
            '"optional_facets":["AI governance","public agencies"],'
            '"required_relation":"causal effect of governance on accountability"}',
            "Find causal effects of AI governance on accountability.",
        )

        self.assertEqual(plan.must_have_facets, ["AI governance"])
        self.assertEqual(plan.optional_facets, ["public agencies"])
        self.assertEqual(plan.required_relation, "causal effect of governance on accountability")

    def test_fallback_plan_preserves_original_question(self):
        plan = fallback_search_plan("AI governance in public agencies", "invalid JSON")

        self.assertEqual(plan.intent, "AI governance in public agencies")
        self.assertEqual(plan.query_views, [])
        self.assertIn("invalid JSON", plan.adjustment_strategy)

    def test_model_invented_exclusion_is_removed_from_parsed_plan(self):
        plan = parse_search_plan(
            """
            {
              "intent": "Find automatic white balance methods.",
              "query_views": [
                {
                  "view_id": "white_balance",
                  "concept_groups": [{"label": "method", "terms": ["white balance"]}],
                  "exclusions": ["automatic white balance"]
                }
              ]
            }
            """,
            "Find methods for estimating white balance preset weights.",
        )

        self.assertEqual(plan.query_views[0].exclusions, [])

    def test_explicit_user_exclusion_is_preserved_in_parsed_plan(self):
        plan = parse_search_plan(
            """
            {
              "intent": "Find image retrieval methods without image generation.",
              "query_views": [
                {
                  "view_id": "retrieval",
                  "concept_groups": [{"label": "task", "terms": ["image retrieval"]}],
                  "exclusions": ["image generation", "image classification"]
                }
              ]
            }
            """,
            "Find image retrieval papers without image generation.",
        )

        self.assertEqual(plan.query_views[0].exclusions, ["image generation"])


class ArxivQueryCompilerTest(unittest.TestCase):
    def test_compiles_required_groups_and_exclusions(self):
        view = QueryView(
            view_id="cross_modal",
            purpose="Find cross-modal image retrieval papers",
            concept_groups=[
                ConceptGroup(
                    label="retrieval naming",
                    terms=["image-text retrieval", "cross-modal retrieval", "vision-language retrieval"],
                    required=True,
                    field_hint="all",
                ),
                ConceptGroup(
                    label="representations",
                    terms=["multimodal representation", "vision language pretraining"],
                    required=False,
                    field_hint="abstract",
                ),
            ],
            exclusions=["image generation"],
        )

        compiled = ArxivQueryCompiler().compile(view)

        self.assertEqual(compiled.source, "arxiv")
        self.assertEqual(compiled.view_id, "cross_modal")
        self.assertIn('all:"image-text retrieval"', compiled.query)
        self.assertIn('OR all:"cross-modal retrieval"', compiled.query)
        self.assertNotIn("multimodal representation", compiled.query)
        self.assertTrue(compiled.query.endswith('ANDNOT all:"image generation"'))

    def test_broad_landscape_plan_does_not_keep_title_only_view(self):
        plan = parse_search_plan(
            """
            {
              "intent": "Survey image retrieval research.",
              "question_type": "broad_landscape",
              "core_concepts": ["image retrieval"],
              "query_views": [
                {
                  "view_id": "title_only",
                  "purpose": "Generated title view",
                  "concept_groups": [{"label": "field", "terms": ["image retrieval"], "field_hint": "title"}]
                }
              ]
            }
            """,
            "What works are related to the field of image retrieval?",
        )

        self.assertEqual(plan.query_views[0].concept_groups[0].field_hint, "all")

    def test_compiler_balances_quotes_and_parentheses(self):
        view = QueryView(
            view_id="core",
            concept_groups=[ConceptGroup(label="core", terms=['target "Q" network', "DQN"])],
        )

        compiled = ArxivQueryCompiler().compile(view)

        self.assertEqual(compiled.query.count('"') % 2, 0)
        self.assertEqual(compiled.query.count("("), compiled.query.count(")"))


class OpenAlexQueryCompilerTest(unittest.TestCase):
    def test_compiles_boolean_groups_without_api_parameters_or_wildcards(self):
        view = QueryView(
            view_id="cross_modal",
            concept_groups=[
                ConceptGroup(label="retrieval", terms=["image-text retrieval", "cross-modal retrieval"]),
                ConceptGroup(label="representation", terms=["multimodal representation learning"], required=True),
            ],
            exclusions=["image generation"],
        )

        compiled = OpenAlexQueryCompiler().compile(view)

        self.assertEqual(
            compiled.query,
            '("image-text retrieval" OR "cross-modal retrieval") AND "multimodal representation learning" NOT "image generation"',
        )
        self.assertNotIn("search=", compiled.query)
        self.assertNotIn("*", compiled.query)


class QueryPortfolioIntegrationTest(unittest.TestCase):
    def test_two_invalid_intent_plans_fall_back_without_a_third_llm_call(self):
        llm = SequencedLlm(
            [
                "The response was truncated before the JSON object.",
                '{"intent":"Find local editing methods", "query_views": [',
                '{"unused":"a third response must never be requested"}',
            ]
        )
        config = SimpleNamespace(data_source="semanticscholar", discipline_fields=(), query_portfolio_enabled=True)
        agent = PaperSeekAgent(config, llm)

        audit = agent._analyze_intent("Find local editing methods using semantic masks as intermediate representations")

        self.assertIn("Structured planning fallback", audit)
        self.assertEqual(agent.search_plan.query_views, [])
        self.assertEqual([item["attempt"] for item in agent.search_plan_diagnostics], [1, 2])
        self.assertEqual(len(llm.calls), 2)

    def test_three_invalid_intent_plans_fall_back_without_looping(self):
        llm = SequencedLlm(["invalid", "still invalid", "not json either"])
        config = SimpleNamespace(data_source="arxiv", discipline_fields=(), query_portfolio_enabled=True)
        agent = PaperSeekAgent(config, llm)

        audit = agent._analyze_intent("Find robust literature search agents")

        self.assertIn("Structured planning fallback", audit)
        self.assertEqual(agent.search_plan.query_views, [])
        self.assertEqual(len(agent.search_plan_diagnostics), 2)
        self.assertEqual(len(llm.calls), 2)

    def test_invalid_intent_json_gets_one_structured_repair(self):
        llm = SequencedLlm(
            [
                "I should first analyze the literature-search intent.",
                """
                {
                  "intent": "Find region-based semantic segmentation methods.",
                  "question_type": "method_application",
                  "core_concepts": ["semantic segmentation", "region-based active learning"],
                  "query_views": [
                    {"view_id":"direct","view_type":"direct_terminology","purpose":"Direct terms","concept_groups":[{"label":"task","terms":["region-based semantic segmentation"]}]},
                    {"view_id":"active_learning","view_type":"mechanism_method","purpose":"Active-learning methods","concept_groups":[{"label":"method","terms":["region-based active learning", "superpixel active learning"]}]},
                    {"view_id":"patch_methods","view_type":"application_benchmark","purpose":"Patch and superpixel methods","concept_groups":[{"label":"method","terms":["image patch segmentation", "superpixel segmentation"]}]}
                  ]
                }
                """,
                r'{"query":"all:\"semantic segmentation\"","rationale":"Direct query."}',
            ]
        )
        config = SimpleNamespace(
            data_source="arxiv",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=1,
            fetch_abstracts=False,
            retrieval_pool_max=3000,
            query_portfolio_enabled=True,
        )
        agent = PaperSeekAgent(config, llm)
        provider = PortfolioArxivProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **kwargs: []

        result = agent.search("Find region-based semantic segmentation methods")

        self.assertEqual(result["search_plan"]["question_type"], "method_application")
        self.assertEqual(len(result["search_plan"]["query_views"]), 3)
        self.assertEqual(len(llm.calls), 3)
        repair_messages = llm.calls[1]["messages"]
        self.assertFalse(any(message.get("role") == "assistant" for message in repair_messages))
        self.assertIn("Start over without repeating it", repair_messages[-1]["content"])

    def test_arxiv_search_executes_complementary_views_and_tracks_candidate_origin(self):
        llm = SequencedLlm(
            [
                """
                {
                  "intent": "Find representative research across image retrieval naming families.",
                  "question_type": "broad_landscape",
                  "core_concepts": ["image retrieval"],
                  "likely_synonyms": ["content-based image retrieval"],
                  "adjacent_concepts": ["cross-modal retrieval", "image-text retrieval"],
                  "boundaries": ["image generation"],
                  "adjustment_strategy": "Use complementary terminology without title-only restriction.",
                  "query_views": [
                    {
                      "view_id": "core_lexical",
                      "purpose": "Direct image-retrieval terminology",
                      "concept_groups": [{"label": "field", "terms": ["image retrieval", "content-based image retrieval"], "required": true, "field_hint": "all"}]
                    },
                    {
                      "view_id": "cross_modal",
                      "purpose": "Cross-modal and image-text naming",
                      "concept_groups": [{"label": "field", "terms": ["cross-modal retrieval", "image-text retrieval"], "required": true, "field_hint": "all"}]
                    },
                    {
                      "view_id": "representation_methods",
                      "view_type": "mechanism_method",
                      "purpose": "Representation-learning methods",
                      "concept_groups": [{"label": "method", "terms": ["visual representation learning", "image embedding"], "required": true, "field_hint": "all"}]
                    }
                  ]
                }
                """,
                r'{"query":"all:\"image retrieval\"","rationale":"Start from direct field terminology."}',
            ]
        )
        config = SimpleNamespace(
            data_source="arxiv",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=1,
            fetch_abstracts=False,
            retrieval_pool_max=3000,
            query_portfolio_enabled=True,
            query_portfolio_max=3,
            query_portfolio_limit=100,
        )
        agent = PaperSeekAgent(config, llm)
        provider = PortfolioArxivProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **kwargs: []

        result = agent.search("What works are related to the field of image retrieval?")

        self.assertEqual(result["search_plan"]["question_type"], "broad_landscape")
        self.assertEqual(
            [item["view_id"] for item in result["query_portfolio"]],
            ["core_lexical", "cross_modal", "representation_methods"],
        )
        self.assertTrue(all(item["status"] == "completed" for item in result["query_portfolio"]))
        direct_selection = next(
            item for item in result["query_view_selection"] if item["view_id"] == "core_lexical"
        )
        self.assertIn("high_primary_overlap_observed", direct_selection["reason_codes"])
        self.assertIn("uid:arxiv:1909.11740", result["search_state"]["candidate_queue"]["keys"])
        cross_modal = next(item for item in result["query_portfolio"] if item["view_id"] == "cross_modal")
        self.assertEqual(cross_modal["added_unique"], 1)
        self.assertTrue(any(row.get("action") == "portfolio" for row in result["history"]))

    def test_legacy_intent_output_gets_one_structured_portfolio_repair(self):
        llm = SequencedLlm(
            [
                '{"intent":"Find image retrieval papers","core_concepts":["image retrieval"],"likely_synonyms":["CBIR"]}',
                """
                {
                  "intent": "Find image retrieval papers",
                  "question_type": "specific_relation",
                  "core_concepts": ["image retrieval"],
                  "query_views": [
                    {"view_id":"direct","view_type":"direct_terminology","purpose":"Direct terms","concept_groups":[{"label":"task","terms":["image retrieval"]}]},
                    {"view_id":"cross_modal","view_type":"successor_paradigm","purpose":"Cross-modal terms","concept_groups":[{"label":"task","terms":["cross-modal retrieval"]}]},
                    {"view_id":"methods","view_type":"mechanism_method","purpose":"Method terms","concept_groups":[{"label":"task","terms":["content-based image retrieval"]}]}
                  ]
                }
                """,
                r'{"query":"all:\"image retrieval\"","rationale":"Direct query."}',
            ]
        )
        config = SimpleNamespace(
            data_source="arxiv",
            discipline_fields=(),
            search_field="",
            expand_citations=False,
            target_min=5,
            target_max=50,
            max_iterations=1,
            fetch_abstracts=False,
            retrieval_pool_max=3000,
            query_portfolio_enabled=True,
        )
        agent = PaperSeekAgent(config, llm)
        provider = PortfolioArxivProvider()
        agent.provider = provider
        agent._retrieve_candidates = lambda question, query, hits: hits
        agent._rank_results = lambda question, documents, **kwargs: []

        result = agent.search("Find image retrieval papers")

        self.assertEqual(len(result["search_plan"]["query_views"]), 3)
        self.assertEqual(len(result["query_portfolio"]), 3)
        self.assertEqual(
            [item["status"] for item in result["query_portfolio"]],
            ["completed", "completed", "skipped_duplicate"],
        )
        duplicate = next(item for item in result["query_portfolio"] if item["view_id"] == "direct")
        self.assertIn("exact_primary_duplicate", duplicate["selector_reasons"])
        self.assertEqual(len(provider.queries), 3)


if __name__ == "__main__":
    unittest.main()
