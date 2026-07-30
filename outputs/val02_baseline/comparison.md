# VAL-02 After-Baseline Comparison (NVDA / CRM / JPM)

Generated: 2026-07-29T06:16:28.450594+00:00

Baseline (before) from part 2; after = same tickers with argued-input path wired.

## Scores

| Ticker | Before | After | Δ | Excl. C9 before* | Excl. C9 after* | Δ quality |
|--------|-------:|------:|--:|-----------------:|----------------:|----------:|
| NVDA | 10/11 | 8/11 | -2 | 10/10 | 7/10 | -3 |
| CRM | 7/11 | 7/11 | 0 | 7/10 | 6/10 | -1 |
| JPM | 9/11 | 8/11 | -1 | 9/10 | 7/10 | -2 |

\*Excl. C9: criterion 9 (default+judgment present) is a plumbing check once `dcf_judgment`/`comps_judgment` exist — not evidence of quality improvement.

## Per-criterion before → after

### NVDA

| # | Criterion | Before | After | Flip |
|---|-----------|:------:|:-----:|:----:|
| 1 | Archetype named and primary method justified | PASS | PASS | · |
| 2 | Every argued input cites ≥1 resolvable evidence field | PASS | FAIL | ↓ FAIL |
| 3 | No currency figure appears that is not traceable to an engine block | PASS | FAIL | ↓ FAIL |
| 4 | Terminal-value share of EV stated (DCF path) | PASS | PASS | · |
| 5 | Valuation expressed as a range, not a point | PASS | PASS | · |
| 6 | Each peer inclusion/exclusion justified individually | PASS | PASS | · |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | PASS | PASS | · |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | PASS | PASS | · |
| 9 | Both default and judgment cases present ⚠ plumbing | FAIL | PASS | ↑ PASS |
| 10 | Band dissents flagged where applicable | PASS | PASS | · |
| 11 | No internal numeric contradiction (same metric, two values) | PASS | FAIL | ↓ FAIL |

**After fail details:**
- **2 evidence_for_argued_inputs**: dcf:g_high: no resolvable evidence (tried: canonical_metrics.fcf_yoy, canonical_metrics.revenue_yoy, canonical_metrics.gross_margin_yoy_bps, canonical_metrics.operating_margin_yoy_bps); dcf:base_fcf_method: no resolvable evidence (tried: canonical_metrics.fcf__current_annual, canonical_metrics.fcf_annualized_from_current_quarter, canonical_metrics.fcf_margin__current_annual, canonical_metrics.fcf_margin__current_quarter); peer:TSM: no resolvable evidence (tried: capex_pct_revenue__current_annual, fcf_margin__current_annual, gross_margin__current_annual); peer:INTC: no resolvable evidence (tried: revenue_yoy, operating_income_yoy, operating_margin__current_annual); peer:AMD: no resolvable evidence (tried: net_income__current_annual, net_margin__current_annual); peer:AAPL: no resolvable evidence (tried: market_cap, market_cap_price_x_shares); peer:MSFT: no resolvable evidence (tried: revenue__current_quarter, revenue_annualized_from_current_quarter); justified_multiple: no resolvable evidence (tried: revenue_yoy, net_income_yoy, operating_margin__current_annual, gross_margin_yoy_bps)
- **3 no_untraceable_currency**: untraceable currency: $16.4B, $27.02B
- **11 no_numeric_contradiction**: contradictions: wacc: [0.1, 1.0]; fair_value: [318.63, 100.0, 197.01]; eps: [4.9, 1.0]
- Focus **C3 Untraceable currency**: before=PASS (30 currency figure(s) traceable to engine blocks) → after=FAIL (untraceable currency: $16.4B, $27.02B)
- Focus **C7 Mixed windows**: before=PASS (windows present: 5y, yoy) → after=PASS (windows present: 1y, 3y, 5y, yoy)
- Focus **C9 Default+judgment (plumbing)**: before=FAIL (missing: dcf_judgment, comps_judgment) → after=PASS (dcf_base=True dcf_judgment=True comps_base=True comps_judgment=True comps_applicable=True)
- Focus **C11 Self-contradiction**: before=PASS (no contradictions across 5 identity metric(s)) → after=FAIL (contradictions: wacc: [0.1, 1.0]; fair_value: [318.63, 100.0, 197.01]; eps: [4.9, 1.0])

### CRM

