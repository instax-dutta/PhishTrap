import argparse

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="PhishTrap dataset auto-update pipeline"
    )
    parser.add_argument(
        "--force-full",
        action="store_true",
        help="Skip incremental merge, rebuild from scratch",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=10000,
        help="Max total samples per class (default 10000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, merge, prune, rebalance but do not upload",
    )
    return parser.parse_args(argv)
