import argparse
import json
from pathlib import Path

from .build import order_snapshot
from .export import export_tables
from .ingest import ingest
from .queries import line_quantities, overview
from .storage import open_store


def main():
    parser = argparse.ArgumentParser(description='本地仓库日常接收与核对')
    parser.add_argument('--database', default='warehouse.duckdb')
    commands = parser.add_subparsers(dest='action', required=True)
    load = commands.add_parser('load', help='接收一个业务包')
    load.add_argument('file', type=Path)
    commands.add_parser('overview', help='查看现有业务汇总')
    snapshot = commands.add_parser('snapshot', help='查看订单行累积快照')
    snapshot.add_argument('--line', dest='line_id')
    output = commands.add_parser('export', help='冻结列式导出')
    output.add_argument('destination', type=Path)
    output.add_argument('revision')
    args = parser.parse_args()
    connection = open_store(args.database)
    try:
        if args.action == 'load':
            result = ingest(connection, json.loads(args.file.read_text(encoding='utf-8')))
        elif args.action == 'export':
            result = export_tables(connection, args.destination, args.revision)
        elif args.action == 'snapshot':
            result = (line_quantities(connection, args.line_id) if args.line_id
                      else order_snapshot(connection))
        else:
            result = overview(connection)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    finally:
        connection.close()


if __name__ == '__main__':
    main()