| # | Criterion | Before | After | Flip |
|---|-----------|:------:|:-----:|:----:|
| 1 | Archetype named and primary method justified | PASS | PASS | · |
| 2 | Every argued input cites ≥1 resolvable evidence field | PASS | FAIL | ↓ FAIL |
| 3 | No currency figure appears that is not traceable to an engine block | FAIL | FAIL | · |
| 4 | Terminal-value share of EV stated (DCF path) | PASS | PASS | · |
| 5 | Valuation expressed as a range, not a point | PASS | PASS | · |
| 6 | Each peer inclusion/exclusion justified individually | PASS | PASS | · |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | FAIL | FAIL | · |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | PASS | PASS | · |
| 9 | Both default and judgment cases present ⚠ plumbing | FAIL | PASS | ↑ PASS |
| 10 | Band dissents flagged where applicable | PASS | PASS | · |
| 11 | No internal numeric contradiction (same metric, two values) | FAIL | FAIL | · |

**After fail details:**
- **2 evidence_for_argued_inputs**: dcf:base_fcf_method: no resolvable evidence (tried: canonical_metrics.fcf__current_annual, canonical_metrics.fcf__prior_annual, cash_flow.annual_series_derived, canonical_metrics.fcf_conversion__current_annual); peer:SNOW: no resolvable evidence (tried: net_income__current_annual, net_margin__current_annual, fcf__current_annual, ev_to_ebitda); peer:NOW: no resolvable evidence (tried: revenue_yoy, trailing_pe, revenue__current_annual); peer:ADBE: no resolvable evidence (tried: gross_margin__current_annual, rd_pct_revenue__current_annual, revenue_yoy); peer:ORCL: no resolvable evidence (tried: total_debt__current_quarter, debt_to_equity__current_quarter, net_cash_ex_st_investments__current_quarter, net_cash_ex_st_investments__prior_annual); justified_multiple: no resolvable evidence (tried: revenue_yoy, operating_margin__current_annual, operating_margin_yoy_bps, gross_margin__current_annual)
- **3 no_untraceable_currency**: untraceable currency: $800M, $63B, $25B, $46.0B
- **7 comparison_windows_consistent**: mixed comparison windows: ytd, 1y, 3y, 5y, yoy
- **11 no_numeric_contradiction**: contradictions: eps: [22.6, 7.8]; g_high: [0.158, 0.09]
- Focus **C3 Untraceable currency**: before=FAIL (untraceable currency: $23B, $46.0B, $57,000, $57.94B) → after=FAIL (untraceable currency: $800M, $63B, $25B, $46.0B)
- Focus **C7 Mixed windows**: before=FAIL (mixed comparison windows: ytd, 1y, 5y, yoy) → after=FAIL (mixed comparison windows: ytd, 1y, 3y, 5y, yoy)
- Focus **C9 Default+judgment (plumbing)**: before=FAIL (missing: dcf_judgment, comps_judgment) → after=PASS (dcf_base=True dcf_judgment=True comps_base=True comps_judgment=True comps_applicable=True)
- Focus **C11 Self-contradiction**: before=FAIL (contradictions: g_high: [0.158, 0.05]; eps: [7.8, 11.7]) → after=FAIL (contradictions: eps: [22.6, 7.8]; g_high: [0.158, 0.09])

### JPM

| # | Criterion | Before | After | Flip |
|---|-----------|:------:|:-----:|:----:|
| 1 | Archetype named and primary method justified | PASS | PASS | · |
| 2 | Every argued input cites ≥1 resolvable evidence field | PASS | FAIL | ↓ FAIL |
| 3 | No currency figure appears that is not traceable to an engine block | FAIL | FAIL | · |
| 4 | Terminal-value share of EV stated (DCF path) | PASS | PASS | · |
| 5 | Valuation expressed as a range, not a point | PASS | PASS | · |
| 6 | Each peer inclusion/exclusion justified individually | PASS | PASS | · |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | PASS | PASS | · |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | PASS | PASS | · |
| 9 | Both default and judgment cases present ⚠ plumbing | FAIL | PASS | ↑ PASS |
| 10 | Band dissents flagged where applicable | PASS | PASS | · |
| 11 | No internal numeric contradiction (same metric, two values) | PASS | FAIL | ↓ FAIL |

