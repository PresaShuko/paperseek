from __future__ import annotations

import unittest

from paperseek_core.query_loop import QueryLoopPipeline

try:
    from paperseek_core.query_portfolio import QueryPortfolioExecutor
except ImportError:
    QueryPortfolioExecutor = None


class QueryPortfolioExecutionBoundaryContract(unittest.TestCase):
    def test_portfolio_execution_has_one_module_owner(self) -> None:
        self.assertIsNotNone(QueryPortfolioExecutor)
        self.assertFalse(hasattr(QueryLoopPipeline, "_run_portfolio"))
        self.assertFalse(hasattr(QueryLoopPipeline, "_portfolio_execution"))


if __name__ == "__main__":
    unittest.main()
