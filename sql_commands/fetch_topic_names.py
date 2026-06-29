"""
Fetch all topic names for a given property from the public.topics table.

Looks up the property by name (user_defined_name) or UUID, then runs:

    SELECT * FROM public.topics
    WHERE property_id IN (
        SELECT property_id FROM public.property
        WHERE user_defined_name = <property_name>
    )

Usage:
    python sql_commands/fetch_topic_names.py --property-name msa_orient_building_1
    python sql_commands/fetch_topic_names.py --property-name msa_orient_building_1 --floor Floor_02
    python sql_commands/fetch_topic_names.py --property-name msa_orient_building_1 --output data/snapshots/topics_raw.csv

Requires the SSH tunnel to be open before running:
    ssh -i <key.pem> -L 5432:<rds-host>:5432 ec2-user@<bastion-ip> -N

DB credentials are read from the .env file in the project root.
"""

import argparse
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _connect():
    host = os.getenv("DB_HOST")
    dbname = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    port = int(os.getenv("DB_PORT") or 5432)

    # When using the SSH tunnel, connect via localhost
    connect_host = "127.0.0.1" if host and "rds.amazonaws.com" in host else host

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=connect_host, dbname=dbname, user=user, password=password, port=port
        )
        conn.set_session(readonly=True)
        return conn
    except ImportError:
        pass

    try:
        import psycopg
        conn = psycopg.connect(
            host=connect_host, dbname=dbname, user=user, password=password, port=port
        )
        conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        return conn
    except ImportError:
        pass

    print("Error: install psycopg2 or psycopg — pip install psycopg2-binary")
    sys.exit(1)


def fetch_topics(property_name: str, floor_prefix: str | None = None):
    conn = _connect()
    try:
        cursor = conn.cursor()
        if floor_prefix:
            cursor.execute(
                """
                SELECT t.*
                FROM public.topics t
                WHERE t.property_id IN (
                    SELECT property_id FROM public.property
                    WHERE user_defined_name = %s
                )
                AND t.topic_name LIKE %s
                ORDER BY t.topic_name
                """,
                (property_name, f"{floor_prefix}/%"),
            )
        else:
            cursor.execute(
                """
                SELECT t.*
                FROM public.topics t
                WHERE t.property_id IN (
                    SELECT property_id FROM public.property
                    WHERE user_defined_name = %s
                )
                ORDER BY t.topic_name
                """,
                (property_name,),
            )
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        return columns, rows
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Fetch topics for a property by name.")
    parser.add_argument(
        "--property-name",
        default="msa_orient_building_1",
        help="Property user_defined_name (default: msa_orient_building_1)",
    )
    parser.add_argument("--floor", default=None, help="Optional floor prefix, e.g. Floor_02")
    parser.add_argument("--output", default=None, help="Optional CSV output path")
    args = parser.parse_args()

    print(f"Connecting to database...")
    columns, rows = fetch_topics(args.property_name, args.floor)
    print(f"Found {len(rows)} topic(s) for property '{args.property_name}'")

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        print(f"Saved to {output_path}")
    else:
        print("\t".join(columns))
        for row in rows:
            print("\t".join(str(v) for v in row))


if __name__ == "__main__":
    main()