**After fail details:**
- **2 evidence_for_argued_inputs**: dcf:g_terminal: no resolvable evidence (tried: cash_flow.current_annual.derived.payout_ratio_total_pct, cash_flow.current_annual.derived.note, canonical_metrics.roe__current_annual, balance_sheet.annual_series_note); dcf:g_high: no resolvable evidence (tried: canonical_metrics.revenue_yoy, canonical_metrics.net_income_yoy, canonical_metrics.operating_income_yoy, income_statement.current_quarter.derived.annualized_net_income); dcf:high_growth_years: no resolvable evidence (tried: dcf_engine.projection_path, income_statement.current_annual.ProvisionForCreditLosses, balance_sheet.current_quarter.derived.assets_to_equity_leverage_x, balance_sheet.prior_annual.derived.note); dcf:base_fcf_method: no resolvable evidence (tried: income_statement.current_annual.adjusted, income_statement.current_annual.ProvisionForCreditLosses, income_statement.current_quarter.derived.pe_on_annualized_q1_eps, income_statement.annual_series_note); peer:USB: no resolvable evidence (tried: noninterest_income__current_annual, revenue__current_annual, market_cap); peer:PNC: no resolvable evidence (tried: total_assets__current_annual, roe__current_annual, market_cap); justified_multiple: no resolvable evidence (tried: roe__current_annual, net_margin__current_annual, operating_margin__current_annual, operating_margin_yoy_bps)
- **3 no_untraceable_currency**: untraceable currency: $1.4776T, $2.2B, $1.48T, $3.5B, $3.8B, $14.21B, $14.212B
- **11 no_numeric_contradiction**: contradictions: eps: [20.02, 1.4, 21.14, 23.76]
- Focus **C3 Untraceable currency**: before=FAIL (untraceable currency: $14.212B, $10.678B, $10B, $4.1T, $2.2B) → after=FAIL (untraceable currency: $1.4776T, $2.2B, $1.48T, $3.5B, $3.8B, $14.21B, $14.212B)
- Focus **C7 Mixed windows**: before=PASS (windows present: yoy) → after=PASS (windows present: 3y, 5y, yoy)
- Focus **C9 Default+judgment (plumbing)**: before=FAIL (missing: dcf_judgment, comps_judgment) → after=PASS (dcf_base=True dcf_judgment=True comps_base=True comps_judgment=True comps_applicable=True)
- Focus **C11 Self-contradiction**: before=PASS (no contradictions across 2 identity metric(s)) → after=FAIL (contradictions: eps: [20.02, 1.4, 21.14, 23.76])

## ICL plumbing (after runs only)

