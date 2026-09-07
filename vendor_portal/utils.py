# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt
import frappe
from frappe.utils import cint, flt

"""Shared helpers for the vendor portal.

The rating conversions here exist because two scales are in play and only one
of them is a choice. Frappe's Rating fieldtype stores a fraction between 0 and
1 regardless of how many stars it draws, while every threshold, weight and
score in this app is expressed on the 1-5 scale people actually speak in.
Rather than teach each consumer about the fraction, the translation lives here
and nowhere else.
"""

# The scale ratings are expressed in throughout the portal.
RATING_SCALE_MAX = 5.0

FILLED_STAR = "★"
EMPTY_STAR = "☆"

def rating_field_to_scale(value: float | None) -> float:
	"""Convert a stored Rating field value to the 1-5 scale.

	Args:
		value: The 0-1 fraction held by a Rating field, or None.

	Returns:
		The equivalent score between 0 and 5. An unset field returns 0.0,
		which callers should treat as "no rating", not as a bad one.
	"""
	return (value or 0) * RATING_SCALE_MAX


def scale_to_rating_field(score: float | None) -> float:
	"""Convert a 1-5 score to the fraction a Rating field stores.

	Args:
		score: A score on the 1-5 scale, or None.

	Returns:
		The equivalent 0-1 fraction, clamped so a miscalculated score cannot
		write a value the Rating widget refuses to render.
	"""
	fraction = (score or 0) / RATING_SCALE_MAX

	return max(0.0, min(1.0, fraction))


def star_rating(value: float | None) -> str:
	"""Render a stored rating as five star characters.

	Takes the 0-1 fraction a Rating field holds rather than a 1-5 score,
	because its callers are print formats reading a Rating field directly —
	`{{ doc.custom_vendor_rating | star_rating }}` should work without the
	template author converting first. A score already on the 1-5 scale can be
	fed through scale_to_rating_field first.

	Deliberately not inferring the scale from magnitude: a value of 1.0 is
	ambiguous between a full five stars and a single star, and guessing wrong
	misrepresents the worst vendors as the best.

	Args:
		value: The 0-1 fraction from a Rating field, or None.

	Returns:
		Five characters, filled stars followed by empty ones. An unset or zero
		rating renders five empty stars rather than nothing, so a print format
		keeps its layout whether or not the vendor has been rated.
	"""
	score = rating_field_to_scale(value)

	# Clamped so a value outside 0-1 — from a bad import or a hand-edited
	# field — still renders exactly five characters and does not break the
	# surrounding layout.
	filled = max(0, min(int(round(score)), int(RATING_SCALE_MAX)))

	return FILLED_STAR * filled + EMPTY_STAR * (int(RATING_SCALE_MAX) - filled)


# The rating types the weighted average is built from, paired with the
# settings field holding each one's weight.
RATING_TYPE_WEIGHTS = {
	"Delivery": "rating_weight_delivery",
	"Quality": "rating_weight_quality",
	"Pricing": "rating_weight_pricing",
	"Communication": "rating_weight_communication",
}


def recalculate_vendor_rating(supplier: str) -> dict:
	"""Recompute a supplier's overall rating from its rating log.

	Always computed from the log rather than adjusted from the previous value.
	Ratings are deleted when a purchase order or receipt is cancelled, so an
	incremental update would drift away from the truth with no way back.
	Recomputing is idempotent, which is what lets the daily job and the
	backfill patch re-run safely.

	Weights come from Vendor Portal Settings and are renormalised across the
	rating types that actually have entries. A vendor rated only on delivery
	and pricing should not be dragged toward zero by two dimensions nobody has
	scored — those are unmeasured, not bad. The consequence is that a single
	five-star delivery reads the same as five stars across all four types;
	total_rating_count is what tells a reader how much weight to give it.

	Args:
		supplier: Name of the Supplier to recalculate.

	Returns:
		A dict with the rating on the 1-5 scale, the fraction written to the
		Rating field, and the number of log entries behind it.
	"""
	rows = frappe.db.sql(
		"""
		SELECT rating_type, AVG(score) AS average_score, COUNT(*) AS rating_count
		FROM `tabVendor Rating Log`
		WHERE supplier = %(supplier)s
		GROUP BY rating_type
		""",
		{"supplier": supplier},
		as_dict=True,
	)

	total_count = sum(int(row.rating_count or 0) for row in rows)

	if not total_count:
		# Reset rather than leave a stale score behind: a supplier whose
		# ratings were all withdrawn is unrated, not still rated.
		frappe.db.set_value(
			"Supplier",
			supplier,
			{"custom_vendor_rating": 0, "custom_total_rating_count": 0},
			update_modified=False,
		)

		return {"rating": 0.0, "rating_field_value": 0.0, "rating_count": 0}

	settings = frappe.get_single("Vendor Portal Settings")

	weighted_total = 0.0
	weight_sum = 0.0

	for row in rows:
		weight_field = RATING_TYPE_WEIGHTS.get(row.rating_type)

		if not weight_field:
			continue

		weight = flt(settings.get(weight_field))

		if not weight:
			continue

		weighted_total += flt(row.average_score) * weight
		weight_sum += weight

	# Dividing by the weights actually used, not by 1.0, is what renormalises
	# across the types present.
	rating = weighted_total / weight_sum if weight_sum else 0.0

	rating_field_value = scale_to_rating_field(rating)

	# db.set_value rather than a full save: these are derived read-only fields,
	# and saving would run ERPNext's Supplier validation and on_update hooks on
	# every single rating submitted.
	frappe.db.set_value(
		"Supplier",
		supplier,
		{
			"custom_vendor_rating": rating_field_value,
			"custom_total_rating_count": total_count,
		},
		update_modified=False,
	)

	return {
		"rating": rating,
		"rating_field_value": rating_field_value,
		"rating_count": total_count,
	}

