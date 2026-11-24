from __future__ import annotations

import argparse
from pathlib import Path

from jarvis.memory.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS local-first core")
    parser.add_argument("--db", default="../data/jarvis-core.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("remember", help="save a memory")
    add.add_argument("text")
    sub.add_parser("memories", help="list saved memories")
    delete = sub.add_parser("forget", help="soft-delete a memory by ID")
    delete.add_argument("id")
    args = parser.parse_args()
    store = MemoryStore(Path(args.db))
    if args.command == "remember":
        print(store.add_memory(args.text))
    elif args.command == "memories":
        for item in store.list_memories():
            print(f"{item['id']} [{item['kind']}] {item['content']}")
    elif args.command == "forget":
        print("Deleted." if store.delete_memory(args.id) else "Memory not found.")


if __name__ == "__main__":
    main()
