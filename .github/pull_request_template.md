## Summary

- 

## Scope

Select all that apply:

- [ ] CLI
- [ ] Web UI
- [ ] Agent Skill
- [ ] Core search logic
- [ ] Source adapter
- [ ] Deployment
- [ ] Documentation
- [ ] Tests only

## Tests

List the checks you ran:

- [ ] `uv run --directory backend --locked python -m compileall -q src`
- [ ] `uv run --directory backend --locked python -m unittest discover -s tests/contract -p "*contract.py"`
- [ ] `uv run --directory backend --locked python -m unittest discover -s tests/integration -p "*.py"`
- [ ] `uv run --directory backend --locked python -m unittest discover -s tests/migration -p "*.py"`
- [ ] `uv run --directory backend --locked python tests/import_boundaries.py`
- [ ] `uv run --directory integrations/mcp --locked python -m unittest discover -s tests -p "*contract.py"`
- [ ] `python -m unittest discover -s .github/scripts -p "test_*.py"` (release workflow changes; requires `packaging`)
- [ ] `npm run docs:build` (documentation changes)
- [ ] `npm --prefix web run typecheck && npm --prefix web run build`
- [ ] Manual smoke test:

## Notes

- Breaking changes:
- API-provider assumptions:
- Known limitations:

## Safety

- [ ] I did not commit API keys, tokens, cookies, private search history, or protected full-text content.
- [ ] This change does not add paywall bypass, credential sharing, or bulk protected PDF downloading.
