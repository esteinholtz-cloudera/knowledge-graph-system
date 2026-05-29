"""Interactive review of predicate_map.yaml."""
from __future__ import annotations
from pathlib import Path
import yaml

_DIVIDER = "─" * 52


def interactive_review(map_file: str) -> int:
    """
    Walk through unreviewed mappings one at a time and ask the user to confirm.

    Choices:
      y / Enter  — accept as-is, mark reviewed
      n          — enter a different canonical, then mark reviewed
      s          — skip (leave unreviewed)
      q          — quit and save progress

    Returns number of mappings marked reviewed this session.
    """
    map_path = Path(map_file)
    if not map_path.exists():
        print(f"No predicate map at {map_path}. Run 'normalize scan' first.")
        return 0

    mapping = yaml.safe_load(map_path.read_text())
    all_mappings = mapping.get("mappings", [])
    pending = [m for m in all_mappings if not m.get("reviewed")]

    if not pending:
        print("All mappings already reviewed.")
        return 0

    reviewed_count = 0
    total = len(pending)
    print(f"\n{total} mapping(s) to review.  y=accept  n=rename  s=skip  q=quit\n")

    for idx, entry in enumerate(pending, 1):
        canonical = entry["canonical"]
        variants = entry.get("variants", [canonical])
        total_uses = entry.get("total_uses", 0)
        reason = entry.get("reason", "")

        print(_DIVIDER)
        print(f"  {idx}/{total}  canonical: {canonical}  ({total_uses} uses)")
        if len(variants) > 1:
            print(f"  Variants:")
            for v in variants:
                marker = "✓" if v == canonical else " "
                print(f"    {marker} {v}")
        if reason and reason not in ("singleton — no mapping needed",):
            print(f"  Reason: {reason}")
        print()

        while True:
            choice = input("  ok? [y/n/s/q]: ").strip().lower()
            if choice in ("y", ""):
                entry["reviewed"] = True
                reviewed_count += 1
                break
            elif choice == "n":
                new_canonical = input("  New canonical: ").strip()
                if new_canonical:
                    entry["canonical"] = new_canonical
                    entry["reviewed"] = True
                    reviewed_count += 1
                    print(f"  → Renamed to '{new_canonical}'")
                    break
                print("  (empty — keeping original)")
            elif choice == "s":
                print("  Skipped.")
                break
            elif choice == "q":
                _save(map_path, mapping, all_mappings)
                print(f"\n  Quit. {reviewed_count} reviewed this session. Progress saved.")
                return reviewed_count
            else:
                print("  Invalid choice.")

    _save(map_path, mapping, all_mappings)
    remaining = sum(1 for m in all_mappings if not m.get("reviewed"))
    print(f"\n{_DIVIDER}")
    print(f"  Review complete: {reviewed_count} reviewed this session.")
    if remaining:
        print(f"  {remaining} mapping(s) still unreviewed.")
    else:
        print(f"  All mappings reviewed. Run 'normalize apply' when ready.")
    print(_DIVIDER)
    return reviewed_count


def _save(map_path: Path, mapping: dict, all_mappings: list):
    mapping["mappings"] = all_mappings
    map_path.write_text(yaml.dump(mapping, allow_unicode=True, sort_keys=False))