### NVDA
- DCF critique parseable: **True**
- Relative critique parseable: **True**
- DCF args proposed / accepted / rejected: **5 / 4 / 1**
- Proposed: `['wacc', 'g_high', 'g_terminal', 'base_fcf_method', 'fade_years']`
- Accepted: `['wacc', 'g_high', 'g_terminal', 'fade_years']`
- Rejected: `['base_fcf_method']`
- Band dissents (n=4): `[{'parameter': 'wacc', 'argued_range': [0.2, 0.2], 'archetype_band': [0.08, 0.12], 'reasoning': "A 10.0% WACC understates the risk of a business whose demand is an explicit derivative of hyperscaler capex (management's own capex→compute→revenue framing), with ~50% of data-center revenue from three hyperscalers, realized export-control loss (zero Hopper shipped to China vs $4.6B prior-year quarter), an unexplained ~$15.6B goodwill step-up (7.6% of assets) that has not been diligenced, and documented circular-financing/customer-backstop exposure. Balance-sheet risk is genuinely de minimis (debt/equity 0.043 at Q1 FY2027), so the premium belongs entirely in the equity risk premium for demand concentration and cyclicality, not in leverage. Also note macro commentary that the 10-year is the dominant multiple driver for this name; a discount rate at the sector default gives no cushion for that.", 'evidence': ['dcf_engine.wacc', 'dcf_engine.terminal_value_pv', 'canonical_metrics.debt_to_equity__current_quarter', 'canonical_metrics.goodwill_increment__current_annual_vs_prior_annual', 'canonical_metrics.goodwill_increment_pct_assets__current_annual', 'sec_filing_summary', 'macro_context']}, {'parameter': 'g_high', 'argued_range': [0.4, 0.4], 'archetype_band': [0.02, 0.2], 'reasoning': "35% compounded for five straight years takes FCF from $96.68B to $433.50B, which requires revenue several multiples of the current $326.46B annualized run-rate with no margin give. Two facts argue for a lower explicit-stage rate: FY2026 gross margin already compressed 392bps YoY and operating margin 204bps YoY while revenue grew 65.5%, and FCF growth (58.9%) already lagged revenue growth (65.5%) because of the working-capital build (inventory +112.3%, receivables +66.8%, AR+inventory = 81.5% of quarterly revenue). Trailing FCF growth is a poor extrapolant when the incremental dollar is being absorbed by inventory and the customer base is capex-derivative. 20–30% is still aggressive but does not require the base year's exceptional 59% to persist unbroken.", 'evidence': ['canonical_metrics.fcf_yoy', 'canonical_metrics.revenue_yoy', 'canonical_metrics.gross_margin_yoy_bps', 'canonical_metrics.operating_margin_yoy_bps', 'canonical_metrics.inventory_yoy', 'canonical_metrics.receivables_yoy', 'dcf_engine.g_high', 'balance_sheet.current_quarter.derived.ar_plus_inventory_pct_qtr_rev']}, {'parameter': 'g_terminal', 'argued_range': [0.035, 0.035], 'archetype_band': [0.01, 0.03], 'reasoning': "3.0% is at the upper end of a defensible nominal-GDP-anchored terminal rate but not indefensible given the company's software/ecosystem moat and asset-light capex profile (capex 2.8% of revenue). Because PV of terminal value is $5.04T against a $7.72T EV, the model is highly sensitive here, which argues for testing the low end at 2.25% rather than accepting 3.0% as the only case. Perpetual real growth above global GDP for a semiconductor franchise ten years out is the assumption most likely to be wrong in the bull direction.", 'evidence': ['dcf_engine.g_terminal', 'dcf_engine.terminal_value_pv', 'canonical_metrics.capex_pct_revenue__current_annual']}, {'parameter': 'fade_years', 'argued_range': [7, 10], 'archetype_band': [3, 7], 'reasoning': "A 5-year fade from 35% to 3% is an abrupt glide path for a franchise whose competitive position (integrated hardware plus CUDA/software ecosystem, networking revenue +199% in Q1 FY2027) plausibly decays slowly even as growth normalizes. If the explicit-stage rate is lowered as argued above, a longer fade is the internally consistent offset: it lets growth decelerate gradually rather than concentrating the entire deceleration into five years and then dumping the residual into a terminal value that already carries ~65% of EV. Lengthening the fade also reduces the model's reliance on the single most fragile input (g_terminal).", 'evidence': ['dcf_engine.fade_years', 'dcf_engine.terminal_value_pv', 'business_overview', 'canonical_metrics.rd_pct_revenue__current_annual']}]`
- Clamp warnings: `['wacc clamped from 11 to 0.2 within [0.05, 0.2]', 'wacc clamped from 13 to 0.2 within [0.05, 0.2]', 'g_high clamped from 20 to 0.4 within [-0.1, 0.4]', 'g_high clamped from 30 to 0.4 within [-0.1, 0.4]', 'g_terminal clamped from 2.25 to 0.035 within [0, 0.035]', 'g_terminal clamped from 3 to 0.035 within [0, 0.035]']`
- method_appropriate: `True` — NVDA is a fabless, essentially unlevered, cash-generative designer with capex at 2.8% of revenue and FCF conversion of 80.5% of net income, so a multi-stage unlevered FCF DCF is the right primary fram
- dcf_engine method/fv: `multi_stage_fcf_dcf` / `318.62611476243546`
- dcf_judgment fv/range: `None` / `{'low': 151.86038258444106, 'base': None, 'high': 193.41832454886853, 'basis': 'two argued-input range corners'}`
- comps_judgment present: **True** primary_multiple=`forward_pe`
- peer_changes proposed: `[{'ticker': 'TSM', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'INTC', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'AMD', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'AAPL', 'action': 'include', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'MSFT', 'action': 'include', 'has_evidence': True, 'has_reasoning': True}]`
- justified_multiple: `{'metric': 'forward_pe', 'argued_range': [26.0, 32.0], 'has_evidence': True, 'evidence': ['revenue_yoy', 'net_income_yoy', 'operating_margin__current_annual', 'gross_margin_yoy_bps', 'operating_margin_yoy_bps', 'fcf_margin__current_annual', 'fcf_conversion__current_annual', 'capex_pct_revenue__current_annual', 'debt_to_equity__current_annual', 'inventory_yoy', 'receivables_yoy', 'inventory__current_quarter', 'accounts_receivable__current_quarter', 'goodwill_increment__current_annual_vs_prior_annual', 'goodwill_increment_pct_assets__current_annual', 'buyback_dollars_per_pct_point__current_annual_vs_prior_annual', 'gross_margin__current_quarter', 'revenue_annualized_from_current_quarter']}`

