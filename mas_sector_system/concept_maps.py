"""XBRL concept maps by business archetype (US 10-K / 10-Q filers).

Commercial-company tags are the ``general`` default. Hard archetypes
(bank, insurance, equity REIT) add/override concepts so extraction is not
empty on those filers.

Canonical keys used by extractors:
  income / balance / cashflow maps → line labels in statement dicts.
"""

from __future__ import annotations

from typing import Any

# ── General commercial operating company (existing behavior) ─────────────────

GENERAL_INCOME: dict[str, list[str]] = {
    "Revenues": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "TurnoverRevenue",
    ],
    "CostOfRevenue": [
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
        "CostOfServices",
    ],
    "GrossProfit": ["GrossProfit"],
    "ResearchAndDevelopmentExpense": [
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    ],
    "SellingGeneralAndAdministrativeExpense": [
        "SellingGeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "OperatingExpenses": ["OperatingExpenses", "CostsAndExpenses"],
    "OperatingIncomeLoss": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "InterestExpense": [
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
    ],
    "IncomeTaxExpenseBenefit": [
        "IncomeTaxExpenseBenefit",
        "IncomeTaxExpenseBenefitContinuingOperations",
    ],
    "NetIncomeLoss": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "EarningsPerShareBasic": ["EarningsPerShareBasic"],
    "EarningsPerShareDiluted": ["EarningsPerShareDiluted"],
    "WeightedAverageNumberOfSharesOutstandingBasic": [
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    ],
    "WeightedAverageNumberOfDilutedSharesOutstanding": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
}

GENERAL_BALANCE: dict[str, list[str]] = {
    "CashAndCashEquivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
        "Cash",
    ],
    "ShortTermInvestments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
    ],
    "AccountsReceivable": [
        "AccountsReceivableNetCurrent",
        "AccountsReceivableNet",
        "ReceivablesNetCurrent",
    ],
    "Inventory": ["InventoryNet", "InventoryFinishedGoodsNetOfReserves"],
    "TotalCurrentAssets": ["AssetsCurrent"],
    "PropertyPlantAndEquipment": [
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    ],
    "Goodwill": ["Goodwill"],
    "IntangibleAssets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    "TotalAssets": ["Assets"],
    "AccountsPayable": [
        "AccountsPayableCurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
    ],
    "ShortTermDebt": [
        "ShortTermBorrowings",
        "LongTermDebtCurrent",
        "DebtCurrent",
        "CommercialPaper",
    ],
    "TotalCurrentLiabilities": ["LiabilitiesCurrent"],
    "LongTermDebt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
    ],
    "TotalLiabilities": ["Liabilities", "LiabilitiesAndStockholdersEquity"],
    "StockholdersEquity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "PartnersCapital",
    ],
    "SharesOutstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
}

GENERAL_CASHFLOW: dict[str, list[str]] = {
    "NetCashFromOperatingActivities": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "CapitalExpenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "CapitalExpendituresIncurredButNotYetPaid",
    ],
    "NetCashFromInvestingActivities": [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ],
    "DividendsPaid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsOfOrdinaryDividends",
    ],
    "StockRepurchases": [
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ],
    "DebtIssuance": [
        "ProceedsFromIssuanceOfLongTermDebt",
        "ProceedsFromDebtNetOfIssuanceCosts",
        "ProceedsFromIssuanceOfDebt",
    ],
    "DebtRepayment": [
        "RepaymentsOfLongTermDebt",
        "RepaymentsOfDebt",
        "RepaymentsOfLongTermDebtAndCapitalSecurities",
    ],
    "NetCashFromFinancingActivities": [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ],
}

# ── Bank / lender ────────────────────────────────────────────────────────────

