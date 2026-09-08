# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Delivery observations recorded against Purchase Receipts.

Hooked through doc_events rather than by overriding the controller. A short or
late delivery does not make a Purchase Receipt invalid — it is an observation
about an event that this document happens to record. The rule is additive and
could be removed without changing what a Purchase Receipt is, which is exactly
the case doc_events serves. Compare the Purchase Order override, where a
blacklisted supplier makes the order itself invalid and the rule belongs inside
the controller.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

# Below this fraction of the ordered quantity, a delivery counts as short.
SHORT_DELIVERY_THRESHOLD = 0.90

# Days past the promised date before a delivery counts as late. Two days of
# slack absorbs weekends and courier handover without penalising the vendor.
LATE_DELIVERY_GRACE_DAYS = 2

SCORE_ON_TIME_COMPLETE = 5.0
SCORE_ON_TIME_SHORT = 4.0
SCORE_LATE_COMPLETE = 3.0
SCORE_LATE_SHORT = 2.0


def validate(doc, method=None):
	"""Flag a receipt that falls short of what was ordered.

	Args:
		doc: The Purchase Receipt being validated.
		method: The hook name, supplied by the framework and unused.
	"""
	short_items = get_short_delivered_items(doc)

	if not short_items:
		return

	doc.flags.has_short_delivery = True

	doc.add_comment(
		"Comment",
		_("Short delivery on {0}: received less than {1}% of the ordered quantity.").format(
			", ".join(short_items), int(SHORT_DELIVERY_THRESHOLD * 100)
		),
	)


def on_submit(doc, method=None):
	"""Record how this delivery performed once the receipt is committed.

	Args:
		doc: The Purchase Receipt being submitted.
		method: The hook name, supplied by the framework and unused.
	"""
	create_delivery_rating(doc)


def on_cancel(doc, method=None):
	"""Withdraw the delivery rating a cancelled receipt produced.

	A cancelled receipt describes a delivery that, as far as the system is
	concerned, did not happen. Leaving its rating behind would keep it
	influencing the supplier's average.

	Args:
		doc: The Purchase Receipt being cancelled.
		method: The hook name, supplied by the framework and unused.
	"""
	for name in frappe.get_all(
		"Vendor Rating Log", filters={"purchase_receipt": doc.name}, pluck="name"
	):
		frappe.delete_doc("Vendor Rating Log", name, ignore_permissions=True)


def get_short_delivered_items(doc) -> list[str]:
	"""Return the item codes received below the short-delivery threshold.

	Compares against the quantity ordered on the linked Purchase Order item.
	Rows with no linked order are skipped rather than treated as short: a
	direct receipt was never promised a quantity, so there is nothing to fall
	short of.

	Args:
		doc: The Purchase Receipt to inspect.

	Returns:
		Item codes that arrived short, in receipt order, without duplicates.
	"""
	short_items = []

	for item in doc.items:
		if not item.purchase_order_item:
			continue

		ordered_qty = frappe.db.get_value(
			"Purchase Order Item", item.purchase_order_item, "qty"
		)

		if not ordered_qty:
			continue

		if flt(item.qty) < flt(ordered_qty) * SHORT_DELIVERY_THRESHOLD:
			if item.item_code not in short_items:
				short_items.append(item.item_code)

	return short_items


def get_promised_date(doc):
	"""Return the date this delivery was promised for.

	Takes the latest schedule_date across the linked Purchase Order items: a
	receipt covering several lines is judged against the last thing it was
	waiting on, not the first.

	Args:
		doc: The Purchase Receipt to inspect.

	Returns:
		The promised date, or None when no linked order carries one. None means
		lateness is unknowable, not that the delivery was on time.
	"""
	promised_dates = []

	for item in doc.items:
		if not item.purchase_order_item:
			continue

		schedule_date = frappe.db.get_value(
			"Purchase Order Item", item.purchase_order_item, "schedule_date"
		)

		if schedule_date:
			promised_dates.append(getdate(schedule_date))

	return max(promised_dates) if promised_dates else None


def is_late(doc) -> bool:
	"""Report whether the receipt arrived beyond the promised date and grace.

	Args:
		doc: The Purchase Receipt to inspect.

	Returns:
		True when the posting date is more than the grace period past the
		promised date. False when it is not, and False when no promised date
		exists — an unknown promise is not evidence of lateness.
	"""
	promised = get_promised_date(doc)

	if not promised:
		return False

	return date_diff(getdate(doc.posting_date), promised) > LATE_DELIVERY_GRACE_DAYS


def create_delivery_rating(doc):
	"""Score this delivery on timeliness and completeness.

	One rating per receipt rather than per item: a receipt with five short
	lines is one poor delivery, not five, and scoring per line would let a
	large receipt swamp the supplier's average.

	Returns without acting if this receipt already carries a delivery rating.
	The guard lives here rather than in the callers so both are covered — the
	submit hook, and the hourly job that backfills receipts the hook never saw.
	It also means an amended receipt cannot double-rate its supplier.

	Args:
		doc: The submitted Purchase Receipt.

	Returns:
		The name of the rating created, or None when one already existed.
	"""
	existing = frappe.db.exists(
		"Vendor Rating Log",
		{"purchase_receipt": doc.name, "rating_type": "Delivery"},
	)

	if existing:
		return None

	short = bool(get_short_delivered_items(doc))
	late = is_late(doc)

	if late and short:
		score = SCORE_LATE_SHORT
	elif late:
		score = SCORE_LATE_COMPLETE
	elif short:
		score = SCORE_ON_TIME_SHORT
	else:
		score = SCORE_ON_TIME_COMPLETE

	rating = frappe.get_doc(
		{
			"doctype": "Vendor Rating Log",
			"supplier": doc.supplier,
			"purchase_receipt": doc.name,
			"rating_type": "Delivery",
			"score": score,
			"remarks": _("Automatic delivery score on receipt submission."),
		}
	)

	# The receiving clerk has authority over the receipt, not over rating
	# records; the rating is the system's observation, not theirs.
	rating.insert(ignore_permissions=True)

	return rating.name

    