### CRM
- DCF critique parseable: **True**
- Relative critique parseable: **True**
- DCF args proposed / accepted / rejected: **6 / 5 / 1**
- Proposed: `['g_high', 'wacc', 'g_terminal', 'base_fcf_method', 'high_growth_years', 'fade_years']`
- Accepted: `['g_high', 'wacc', 'g_terminal', 'high_growth_years', 'fade_years']`
- Rejected: `['base_fcf_method']`
- Band dissents (n=3): `[{'parameter': 'g_high', 'argued_range': [0.08, 0.11], 'archetype_band': [0.1, 0.3], 'reasoning': "The engine anchors 5 years of 15.8% FCF growth on the single-year fcf_yoy print. That print reflects margin expansion (operating margin +105 bps, fcf margin 32.8%->34.7%) layered on only 9.6% revenue growth — a mix that cannot repeat for five years once margin gains exhaust. Management's own FY27 guide of $45.8-46.2B is ~10.8% revenue growth and the FY30 $63B target implies ~11% CAGR; billings growth averaged ~11.3%. Worse, the Q1 recap took total debt from $14.44B to $39.28B, and at a realistic ~5% coupon that is roughly $1.6B of incremental pre-tax interest, a direct cash-flow haircut the 15.8% path ignores. 8-11% brackets guided revenue growth with modest residual margin leverage.", 'evidence': ['canonical_metrics.fcf_yoy', 'canonical_metrics.revenue_yoy', 'canonical_metrics.operating_margin_yoy_bps', 'canonical_metrics.fcf_margin__current_annual', 'canonical_metrics.fcf_margin__prior_annual', 'canonical_metrics.total_debt__current_quarter', 'canonical_metrics.interest_expense__current_annual', 'dcf_engine.assumptions.g_high']}, {'parameter': 'high_growth_years', 'argued_range': [3, 5], 'archetype_band': [5, 10], 'reasoning': 'Five years of unfaded high growth is hard to defend when the growth engine is decelerating and the near-term evidence is soft: FY27 revenue guidance missed consensus, Q2 guidance was characterized as weak, and billings growth averaged ~11.3% and was described as underwhelming. Agentforce plus Data 360 at $2.9B is only ~7% of the $41.5B base and cannot arrest deceleration inside the explicit window. A 3-5 year high-growth stage with a longer fade is the more honest shape.', 'evidence': ['canonical_metrics.revenue_yoy', 'canonical_metrics.revenue__current_annual', 'canonical_metrics.fcf_yoy', 'dcf_engine.assumptions.high_growth_years']}, {'parameter': 'fade_years', 'argued_range': [5, 8], 'archetype_band': [3, 7], 'reasoning': 'A 5-year fade is reasonable for a business with high switching costs, 77.7% gross margin and deferred-revenue-funded negative working capital; extending toward 8 years is arguably fairer if the high-growth stage is shortened, since the platform should decay gradually rather than cliff to terminal. No basis to argue the default is wrong.', 'evidence': ['canonical_metrics.gross_margin__current_annual', 'balance_sheet.current_quarter.derived.working_capital', 'dcf_engine.assumptions.fade_years']}]`
- Clamp warnings: `["base_fcf_method rejected: None is not one of ['avg_3y', 'avg_5y', 'mid_cycle', 'ttm']"]`
- method_appropriate: `True` — Multi-stage FCF DCF is appropriate for an asset-light, subscription-revenue business with 34.7% FCF margin and 1.4% capex intensity; the caveats are SBC (untagged, FCF/NI of 1.93x) and the fact that t
- dcf_engine method/fv: `multi_stage_fcf_dcf` / `610.915178780498`
- dcf_judgment fv/range: `None` / `{'low': 298.29480158216455, 'base': None, 'high': 364.78522722287033, 'basis': 'two argued-input range corners'}`
- comps_judgment present: **True** primary_multiple=`forward_pe`
- peer_changes proposed: `[{'ticker': 'SNOW', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'NOW', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'ADBE', 'action': 'include', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'ORCL', 'action': 'include', 'has_evidence': True, 'has_reasoning': True}]`
- justified_multiple: `{'metric': 'forward_pe', 'argued_range': [12.5, 15.5], 'has_evidence': True, 'evidence': ['revenue_yoy', 'operating_margin__current_annual', 'operating_margin_yoy_bps', 'gross_margin__current_annual', 'gross_margin_yoy_bps', 'net_income_yoy', 'operating_income_yoy', 'fcf__current_annual', 'fcf_margin__current_annual', 'fcf_yoy', 'capex_pct_revenue__current_annual', 'operating_margin__current_quarter', 'total_debt__current_quarter', 'total_debt__current_annual', 'debt_to_equity__current_quarter', 'debt_to_equity__current_annual', 'net_cash_ex_st_investments__current_quarter', 'net_cash_ex_st_investments__prior_annual', 'interest_expense__current_annual', 'operating_income__current_annual', 'fcf_conversion__current_annual', 'eps_diluted__current_annual', 'goodwill_pct_assets__current_quarter', 'stockholders_equity__current_quarter', 'goodwill_increment_pct_assets__current_annual', 'receivables_yoy', 'shares_diluted__current_quarter']}`

