# VAL-02 After-Baseline Comparison (NVDA / CRM / JPM)

Generated: 2026-07-30T03:04:09.571743+00:00

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
- **2 evidence_for_argued_inputs**: dcf:g_high: no resolvable evidence (tried: canonical_metrics.fcf__current_annual, canonical_metrics.fcf__prior_annual, canonical_metrics.fcf_conversion__current_annual, canonical_metrics.inventory__current_annual); dcf:g_terminal: no resolvable evidence (tried: canonical_metrics.gross_margin__current_annual, canonical_metrics.operating_margin__current_annual, canonical_metrics.capex_pct_revenue__current_annual, canonical_metrics.fcf_margin__current_annual); dcf:base_fcf_method: no resolvable evidence (tried: cash_flow_statement.current_annual.FreeCashFlow, canonical_metrics.fcf_margin__current_annual, canonical_metrics.fcf_margin__prior_annual, canonical_metrics.fcf_annualized_from_current_quarter); peer:INTC: no resolvable evidence (tried: canonical_metrics.capex_pct_revenue__current_annual, canonical_metrics.capex__current_annual); justified_multiple: no resolvable evidence (tried: canonical_metrics.revenue_yoy, canonical_metrics.net_income_yoy, canonical_metrics.operating_margin__current_annual, canonical_metrics.fcf_margin__current_annual)
- **3 no_untraceable_currency**: untraceable currency: $18B, $91B, $38T, $1T, $27.02B, $16B
- **11 no_numeric_contradiction**: contradictions: g_high: [0.35, 0.05]; fair_value: [318.63, 88.24]; base_fcf: [4.5, 58.9, 96.68]
- Focus **C3 Untraceable currency**: before=PASS (30 currency figure(s) traceable to engine blocks) → after=FAIL (untraceable currency: $18B, $91B, $38T, $1T, $27.02B, $16B)
- Focus **C7 Mixed windows**: before=PASS (windows present: 5y, yoy) → after=PASS (windows present: 1y, 3y, 5y, yoy)
- Focus **C9 Default+judgment (plumbing)**: before=FAIL (missing: dcf_judgment, comps_judgment) → after=PASS (dcf_base=True dcf_judgment=True comps_base=True comps_judgment=True comps_applicable=True)
- Focus **C11 Self-contradiction**: before=PASS (no contradictions across 5 identity metric(s)) → after=FAIL (contradictions: g_high: [0.35, 0.05]; fair_value: [318.63, 88.24]; base_fcf: [4.5, 58.9, 96.68])

### CRM

| # | Criterion | Before | After | Flip |
|---|-----------|:------:|:-----:|:----:|
| 1 | Archetype named and primary method justified | PASS | PASS | · |
| 2 | Every argued input cites ≥1 resolvable evidence field | PASS | FAIL | ↓ FAIL |
| 3 | No currency figure appears that is not traceable to an engine block | FAIL | FAIL | · |
| 4 | Terminal-value share of EV stated (DCF path) | PASS | PASS | · |
| 5 | Valuation expressed as a range, not a point | PASS | PASS | · |
| 6 | Each peer inclusion/exclusion justified individually | PASS | PASS | · |
| 7 | Comparison windows consistent and stated (no YTD vs 1-yr mixing) | FAIL | PASS | ↑ PASS |
| 8 | ≥1 risk left explicitly unresolved (no self-neutralizing close) | PASS | FAIL | ↓ FAIL |
| 9 | Both default and judgment cases present ⚠ plumbing | FAIL | PASS | ↑ PASS |
| 10 | Band dissents flagged where applicable | PASS | PASS | · |
| 11 | No internal numeric contradiction (same metric, two values) | FAIL | FAIL | · |