BANK_INCOME: dict[str, list[str]] = {
    **GENERAL_INCOME,
    # Primary revenue lines for banks
    "InterestIncome": [
        "InterestAndDividendIncomeOperating",
        "InterestAndFeeIncomeLoansAndLeases",
        "InterestIncomeOperating",
        "InterestAndDividendIncomeOperatingAfterProvisionForLoanLoss",
    ],
    "InterestExpenseBank": [  # operating cost for banks, not corporate leverage noise
        "InterestExpense",
        "InterestExpenseDeposits",
        "InterestExpenseDebt",
    ],
    "NetInterestIncome": [
        "InterestIncomeExpenseNet",
        "InterestIncomeExpenseAfterProvisionForLoanLoss",
    ],
    "NoninterestIncome": [
        "NoninterestIncome",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ],
    "ProvisionForCreditLosses": [
        "ProvisionForLoanLeaseAndOtherLosses",
        "ProvisionForCreditLosses",
        "ProvisionForLoanAndLeaseLosses",
    ],
    "NoninterestExpense": [
        "NoninterestExpense",
        "OperatingExpenses",
    ],
    # Override Revenues to prefer interest+noninterest composites (tried first
    # as tags; derived composite also computed post-extract).
    "Revenues": [
        "InterestAndDividendIncomeOperating",
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ],
}

BANK_BALANCE: dict[str, list[str]] = {
    **GENERAL_BALANCE,
    "LoansNet": [
        "LoansAndLeasesReceivableNetReportedAmount",
        "NotesReceivableNet",
        "LoansAndLeasesReceivableGrossCarryingAmount",
        "FinancingReceivableExcludingAccruedInterestAfterAllowanceForCreditLoss",
    ],
    "Deposits": [
        "Deposits",
        "DepositLiabilities",
        "InterestBearingDepositLiabilities",
    ],
    "AllowanceForCreditLosses": [
        "AllowanceForLoanAndLeaseLosses",
        "FinancingReceivableAllowanceForCreditLosses",
    ],
    "InvestmentSecurities": [
        "DebtSecuritiesAvailableForSaleExcludingAccruedInterest",
        "AvailableForSaleSecuritiesDebtSecurities",
        "MarketableSecurities",
    ],
    # Prefer bank-style debt tags but keep general
    "ShortTermDebt": [
        "ShortTermBorrowings",
        "FederalFundsPurchasedAndSecuritiesSoldUnderAgreementsToRepurchase",
        "LongTermDebtCurrent",
        "DebtCurrent",
        "CommercialPaper",
    ],
}

BANK_CASHFLOW: dict[str, list[str]] = dict(GENERAL_CASHFLOW)

# ── Insurance ────────────────────────────────────────────────────────────────

INSURANCE_INCOME: dict[str, list[str]] = {
    **GENERAL_INCOME,
    "PremiumsEarned": [
        "PremiumsEarnedNet",
        "PremiumsWrittenNet",
        "InsuranceCommissionsAndFees",
    ],
    "NetInvestmentIncome": [
        "NetInvestmentIncome",
        "InvestmentIncomeNet",
        "InterestAndDividendIncomeOperating",
    ],
    "PolicyholderBenefits": [
        "PolicyholderBenefitsAndClaimsIncurredNet",
        "BenefitsLossesAndExpenses",
        "IncurredClaims",
    ],
    "UnderwritingExpense": [
        "DeferredPolicyAcquisitionCostAmortizationExpense",
        "AmortizationOfDeferredPolicyAcquisitionCosts",
        "SellingGeneralAndAdministrativeExpense",
    ],
    "Revenues": [
        "PremiumsEarnedNet",
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    ],
}

INSURANCE_BALANCE: dict[str, list[str]] = {
    **GENERAL_BALANCE,
    "InvestmentsInsurance": [
        "DebtSecuritiesAvailableForSaleExcludingAccruedInterest",
        "AvailableForSaleSecuritiesDebtSecurities",
        "MarketableSecurities",
        "Investments",
    ],
    "PolicyReserves": [
        "LiabilityForFuturePolicyBenefits",
        "LiabilityForUnpaidClaimsAndClaimsAdjustmentExpense",
        "UnearnedPremiums",
        "PolicyholderContractDeposits",
    ],
    "UnearnedPremiums": ["UnearnedPremiums"],
}

INSURANCE_CASHFLOW: dict[str, list[str]] = dict(GENERAL_CASHFLOW)

# ── Equity REIT ──────────────────────────────────────────────────────────────
# FFO is non-GAAP — derived post-extract from NI + real-estate D&A − gains.

