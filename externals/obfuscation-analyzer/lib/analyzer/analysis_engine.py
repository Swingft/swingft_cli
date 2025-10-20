from .graph_loader import SymbolGraph
from .rule_loader import RuleLoader
from .pattern_matcher import PatternMatcher


class AnalysisEngine:
    """
    Loads a symbol graph and a set of rules, then runs the analysis
    to find all symbols that should be excluded from obfuscation.
    """

    def __init__(self, graph: SymbolGraph, rules: RuleLoader):
        self.graph = graph
        self.rules = rules.rules
        self.matcher = PatternMatcher(self.graph)
        self.excluded_symbols = {}

    def run(self):
        """
        Iterates through all loaded rules and applies them to the symbol graph.
        """
        print("🚀 Starting exclusion analysis...")

        # Iterate over each rule loaded from the YAML file
        for i, rule in enumerate(self.rules):
            rule_id = rule.get('id', 'Unknown Rule')
            print(f"  - Running rule [{i + 1}/{len(self.rules)}] \"{rule_id}\"...")

            pattern = rule.get('pattern')
            if not pattern:
                print(f"    ⚠️  Skipping rule with no pattern: {rule_id}")
                continue

            # Use the pattern matcher to find all matching symbol IDs
            matched_ids = self.matcher.match(pattern)
            print(f"    Found {len(matched_ids)} matching symbols.")

            # For each matched symbol, store it with the reason for exclusion
            for symbol_id in matched_ids:
                reason = {
                    "rule_id": rule_id,
                    "description": rule.get('description', 'No description provided.')
                }

                # If this symbol is already excluded, add another reason
                if symbol_id not in self.excluded_symbols:
                    self.excluded_symbols[symbol_id] = []
                self.excluded_symbols[symbol_id].append(reason)

        print(f"✅ Analysis complete. Found {len(self.excluded_symbols)} unique symbols to exclude.")

    def get_results(self) -> list:
        """
        Formats the analysis results into a structured list of dictionaries,
        ready for JSON export.
        """
        results = []

        # Iterate through the dictionary of excluded symbols
        for symbol_id, reasons in self.excluded_symbols.items():
            symbol_data = self.graph.get_node(symbol_id)
            if symbol_data:
                # Append a structured dictionary for each excluded symbol
                results.append({
                    "name": symbol_data.get("name"),
                    "kind": symbol_data.get("kind"),
                    "location": symbol_data.get("location"),
                    "reasons": reasons
                })

        return results