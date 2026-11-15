

def test_a_pick_in_a_single_and_a_parlay_counts_once():
    import betlog as B
    def bet(i, p, ticket=None, stake=2.0, odds=-125, market="Receptions", result="win"):
        return dict(id=i, slate_date="2026-11-15", player=p, market=market, side="Under", line=4.5, ticket=ticket,
                    stake=stake, entry_odds=odds, result=result, is_real_bet=1)
    bets = [bet(1, "A"), bet(2, "B", result="loss"),
            bet(3, None, ticket="T", stake=2.5, odds=945, market=B.PARLAY_MARKET, result="loss"),
            bet(4, "A", ticket="T", stake=0.0, odds=None), bet(5, "B", ticket="T", stake=0.0, odds=None, result="loss"),
            bet(6, "C", ticket="T", stake=0.0, odds=None)]                 # C only in the parlay: still a pick
    assert [b["id"] for b in B.pick_bets(bets)] == [1, 2, 6]
    rec = {m["market"]: (m["wins"], m["losses"]) for m in B.market_breakdown(bets)}
    assert rec["Receptions"] == (2, 1)
    s = B.summary(bets)
    assert (s["wins"], s["losses"], s["staked"]) == (1, 2, 6.5)            # money: 2 singles + the ticket
