import asyncio
from datetime import datetime, timezone

import pytest

from ledger import monitor as worker
from ledger.store import Store
from ledger.trading_dashboard import funding_status


PROPOSAL = dict(id="p1",run_id="r1",ticker="AAPL",side="buy",amount_usd="20.00")


class Broker:
    def __init__(self, *, approvals=True, review_approval=True, alerts=None):
        self.calls=[]
        self.approvals=approvals
        self.review_approval=review_approval
        self.alerts=alerts or {}

    async def pages(self,name,key,**arguments):
        self.calls.append(name)
        return {key:[]}

    async def call(self,name,**arguments):
        self.calls.append(name)
        if name=="get_equity_tradability":
            return {"results":[dict(symbol="AAPL",tradeable=True,state="active",fractional_tradability="tradable",
                account_type_tradabilities=[dict(account_type="individual",account_type_tradability="tradable")])]}
        if name=="get_portfolio":
            return {"buying_power":{"unleveraged_buying_power":"20"}}
        if name=="review_equity_order":
            return dict(symbol="AAPL",side="buy",type="market",dollar_amount="20.00",
                customer_approval_required=self.review_approval,order_checks=self.alerts,
                quote_data={"has_traded":True,"last_trade_price":"200"})
        if name=="get_trade_approval_setting":
            return {"setting":{"human_must_approve_trades":self.approvals}}
        if name=="place_equity_order":
            assert arguments["ref_id"]=="p1"
            return {"approval":{"id":"approval1","state":"pending"}}
        raise AssertionError(name)


def monitor(tmp_path,monkeypatch,broker):
    monkeypatch.setattr(worker,"regular_session",lambda instant:True)
    class Planner:
        def __init__(self,store):pass
        def prepare(self,*args):return PROPOSAL
    monkeypatch.setattr(worker,"TradePlanner",Planner)
    store=Store(tmp_path)
    store.save_trading_record(dict(id="s1",kind="broker_snapshot",created="2026-11-16T20:00:00Z",
        payload=dict(orders=[],orders_complete=True,buying_power="20",approvals=[])))
    instance=worker.CloudMonitor(broker,store)
    instance.account={"account_number":"test-account","brokerage_account_type":"individual"}
    return instance,store


@pytest.mark.parametrize("config",[{"approvals":False},{"review_approval":False},{"alerts":{"alert_type":"BUYING_POWER"}}])
def test_cloud_worker_blocks_unapproved_or_flagged_requests(tmp_path,monkeypatch,config):
    broker=Broker(**config)
    instance,store=monitor(tmp_path,monkeypatch,broker)
    asyncio.run(instance.request_approval(PROPOSAL))
    assert "place_equity_order" not in broker.calls
    events=[r for r in store.trading_records() if r["kind"]=="trade_event"]
    assert events[0]["payload"]["state"]=="blocked"


def test_cloud_worker_records_approval_separately_from_fill(tmp_path,monkeypatch):
    broker=Broker()
    instance,store=monitor(tmp_path,monkeypatch,broker)
    asyncio.run(instance.request_approval(PROPOSAL))
    assert broker.calls[-2:]==["get_trade_approval_setting","place_equity_order"]
    event=next(r for r in store.trading_records() if r["kind"]=="trade_event")
    assert event["payload"]["state"]=="awaiting_approval"
    assert event["payload"]["approval_id"]=="approval1"
    assert event["payload"]["history"][0]["state"]=="submission_unknown"
    snapshot=next(r for r in store.trading_records() if r["kind"]=="broker_snapshot")
    assert funding_status(snapshot["payload"],[event])["remaining"]=="0"


def test_market_calendar_uses_early_closes_and_holidays():
    assert not worker.regular_session(datetime(2026,11,26,16,tzinfo=timezone.utc))
    assert worker.regular_session(datetime(2026,11,27,17,tzinfo=timezone.utc))
    assert not worker.regular_session(datetime(2026,11,27,19,tzinfo=timezone.utc))


def test_direct_record_store_needs_no_browser_key(tmp_path,monkeypatch):
    from ledger.trading_dashboard import TradingRecord, publish_record, dashboard_state
    monkeypatch.delenv("LEDGER_TRADING_TOKEN",raising=False)
    store=Store(tmp_path)
    record=TradingRecord(id="s1",kind="broker_snapshot",created="2026-11-16T20:00:00Z",
        payload=dict(account_value="20",orders=[],orders_complete=True,buying_power="20"))
    async def roundtrip():
        await publish_record(record,store)
        return await dashboard_state(store)
    result=asyncio.run(roundtrip())
    assert result["snapshot"]["id"]=="s1"
    assert result["funding"]["remaining"]=="20.00"
