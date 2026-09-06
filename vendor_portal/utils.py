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