REIT_INCOME: dict[str, list[str]] = {
    **GENERAL_INCOME,
    "RentalRevenue": [
        "OperatingLeaseLeaseIncome",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RealEstateRevenueNet",
    ],
    "DepreciationRealEstate": [
        "Depreciation",
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ],
    "GainOnSaleOfRealEstate": [
        "GainsLossesOnSalesOfInvestmentRealEstate",
        "GainLossOnSaleOfProperty",
        "GainsLossesOnSalesOfOtherAssets",
    ],
    "Revenues": [
        "OperatingLeaseLeaseIncome",
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RealEstateRevenueNet",
    ],
}

REIT_BALANCE: dict[str, list[str]] = {
    **GENERAL_BALANCE,
    "RealEstateInvestments": [
        "RealEstateInvestmentPropertyNet",
        "RealEstateInvestments",
        "InvestmentInRealEstate",
        "PropertyPlantAndEquipmentNet",
    ],
}

REIT_CASHFLOW: dict[str, list[str]] = {
    **GENERAL_CASHFLOW,
    "DepreciationRealEstateCF": [
        "Depreciation",
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ],
}

# ── Mortgage REIT ────────────────────────────────────────────────────────────

MREIT_INCOME: dict[str, list[str]] = {
    **GENERAL_INCOME,
    "InterestIncome": [
        "InterestAndDividendIncomeOperating",
        "InterestIncomeOperating",
        "InterestAndFeeIncomeLoansAndLeases",
    ],
    "InterestExpenseBank": [
        "InterestExpense",
        "InterestExpenseDebt",
    ],
    "NetInterestIncome": [
        "InterestIncomeExpenseNet",
    ],
    "Revenues": [
        "InterestAndDividendIncomeOperating",
        "Revenues",
    ],
}

MREIT_BALANCE: dict[str, list[str]] = {
    **GENERAL_BALANCE,
    "MortgageBackedSecurities": [
        "MortgageBackedSecuritiesAvailableForSaleAtFairValue",
        "AvailableForSaleSecuritiesDebtSecurities",
        "DebtSecuritiesAvailableForSaleExcludingAccruedInterest",
        "MarketableSecurities",
    ],
    "RepurchaseAgreements": [
        "SecuritiesSoldUnderAgreementsToRepurchase",
        "FederalFundsPurchasedAndSecuritiesSoldUnderAgreementsToRepurchase",
        "ShortTermBorrowings",
    ],
}

MREIT_CASHFLOW: dict[str, list[str]] = dict(GENERAL_CASHFLOW)

# ── Registry ─────────────────────────────────────────────────────────────────

CONCEPT_MAPS: dict[str, dict[str, dict[str, list[str]]]] = {
    "general": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "bank_lender": {
        "income": BANK_INCOME,
        "balance": BANK_BALANCE,
        "cashflow": BANK_CASHFLOW,
    },
    "insurance": {
        "income": INSURANCE_INCOME,
        "balance": INSURANCE_BALANCE,
        "cashflow": INSURANCE_CASHFLOW,
    },
    "equity_reit": {
        "income": REIT_INCOME,
        "balance": REIT_BALANCE,
        "cashflow": REIT_CASHFLOW,
    },
    "reit_real_estate": {  # alias
        "income": REIT_INCOME,
        "balance": REIT_BALANCE,
        "cashflow": REIT_CASHFLOW,
    },
    "mortgage_reit": {
        "income": MREIT_INCOME,
        "balance": MREIT_BALANCE,
        "cashflow": MREIT_CASHFLOW,
    },
    # Soft archetypes reuse general tags for now
    "software_saas": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "asset_heavy_industrial": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "asset_heavy": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "asset_light": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "utility": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "cyclical_commodity": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "pre_profit_growth": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "mature_dividend_payer": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "telecom": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
    "midstream": {
        "income": GENERAL_INCOME,
        "balance": GENERAL_BALANCE,
        "cashflow": GENERAL_CASHFLOW,
    },
}


def maps_for_archetype(archetype: str) -> dict[str, dict[str, list[str]]]:
    key = (archetype or "general").strip().lower()
    return CONCEPT_MAPS.get(key) or CONCEPT_MAPS["general"]


def list_hard_archetypes() -> list[str]:
    return ["bank_lender", "insurance", "equity_reit", "mortgage_reit"]
