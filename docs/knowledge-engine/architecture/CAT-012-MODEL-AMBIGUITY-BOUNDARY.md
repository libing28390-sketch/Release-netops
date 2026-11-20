# CAT-012 Model Ambiguity Boundary

CAT-012 defines what the assistant may safely use when an alias resolves to
more than one product model. The policy accepts only explicit reviewed catalog
context; it never parses a model ID or alias to guess a vendor, operating
system, platform, credential or driver.

When candidates share one reviewed vendor/family/series, series-level hardware
knowledge may be used, while model-specific and platform-specific knowledge is
blocked and the assistant must ask for the full model. Broader ambiguity drops
the safe scope to family, vendor or generic knowledge and expands the required
clarification fields. A unique reviewed model may use model-level knowledge,
but driver selection, credential selection and write-command generation remain
forbidden.

Final Conclusion: PASS
