ALTER TABLE thesis_ledger.records DROP CONSTRAINT records_kind_check;
ALTER TABLE thesis_ledger.records ADD CONSTRAINT records_kind_check
CHECK (kind IN ('run','memory','revision','broker_snapshot','trading_cycle','trade_event',
               'trading_request','trading_access','broker_auth','worker_status','market_observation'));
-- The existing private_trading_workspace constraint keeps every additional kind owner-only.