**After fail details:**
- **2 evidence_for_argued_inputs**: dcf:g_high: no resolvable evidence (tried: canonical_metrics.fcf__current_annual, canonical_metrics.fcf__prior_annual, income_statement.current_annual.Revenues, canonical_metrics.fcf_margin__current_annual); dcf:base_fcf_method: no resolvable evidence (tried: canonical_metrics.fcf__current_annual, canonical_metrics.fcf__prior_annual, canonical_metrics.fcf_conversion__current_annual, canonical_metrics.accounts_receivable__current_annual); dcf:high_growth_years: no resolvable evidence (tried: canonical_metrics.gross_margin__current_annual, canonical_metrics.rd_pct_revenue__current_annual, canonical_metrics.revenue_yoy); peer:SNOW: no resolvable evidence (tried: canonical_metrics.fcf_conversion__current_annual, canonical_metrics.capex_pct_revenue__current_annual, income_statement.current_annual.NetIncomeLoss, income_statement.current_annual.OperatingIncomeLoss); peer:NOW: no resolvable evidence (tried: canonical_metrics.fcf__current_annual, canonical_metrics.fcf_conversion__current_annual, income_statement.current_annual.Revenues, income_statement.current_annual.OperatingIncomeLoss); peer:ORCL: no resolvable evidence (tried: canonical_metrics.debt_to_equity__current_annual, canonical_metrics.debt_to_equity__current_quarter, canonical_metrics.buyback_spend__current_annual, canonical_metrics.buyback_spend__current_quarter); peer:ADBE: no resolvable evidence (tried: canonical_metrics.capex_pct_revenue__current_annual, canonical_metrics.fcf__current_annual, income_statement.current_annual.GrossProfit, income_statement.current_annual.Revenues)
- **3 no_untraceable_currency**: untraceable currency: $69B
- **8 unresolved_risk**: FAIL: The DCF section repeatedly reframes real risks (stale net debt, unsustainable g_high, SBC dilution, terminal value concentration) but each is 'resolved' via the judgment case or explicit numerical adjustment recommendation ('should be re-run with current-quarter net debt'), leaving no risk stated as genuinely open/unresolved — the write-up prescribes the fix rather than leaving it unsettled.
- **11 no_numeric_contradiction**: contradictions: fair_value: [610.92, 285.94]; wacc: [0.09, 0.095, 0.11]; g_high: [0.158, 0.05, 0.07, 0.1]; g_terminal: [0.03, 0.02, 0.15]; eps: [7.8, 22.6]
- Focus **C3 Untraceable currency**: before=FAIL (untraceable currency: $23B, $46.0B, $57,000, $57.94B) → after=FAIL (untraceable currency: $69B)
- Focus **C7 Mixed windows**: before=FAIL (mixed comparison windows: ytd, 1y, 5y, yoy) → after=PASS (windows present: 1y, 3y, 5y, yoy)
- Focus **C9 Default+judgment (plumbing)**: before=FAIL (missing: dcf_judgment, comps_judgment) → after=PASS (dcf_base=True dcf_judgment=True comps_base=True comps_judgment=True comps_applicable=True)
- Focus **C11 Self-contradiction**: before=FAIL (contradictions: g_high: [0.158, 0.05]; eps: [7.8, 11.7]) → after=FAIL (contradictions: fair_value: [610.92, 285.94]; wacc: [0.09, 0.095, 0.11]; g_high: [0.158, 0.05, 0.07,)

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
- DCF args proposed / accepted / rejected: **6 / 6 / 0**
- Proposed: `['wacc', 'g_high', 'g_terminal', 'high_growth_years', 'fade_years', 'base_fcf_method']`
- Accepted: `['wacc', 'g_high', 'g_terminal', 'high_growth_years', 'fade_years', 'base_fcf_method']`
- Rejected: `[]`
- Band dissents (n=3): `[{'parameter': 'wacc', 'argued_range': [0.115, 0.135], 'archetype_band': [0.08, 0.12], 'reasoning': 'A 10.0% WACC understates the specific, named risks in this underwrite. (1) Export-control binarity: NVDA shipped zero Hopper to China in Q1 FY2027 versus $4.6B a year earlier — a single jurisdiction was switched off by policy with no warning, which is a permanent non-diversifiable hazard rather than a one-time event. (2) Customer-quality mix shift: hyperscaler revenue grew only ~12% while total grew ~85%, so the marginal buyer is increasingly the sovereign/neocloud/enterprise tier that funds capex with external capital, and the macro assessment identifies rising AI-datacenter financing costs as the live transmission channel. (3) The macro regime assessment names the 10-year yield above ~4.75% as the dominant valuation variable for this asset against a $38T debt / 123% debt-to-GDP fiscal backdrop with term-premium pressure. Note the balance sheet argues the other way — debt/equity of 0.043 at Q1 FY2027 and a net-cash position mean financial risk is nil — which is why we cap the argued range at 13.5% rather than higher.', 'evidence': ['macro_regime_assessment', 'business_overview', 'canonical_metrics.debt_to_equity__current_quarter', 'canonical_metrics.enterprise_value_ex_st']}, {'parameter': 'g_high', 'argued_range': [0.18, 0.28], 'archetype_band': [0.02, 0.2], 'reasoning': "35% FCF growth held flat for five years compounds base FCF of $96.68B to $433.50B by Y5 — roughly 4.5x — and the engine's own warning concedes the cap may still be optimistic. Three pieces of company evidence argue the FCF ramp is already decelerating relative to revenue: FCF grew 58.9% versus revenue growth of 65.5%, FCF conversion of net income slipped from 83.5% to 80.5%, and the working-capital drag is real (accounts receivable of $38.47B, up 66.8%, and inventory of $21.40B, up 112.3% against 65.5% revenue growth, with ~115 days of inventory at Q1). Gross margin also contracted 392bp in FY2026 as cost of revenue grew 91.4% versus 65.5% revenue growth, so incremental FCF dollars are being earned at a lower rate than the FY2025 corporate level. An 18-28% five-year high-growth rate still embeds an extraordinary AI buildout — the sector-cycle tailwind and the ~$1T pipeline framing are real — without assuming the peak incremental economics of FY2025 persist for half a decade.", 'evidence': ['canonical_metrics.fcf__current_annual', 'canonical_metrics.fcf__prior_annual', 'canonical_metrics.fcf_conversion__current_annual', 'canonical_metrics.inventory__current_annual', 'canonical_metrics.gross_margin_yoy_bps', 'income_statement.current_annual.CostOfRevenue']}, {'parameter': 'fade_years', 'argued_range': [6, 8], 'archetype_band': [3, 7], 'reasoning': 'If the high-growth stage is shortened, the fade should lengthen rather than the model snapping to terminal. A longer, gentler glide path is more faithful to a franchise with a genuine moat — full-stack hardware plus Mellanox-derived networking plus software — that is likely to grow above GDP for a long time even after the AI buildout normalizes. Six to eight fade years also reduces the share of value sitting in the terminal block, which is the correct response to the terminal-value-dominance red flag flagged in the doctrine.', 'evidence': ['business_overview', 'canonical_metrics.gross_margin__current_annual', 'canonical_metrics.rd_pct_revenue__current_annual']}]`
- Clamp warnings: `[]`
- method_appropriate: `True` — NVDA is a fabless, asset-light, cash-generative operating company with FY2026 FCF of $96.68B on 2.8% capex intensity and essentially no leverage, so a multi-stage FCF DCF is the right primary frame. T
- dcf_engine method/fv: `multi_stage_fcf_dcf` / `318.62611476243546`
- dcf_judgment fv/range: `None` / `{'low': 88.24485737033585, 'base': 117.34503593100843, 'high': 146.445214491681, 'basis': 'midpoint of two argued-input range corners'}`
- comps_judgment present: **True** primary_multiple=`forward_pe`
- peer_changes proposed: `[{'ticker': 'INTC', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'AMD', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'AAPL', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'TSM', 'action': 'include', 'has_evidence': True, 'has_reasoning': True}]`
- justified_multiple: `{'metric': 'forward_pe', 'argued_range': [22.0, 28.0], 'has_evidence': True, 'evidence': ['canonical_metrics.revenue_yoy', 'canonical_metrics.net_income_yoy', 'canonical_metrics.operating_margin__current_annual', 'canonical_metrics.fcf_margin__current_annual', 'canonical_metrics.fcf__current_annual', 'canonical_metrics.capex_pct_revenue__current_annual', 'canonical_metrics.debt_to_equity__current_quarter', 'canonical_metrics.net_cash_ex_st_investments__current_quarter', 'canonical_metrics.gross_margin_yoy_bps', 'canonical_metrics.inventory_yoy', 'canonical_metrics.receivables_yoy', 'canonical_metrics.goodwill_increment__current_annual_vs_prior_annual', 'canonical_metrics.goodwill_pct_assets__current_annual', 'canonical_metrics.buyback_dollars_per_pct_point__current_annual_vs_prior_annual', 'canonical_metrics.buyback_spend__current_annual', 'income_statement.current_annual.CostOfRevenue', 'income_statement.current_annual.OperatingIncomeLoss']}`

### CRM
- DCF critique parseable: **True**
- Relative critique parseable: **True**
- DCF args proposed / accepted / rejected: **6 / 6 / 0**
- Proposed: `['g_high', 'wacc', 'g_terminal', 'base_fcf_method', 'high_growth_years', 'fade_years']`
- Accepted: `['g_high', 'wacc', 'g_terminal', 'base_fcf_method', 'high_growth_years', 'fade_years']`
- Rejected: `[]`
- Band dissents (n=2): `[{'parameter': 'g_high', 'argued_range': [0.07, 0.1], 'archetype_band': [0.1, 0.3], 'reasoning': 'The engine used 15.8% because that is the single-year FCF growth print, but FCF growth of that magnitude came from margin expansion (operating margin +105bps, gross margin +48bps) and working-capital/capex leverage, not from volume. Revenue grew 9.6% and the Q1 annualized run-rate of $44.53B against $41.52B FY implies the same high-single-digit trajectory. Margin-driven FCF growth cannot compound for five years at 15.8% off a 34.7% FCF margin base without implying a >50% FCF margin by Y5; the durable rate is the revenue rate, modestly aided by residual mix, i.e. 7-10%.', 'evidence': ['canonical_metrics.fcf__current_annual', 'canonical_metrics.fcf__prior_annual', 'income_statement.current_annual.Revenues', 'canonical_metrics.fcf_margin__current_annual', 'canonical_metrics.capex_pct_revenue__current_annual']}, {'parameter': 'high_growth_years', 'argued_range': [3, 5], 'archetype_band': [5, 10], 'reasoning': "A five-year explicit high-growth stage is reasonable for a franchise with 77.7% gross margin and stable 14.4%-of-revenue R&D reinvestment, but the case for the full five years weakens if growth is set at the revenue rate rather than the margin-inflated FCF rate. Three to five years is the acceptable band; the engine's 5 sits at the permissive end rather than being wrong.", 'evidence': ['canonical_metrics.gross_margin__current_annual', 'canonical_metrics.rd_pct_revenue__current_annual', 'canonical_metrics.revenue_yoy']}]`
- Clamp warnings: `[]`
- method_appropriate: `True` — Multi-stage FCF DCF is the right frame for an asset-light subscription business with 34.7% FCF margin, 1.4%-of-revenue capex and 193% FCF/NI conversion. The caveats are inputs, not method: SBC is unta
- dcf_engine method/fv: `multi_stage_fcf_dcf` / `610.915178780498`
- dcf_judgment fv/range: `None` / `{'low': 285.93748718952133, 'base': 303.9823785956023, 'high': 322.0272700016833, 'basis': 'midpoint of two argued-input range corners'}`
- comps_judgment present: **True** primary_multiple=`forward_pe`
- peer_changes proposed: `[{'ticker': 'SNOW', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'NOW', 'action': 'exclude', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'ORCL', 'action': 'include', 'has_evidence': True, 'has_reasoning': True}, {'ticker': 'ADBE', 'action': 'include', 'has_evidence': True, 'has_reasoning': True}]`
- justified_multiple: `{'metric': 'forward_pe', 'argued_range': [13.5, 17.0], 'has_evidence': True, 'evidence': ['canonical_metrics.fcf_margin__current_annual', 'canonical_metrics.fcf_conversion__current_annual', 'canonical_metrics.fcf__current_annual', 'canonical_metrics.capex_pct_revenue__current_annual', 'canonical_metrics.capex__current_annual', 'canonical_metrics.debt_to_equity__current_quarter', 'canonical_metrics.debt_to_equity__current_annual', 'canonical_metrics.enterprise_value_ex_st', 'income_statement.current_annual.OperatingIncomeLoss', 'income_statement.current_annual.InterestExpense', 'balance_sheet.current_annual.Goodwill', 'balance_sheet.current_annual.TotalAssets', 'macro_regime_assessment', 'capital_allocation_assessment', 'management_assessment']}`

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
