# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

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

