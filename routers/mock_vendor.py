"""Mock vendor-lookup endpoint — THROWAWAY TEST DATA, not a real MIS integration.

Powers the "Justdial Vendor Appointment Scheduling" workflow bot's
`fn-vendor-lookup` function node (see backend/seed_justdial_appointment_workflow_bot.py)
so the bot's {{mis.business_name}}-style tokens resolve to something real
during testing, instead of speaking literal unresolved placeholders.

Swap this out for a real MIS/CRM vendor-lookup API before going live — this
endpoint always returns the same hardcoded sample vendor, ignoring any query
params.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

_SAMPLE_VENDOR = {
    "business_name": "Sunrise Electronics",
    "owner_name": "Rajesh Kumar",
    "business_category": "electronics store",
    "category_searches": "40",
    "competitor_name_1": "Bright Electricals",
    "competitor_name_2": "City Electronics",
}


@router.get("/api/mock/vendor-lookup")
async def mock_vendor_lookup(lead_id: str = "", mobile: str = "") -> dict:
    """Returns a fixed sample vendor record regardless of lead_id/mobile —
    test/demo data only. `lead_id`/`mobile` are accepted (unused) so this has
    the same call shape a real lookup endpoint would."""
    return _SAMPLE_VENDOR
