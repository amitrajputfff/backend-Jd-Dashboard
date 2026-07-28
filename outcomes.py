"""Canonical call-outcome list — mirrors
voicebot_nodcode_platform/callback_worker/analysis.py's DISPOSITION_MAP, the
single source of truth for what `analysis.call_outcome` can actually be
(enforced there by `_VALID_OUTCOMES` coercion). Duplicated here rather than
imported because backend/ and voicebot_nodcode_platform/ are separate
deployables with separate venvs (same reasoning as backend/languages.py).

Four copies of a *stale* version of this list had drifted from the real one
before this module existed: the dashboard's Outcome filter dropdown, its
badge-colour map, the [callId] detail page's identical copy, and this
backend's own OUTCOME_SUCCESS grouping — all listing values like "Callback"
and "Already Purchased" that the analyser has never produced, while missing
real ones like "Approved" and "Enriched" (which is why an Approved call
render a grey fallback badge but couldn't be selected in the filter).
"""

from __future__ import annotations

from typing import Dict, List

DISPOSITION_MAP: Dict[str, str] = {
    "Short Hangup":                      "The call ended with no product discussion — the customer said nothing at all, OR gave only a bare call-acknowledgment (e.g. hello, haan, hold on, ek second) and disconnected before any product topic was raised.",
    "Voicemail":                        "The call went to the recipient's voicemail instead of connecting directly.",
    "Wrong Number":                     "The number dialed does not belong to the intended customer.",
    "Approved":                         "The customer confirmed the product and answered ALL specification questions.",
    "Enriched":                         "The customer confirmed the product and answered at least one (but not all) specification questions with valid specific values.",
    "Interested":                       "The customer confirmed they need the product but answered ZERO specification questions with valid specific values, OR showed clear positive interest without answering any spec questions.",
    "Not Interested":                   "The customer clearly stated they are not interested or do not need the product.",
    "Could Not Confirm":                "The customer was uncertain or did not confirm whether they still need the product.",
    "Alternate Number":                 "The customer provided a different or alternate contact number.",
    "Already Spoken":                   "The customer has already discussed or interacted about the requirement with JD or the seller, OR the requirement has already been fulfilled.",
    "Will do it Myself":                "The customer still has the requirement but will source/handle it themselves without JD's help.",
    "Call Rescheduled":                 "The customer asked to call at a specific date and time.",
    "Seller Intent":                    "The caller is a seller or vendor trying to offer their own products/services — not a buyer with a requirement.",
    "Job Seeker":                       "The caller is seeking employment/a job rather than the product or service being inquired about.",
    "Abusive Lead":                     "The recipient exhibited abusive or inappropriate behavior during the call.",
    "DNC Client : Don't Call Further":  "The customer explicitly requested not to be contacted again.",
    "Other Cases":                      "The call outcome does not fit into any predefined categories.",
    "Technical Issue - Call Connected": "The call connected but was disrupted by technical issues.",
    "Language Issue":                   "Communication was not possible due to a language mismatch.",
}

VALID_OUTCOMES: List[str] = list(DISPOSITION_MAP.keys())

# Sentinel query value for "no analysis.call_outcome at all" — the dashboard's
# Outcome filter couldn't previously express this (it only ever did an exact
# match against `outcome`, and an unanalysed doc's field is empty/missing).
UNANALYSED_SENTINEL = "__unanalysed__"

# Matches voicebot_nodcode_platform/audit_outcome_drift.py's POSITIVE set —
# the previous OUTCOME_SUCCESS here used non-existent values ("Callback",
# "Already Purchased") and omitted real ones ("Approved", "Enriched").
OUTCOME_SUCCESS = {"Interested", "Approved", "Enriched"}
