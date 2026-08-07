from pydantic import BaseModel


class MonthlyFeeResponse(BaseModel):
  year: int
  month: int
  label: str
  amount: float
  is_current_month: bool


class DashboardSummaryMetrics(BaseModel):
  processed_volume_current_month: float
  processed_transactions_current_month: int
  active_clients: int
  fees_earned_current_month: float
  available_fees: float


class DashboardFeesResponse(BaseModel):
  current_month: float
  previous_month: float
  current_year: float
  previous_year_same_period: float
  last_12_months: list[MonthlyFeeResponse]


class DashboardReconciliationResponse(BaseModel):
  period: str
  total_transactions: int
  reconciled_transactions: int
  pending_transactions: int
  failed_transactions: int


class DashboardResponse(BaseModel):
  summary: DashboardSummaryMetrics
  fees: DashboardFeesResponse
  reconciliation: DashboardReconciliationResponse
