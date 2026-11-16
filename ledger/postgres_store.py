import hashlib
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from .store import memory_body, now, rank_memories


class PostgresStore:
    """Durable research records with local chat, caches and usage counters."""

    def __init__(self, local, url, workspace="owner"):
        self.local = local
        self.url = url
        self.workspace = workspace

    def for_visitor(self, visitor):
        return self.local.for_visitor(visitor)

    def for_public_research(self, visitor):
        return PostgresStore(self.local.for_visitor(visitor), self.url, "public")

    def for_account(self, account):
        return PostgresStore(self.local.for_account(account), self.url, f"account:{account}")

    def connect(self):
        return self.local.connect()

    def chat_history(self, session, limit=100):
        return self.local.chat_history(session, limit)

    def save_chat(self, session, question, answer):
        self.local.save_chat(session, question, answer)

    def reserve_trade_proposal(self, proposal, daily_limit_cents):
        # The trading MCP is local-only; keep its budget ledger off the public site.
        return self.local.reserve_trade_proposal(proposal, daily_limit_cents)

    def save_trading_record(self, record):
        from .trading_dashboard import merge_trading_record
        with self._db() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext('thesis-ledger-trial-budget'))")
            rows = db.execute("SELECT payload FROM thesis_ledger.records WHERE workspace='owner' "
                              "AND kind IN ('broker_snapshot','trade_event','trading_request')").fetchall()
            record = merge_trading_record(record, [row[0] for row in rows])
            db.execute("INSERT INTO thesis_ledger.records VALUES (%s,%s,%s,%s,%s) "
                       "ON CONFLICT (workspace,kind,id) DO UPDATE SET payload=excluded.payload",
                       ("owner", record["kind"], record["id"], record["created"], Jsonb(record)))

    def claim_research_review(self):
        from .review_queue import claim_review, release_stale_reviews
        with self._db() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext('thesis-ledger-trial-budget'))")
            rows = db.execute("SELECT payload FROM thesis_ledger.records WHERE workspace='owner' AND kind IN ('broker_snapshot','trade_event','trading_cycle','trading_request')").fetchall()
            records = [row[0] for row in rows]
            updates = release_stale_reviews(records)
            record = claim_review(records)
            if record:
                updates.append(record)
            for updated in updates:
                db.execute("UPDATE thesis_ledger.records SET payload=%s WHERE workspace='owner' AND kind=%s AND id=%s", (Jsonb(updated), updated["kind"], updated["id"]))
            return record

    def cancel_trading_request(self, request_id):
        with self._db() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext('thesis-ledger-trial-budget'))")
            row = db.execute("SELECT payload FROM thesis_ledger.records WHERE workspace='owner' AND kind='trading_request' AND id=%s FOR UPDATE", (request_id,)).fetchone()
            if not row:
                raise KeyError(request_id)
            record = row[0]
            if record["payload"].get("status") not in {"queued", "research_queued", "cancelled"}:
                raise ValueError("Only queued reviews can be removed")
            record["payload"].update(status="cancelled", cancelled_at=now())
            db.execute("UPDATE thesis_ledger.records SET payload=%s WHERE workspace='owner' AND kind='trading_request' AND id=%s", (Jsonb(record), request_id))

    def trading_access_digest(self):
        with self._db() as db:
            row = db.execute("SELECT payload->'payload'->>'sha256' FROM thesis_ledger.records "
                             "WHERE workspace='owner' AND kind='trading_access' AND id='owner'").fetchone()
        return row[0] if row else None

    def trading_records(self):
        with self._db() as db:
            rows = db.execute(
                "SELECT payload FROM thesis_ledger.records WHERE workspace='owner' "
                "AND kind IN ('broker_snapshot','trading_cycle','trade_event','trading_request','worker_status','market_observation') "
                "ORDER BY created DESC LIMIT 300"
            ).fetchall()
        return [row[0] for row in rows]

    def cached_forecast(self, key):
        return self.local.cached_forecast(key)

    def save_forecast(self, key, result):
        self.local.save_forecast(key, result)

    def _db(self):
        return psycopg.connect(self.url, connect_timeout=8)

    def _save(self, kind, record_id, created, payload, *, replace=False):
        conflict = "DO UPDATE SET payload = excluded.payload" if replace else "DO NOTHING"
        with self._db() as db:
            db.execute(
                "INSERT INTO thesis_ledger.records VALUES (%s,%s,%s,%s,%s) "
                f"ON CONFLICT (workspace,kind,id) {conflict}",
                (self.workspace, kind, record_id, created, Jsonb(payload)),
            )

    def save(self, state):
        self._save("run", state["id"], state["created"], state, replace=True)

    def get(self, run_id):
        with self._db() as db:
            row = db.execute(
                "SELECT payload FROM thesis_ledger.records "
                "WHERE workspace=%s AND kind='run' AND id=%s",
                (self.workspace, run_id),
            ).fetchone()
        if not row:
            raise KeyError("Run not found")
        return row[0]

    def runs(self):
        with self._db() as db:
            rows = db.execute(
                "SELECT payload FROM thesis_ledger.records WHERE workspace=%s AND kind='run' "
                "ORDER BY created DESC LIMIT 100",
                (self.workspace,),
            ).fetchall()
        return [row[0] for row in rows]

    def latest_live_report(self, ticker):
        with self._db() as db:
            row = db.execute(
                """SELECT payload FROM thesis_ledger.records
                WHERE workspace=%s AND kind='run' AND payload->>'status'='complete'
                  AND payload->'request'->>'mode'='live'
                  AND payload->'request'->>'ticker'=%s
                  AND payload->'request'->>'as_of' <= %s
                ORDER BY payload->'request'->>'as_of' DESC, created DESC LIMIT 1""",
                (self.workspace, ticker, datetime.now(timezone.utc).date().isoformat()),
            ).fetchone()
        return row[0] if row else None

    def remember(self, run):
        body = memory_body(run)
        memory = dict(
            id=uuid.uuid4().hex,
            run_id=run["id"],
            ticker=run["request"]["ticker"],
            mode=run["request"]["mode"],
            as_of=run["request"]["as_of"],
            created=now(),
            body=body,
            digest=hashlib.sha256(body.encode()).hexdigest(),
        )
        self._save("memory", run["id"], memory["created"], memory)

    def memories(self, ticker=None, mode=None, as_of=None, query="", limit=20):
        with self._db() as db:
            rows = db.execute(
                "SELECT kind, payload FROM thesis_ledger.records "
                "WHERE workspace=%s AND kind IN ('memory', 'revision') ORDER BY created",
                (self.workspace,),
            ).fetchall()
        memories = [payload for kind, payload in rows if kind == "memory"]
        revisions = [payload for kind, payload in rows if kind == "revision"]
        return rank_memories(memories, revisions, ticker, mode, as_of, query, limit)

    def revise(self, memory_id, feedback, scope):
        with self._db() as db:
            exists = db.execute(
                "SELECT 1 FROM thesis_ledger.records "
                "WHERE workspace=%s AND kind='memory' AND payload->>'id'=%s",
                (self.workspace, memory_id),
            ).fetchone()
        if not exists:
            raise KeyError("Memory not found")
        revision = dict(id=uuid.uuid4().hex, memory_id=memory_id, created=now(),
                        scope=scope, feedback=feedback)
        self._save("revision", revision["id"], revision["created"], revision)
        return revision
