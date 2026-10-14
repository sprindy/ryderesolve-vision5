from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid', strict=True)

class Claim(StrictModel):
    claim_id: str | None = None
    kind: Literal['driver_present','wait_minutes','contact_attempts','rider_responses','early_arrival_minutes','rider_presence_unverified','rider_allegation','policy_wait_minutes','policy_fee_sgd','policy_conflict','trip_completed','pickup_location_conflict','gps_route_verified','route_recommended','selected_eta_minutes','shortest_route_eta_minutes','quoted_fare_sgd','charged_fare_sgd','fare_unchanged','rider_route_optional','pickup_changed_verified','fare_breakdown_reconciled','surge_multiplier','promo_discount_sgd']
    value: bool | int | float | str
    evidence_ids: list[str] = Field(min_length=1)
    policy_ids: list[str] = []

class Argument(StrictModel):
    role: Literal['rider','driver']
    position: Literal['refund_requested','charge_upheld','insufficient_evidence','accept_charge']
    claims: list[Claim] = Field(min_length=1)
    rebuttal_claim_ids: list[str] = []
    summary: str = Field(default='',max_length=1500)

class Verdict(StrictModel):
    liability: Literal['charge_upheld','refund','undetermined']
    reason_codes: list[Literal['DRIVER_PRESENT','WAIT_THRESHOLD_MET','CONTACT_ATTEMPTED','INSUFFICIENT_EVIDENCE','POLICY_UNCERTAIN','THRESHOLD_NOT_MET','GPS_EFFICIENT_ROUTE','FIXED_FARE_UNCHANGED','RIDER_ROUTE_OPTIONAL','EXCESS_FIXED_FARE','EVIDENCE_INTEGRITY','DRIVER_NOT_AT_PICKUP']]=Field(min_length=1)
    evidence_ids: list[str]=Field(min_length=1)
    policy_ids: list[str]=Field(min_length=1)
    reasoning_summary: str = Field(default='',max_length=2000)
    rider_explanation: str = Field(default='',max_length=1200)
    driver_explanation: str = Field(default='',max_length=1200)
    precedent_alignment: Literal['FOLLOWED','DISTINGUISHED','NO_PRECEDENT'] = 'NO_PRECEDENT'
    distinguishing_reason: str = Field(default='',max_length=1200)

class ChallengeRequest(StrictModel):
    actor: Literal['rider','driver']
    ground: Literal['new_evidence','factual_error','policy_error','disagreement']
    statement: str = Field(min_length=1,max_length=2000)
    evidence_ids: list[str] = []
    policy_ids: list[str] = []
    evidence: str = Field(default='',max_length=2000)
    artifact_ids: list[str] = Field(default_factory=list,max_length=10)

class EvidenceUpload(StrictModel):
    actor: Literal['rider','driver']
    filename: str = Field(min_length=1,max_length=240)
    payload: dict

class HumanReview(StrictModel):
    liability: Literal['charge_upheld','refund','undetermined']
    rationale: str = Field(min_length=10,max_length=2000)
    evidence_ids: list[str] = Field(min_length=1,max_length=100)
    policy_refs: list[str] = Field(min_length=1,max_length=20)
    feedback_eligible: bool = False

class CaseRequest(StrictModel):
    category: Literal['no_show','long_route','cancellation','waiting_fee']
    title: str = Field(min_length=3,max_length=120)
    statement: str = Field(min_length=10,max_length=2000)
    actor: Literal['rider','driver'] = 'rider'
    official_dispute_id: Literal['DISP-002'] | None = None
    policy_scope: Literal['sample','production'] = 'production'
    trip_id: str | None = Field(default=None,max_length=80)
