ALTER TABLE thesis_ledger.records DROP CONSTRAINT records_kind_check;
ALTER TABLE thesis_ledger.records ADD CONSTRAINT records_kind_check
    CHECK (kind IN ('run','memory','revision','broker_snapshot','trading_cycle',
                    'trade_event','trading_request','trading_access'));
ALTER TABLE thesis_ledger.records ADD CONSTRAINT private_trading_workspace
    CHECK (kind IN ('run','memory','revision') OR workspace='owner');