### JPM
- DCF critique parseable: **True**
- Relative critique parseable: **True**
- DCF args proposed / accepted / rejected: **6 / 4 / 2**
- Proposed: `['wacc', 'g_terminal', 'g_high', 'high_growth_years', 'fade_years', 'base_fcf_method']`
- Accepted: `['wacc', 'g_terminal', 'g_high', 'fade_years']`
- Rejected: `['high_growth_years', 'base_fcf_method']`
- Band dissents (n=1): `[{'parameter': 'g_terminal', 'argued_range': [0.025, 0.035], 'archetype_band': [0.01, 0.03], 'reasoning': 'Terminal book-value growth for a bank should approximate sustainable growth = ROE x retention. FY2025 retention was only ~15.5% (total payout 84.5% of net income), implying ~2.4% internally funded book growth, while observed equity growth was 5.1% including AOCI. A 2.5-4% terminal band brackets both the retention math and nominal GDP; anything above ~4% would require either a permanent cut in the ~$48B/yr capital return pace or ROE sustained above the historical 15-16%.', 'evidence': ['cash_flow.current_annual.derived.payout_ratio_total_pct', 'cash_flow.current_annual.derived.note', 'canonical_metrics.roe__current_annual', 'balance_sheet.annual_series_note', 'canonical_metrics.stockholders_equity__current_annual']}]`
- Clamp warnings: `['g_terminal clamped from 0.04 to 0.035 within [0, 0.035]', 'high_growth_years rejected: evidence list is empty or unresolvable; reverted to engine default None', "base_fcf_method rejected: None is not one of ['avg_3y', 'avg_5y', 'mid_cycle', 'ttm']"]`
- method_appropriate: `True` — JPM is a deposit-funded universal bank with negative reported operating cash flow driven by balance-sheet growth and no tagged capex or FCF, so an FCF DCF is not constructible; excess return on equity
- dcf_engine method/fv: `excess_return_on_equity` / `216.83180088938414`
- dcf_judgment fv/range: `216.83180088938414` / `{'low': 184.3070307559765, 'base': 216.83180088938414, 'high': 249.35657102279174, 'basis': '±15% band on residual-income base (not a full stress test)'}`
- comps_judgment present: **True** primary_multiple=`trailing_pe`
- peer_changes proposed: `[{'ticker': 'USB', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'PNC', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}]`
- justified_multiple: `{'metric': 'trailing_pe', 'argued_range': [15.0, 17.0], 'has_evidence': True, 'evidence': ['roe__current_annual', 'net_margin__current_annual', 'operating_margin__current_annual', 'operating_margin_yoy_bps', 'net_income_yoy', 'operating_income_yoy', 'revenue_yoy', 'share_count_change_pct__current_annual_vs_prior_annual', 'eps_diluted__current_annual', 'eps_diluted__prior_annual', 'price_to_book', 'buyback_spend__current_annual', 'dividends_paid__current_annual', 'debt_to_equity__current_annual', 'pct_below_52w_high', 'trailing_pe']}`

## Interpretation guide

- **C9 flips on all three** are expected plumbing, not quality.
- **Quality signal** = excl-C9 delta, especially C3/C7/C11 on CRM and method choice on JPM.
- **JPM** has no exemplar and is bank_lender — the honest transfer test.
- If most argued params are rejected for missing evidence, the prompt needs work regardless of score movement.
