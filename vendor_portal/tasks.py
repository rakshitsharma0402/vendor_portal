# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Scheduled jobs for the vendor portal.

Every job here must be safe to run twice. The scheduler retries, a developer
runs them by hand, and a job killed halfway will be started again from the
beginning — so each one either recomputes from source or checks whether its
work is already done before doing it.
"""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils import add_days, flt, fmt_money, getdate, today

from vendor_portal.utils import rating_field_to_scale, recalculate_vendor_rating
from vendor_portal.overrides.purchase_receipt import create_delivery_rating

def recalculate_all_vendor_ratings():
	"""Reconcile every rated supplier's score with its rating log.

	Ratings reach the Supplier record two ways: the submission endpoint
	updates it immediately, and order and receipt submission create log
	entries without touching it. Cancellation removes entries the same way.
	This closes the gap nightly so the score a buyer sees is never more than a
	day behind what the log actually holds.

	Suppliers are committed one at a time rather than in a single transaction
	at the end: a job killed partway should leave the suppliers it already
	reconciled correct, not roll all of them back.
	"""
	threshold = flt(
		frappe.db.get_single_value("Vendor Portal Settings", "low_rating_threshold")
	)

	for supplier in _get_suppliers_to_recalculate():
		try:
			# Read before overwriting: the alert fires on the crossing, not on
			# the state, and this is the only moment the previous value exists.
			previous = frappe.db.get_value(
				"Supplier",
				supplier,
				["custom_vendor_rating", "custom_total_rating_count"],
				as_dict=True,
			)

			result = recalculate_vendor_rating(supplier)

			frappe.db.commit()

			_alert_if_newly_underperforming(supplier, previous, result, threshold)

		except Exception:
			# One bad supplier must not cost the rest of the run. Logged with
			# its name so the failure is findable rather than a silent gap.
			frappe.log_error(
				title="Vendor rating recalculation failed",
				message=f"Supplier: {supplier}",
			)


def _get_suppliers_to_recalculate() -> list[str]:
	"""Return the suppliers whose stored rating could be out of date.

	Two groups, and the second is the one that is easy to miss. Suppliers with
	rating logs obviously need recalculating. Suppliers with no logs but a
	non-zero stored count had their ratings deleted — by a cancelled order or
	receipt — and would otherwise keep a score nothing supports.

	Iterating every supplier would work but wastes a run on the majority that
	have never been rated at all.

	Returns:
		Supplier names, without duplicates.
	"""
	rated = frappe.db.sql_list(
		"""
		SELECT DISTINCT vrl.supplier
		FROM `tabVendor Rating Log` vrl
		INNER JOIN `tabSupplier` s ON s.name = vrl.supplier
		WHERE COALESCE(s.disabled, 0) = 0
		"""
	)

	stale = frappe.db.sql_list(
		"""
		SELECT name
		FROM `tabSupplier`
		WHERE COALESCE(disabled, 0) = 0
			AND COALESCE(custom_total_rating_count, 0) > 0
			AND name NOT IN (
				SELECT DISTINCT supplier FROM `tabVendor Rating Log`
			)
		"""
	)

	return list(dict.fromkeys([*rated, *stale]))


def _alert_if_newly_underperforming(supplier, previous, result, threshold):
	"""Email vendor managers when a supplier drops below the threshold.

	Only on the crossing. A vendor that has been underperforming for months is
	already known, and mailing about it every night trains the recipients to
	ignore the alert entirely — at which point the one that matters is missed
	too. The weekly digest is where standing problems are listed.

	Args:
		supplier: Name of the Supplier.
		previous: Its stored rating and count before recalculation.
		result: What recalculate_vendor_rating returned.
		threshold: The score below which a vendor is underperforming.
	"""
	if not threshold:
		return

	new_rating = flt(result.get("rating"))

	if not result.get("rating_count") or new_rating >= threshold:
		return

	# A supplier with no previous ratings has not crossed anything — it has
	# arrived. Treated as a crossing so a vendor whose first ratings are poor
	# is not silently accepted.
	previous_rating = rating_field_to_scale(previous.get("custom_vendor_rating"))
	had_ratings = bool(previous.get("custom_total_rating_count"))

	if had_ratings and previous_rating < threshold:
		return

	recipients = _get_vendor_manager_emails()

	if not recipients:
		return

	try:
		frappe.sendmail(
			recipients=recipients,
			subject=_("Vendor rating below threshold: {0}").format(supplier),
			message=_(
				"{0} has dropped to {1} out of 5, below the threshold of {2}. "
				"Purchase orders for this vendor may now be blocked."
			).format(supplier, round(new_rating, 2), threshold),
			reference_doctype="Supplier",
			reference_name=supplier,
		)
	except Exception:
		frappe.log_error(
			title="Low rating alert failed",
			message=f"Supplier: {supplier}\n\n{frappe.get_traceback()}",
		)


def _get_vendor_manager_emails() -> list[str]:
	"""Return the addresses of every enabled user holding the Vendor Manager role.

	Returns:
		Email addresses, without duplicates.
	"""
	return frappe.db.sql_list(
		"""
		SELECT DISTINCT u.name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` r ON r.parent = u.name
		WHERE r.role = %(role)s
			AND u.enabled = 1
			AND u.name NOT IN ('Administrator', 'Guest')
		""",
		{"role": "Vendor Manager"},
	)


# How many receipts one run will rate. A site with years of unrated history
# should catch up over several runs rather than block the scheduler on the
# first one.
DELIVERY_BATCH_SIZE = 200


def rate_pending_deliveries():
	"""Give a delivery rating to submitted receipts that carry none.

	The receipt hook rates on submission, so in normal operation this finds
	nothing. It exists for the receipts the hook never saw: submitted while
	the scheduler or a worker was down, imported from elsewhere, or created
	before the rule existed.

	No time window is applied. The spec suggests looking at the last two
	hours, but an hourly job with a two-hour lookback only re-covers what it
	already did, while a receipt older than that stays unrated forever — which
	is precisely the case this job is for. The existence of a rating is the
	only filter that matters.
	"""
	for name in _get_unrated_receipts():
		try:
			receipt = frappe.get_doc("Purchase Receipt", name)

			create_delivery_rating(receipt)

			frappe.db.commit()

		except Exception:
			frappe.log_error(
				title="Delivery rating backfill failed",
				message=f"Purchase Receipt: {name}\n\n{frappe.get_traceback()}",
			)


def _get_unrated_receipts() -> list[str]:
	"""Return submitted receipts with no delivery rating against them.

	Capped rather than exhaustive: the job runs hourly, so a backlog clears
	over a few runs without any single run holding the worker for minutes.

	Returns:
		Purchase Receipt names, oldest first so a backlog is worked through in
		the order it accumulated.
	"""
	return frappe.db.sql_list(
		"""
		SELECT pr.name
		FROM `tabPurchase Receipt` pr
		LEFT JOIN `tabVendor Rating Log` vrl
			ON vrl.purchase_receipt = pr.name
			AND vrl.rating_type = 'Delivery'
		WHERE pr.docstatus = 1
			AND vrl.name IS NULL
		ORDER BY pr.posting_date ASC, pr.creation ASC
		LIMIT %(limit)s
		""",
		{"limit": DELIVERY_BATCH_SIZE},
	)


# How many suppliers appear in each ranking. Enough to see the shape of the
# distribution without turning a summary into a report.
DIGEST_RANK_SIZE = 5

# The window the digest covers, counted back from the day it runs rather than
# to a calendar boundary — so a digest triggered by hand covers the same seven
# days as one the scheduler fires.
DIGEST_PERIOD_DAYS = 7


def send_performance_digest():
	"""Email the weekly vendor performance summary to vendor managers.

	A thin wrapper: everything that decides what the digest says lives in
	build_performance_digest, which returns a string and touches no mail
	server. That split is what lets the content be inspected on a site with no
	email account configured, and it keeps the figures reusable by anything
	else that wants them.
	"""
	recipients = _get_vendor_manager_emails()

	if not recipients:
		# Nobody holds the role. Not a failure — a site can legitimately have
		# no vendor managers yet, and logging it as an error every week would
		# be noise.
		return

	try:
		frappe.sendmail(
			recipients=recipients,
			subject=_("Vendor performance digest: week ending {0}").format(
				frappe.format(getdate(today()), {"fieldtype": "Date"})
			),
			message=build_performance_digest(),
		)
	except Exception:
		frappe.log_error(
			title="Vendor performance digest failed",
			message=frappe.get_traceback(),
		)


def build_performance_digest() -> str:
	"""Assemble the weekly digest as HTML.

	Returns:
		The digest body. Sections with nothing to report say so rather than
		rendering an empty table, so a quiet week produces a readable email
		rather than a page of headings over nothing.
	"""
	from_date = add_days(today(), -DIGEST_PERIOD_DAYS)
	to_date = today()

	rated = _get_rated_suppliers()
	orders = _get_period_order_summary(from_date, to_date)
	onboardings = _get_period_onboardings(from_date, to_date)
	underperforming = _get_underperforming_suppliers()

	period = _("{0} to {1}").format(
		frappe.format(getdate(from_date), {"fieldtype": "Date"}),
		frappe.format(getdate(to_date), {"fieldtype": "Date"}),
	)

	sections = [
		f"<h2>{_('Vendor performance digest')}</h2>",
		f"<p>{_('Period')}: {period}</p>",
		f"""<p>{_('Purchase orders placed')}: <b>{orders['count']}</b>
			&nbsp;·&nbsp; {_('Total value')}: <b>{fmt_money(orders['value'])}</b></p>""",
		_render_ranking(
			_("Top {0} vendors by rating").format(DIGEST_RANK_SIZE),
			rated[:DIGEST_RANK_SIZE],
		),
		_render_ranking(
			_("Lowest {0} vendors by rating").format(DIGEST_RANK_SIZE),
			list(reversed(rated))[:DIGEST_RANK_SIZE],
		),
		_render_underperforming(underperforming),
		_render_onboardings(onboardings),
		f"<p><i>{_('Rankings cover the {0} suppliers with at least one rating.').format(len(rated))}</i></p>",
	]

	return "".join(sections)


def _get_rated_suppliers() -> list[dict]:
	"""Return suppliers holding at least one rating, best first.

	Unrated suppliers are excluded rather than sorted to the bottom: a vendor
	nobody has scored is not the worst performer, and listing it as one would
	send managers chasing the wrong problem.

	Reads the cached score on Supplier rather than aggregating the log, since
	the daily job keeps it current and the digest is a weekly summary — a
	rating submitted since last night is not worth a second aggregate.

	Returns:
		Supplier name, rating on the 1-5 scale, and rating count.
	"""
	rows = frappe.db.sql(
		"""
		SELECT name, custom_vendor_rating, custom_total_rating_count
		FROM `tabSupplier`
		WHERE COALESCE(disabled, 0) = 0
			AND COALESCE(custom_total_rating_count, 0) > 0
		ORDER BY custom_vendor_rating DESC
		""",
		as_dict=True,
	)

	return [
		{
			"supplier": row.name,
			"rating": rating_field_to_scale(row.custom_vendor_rating),
			"count": int(row.custom_total_rating_count or 0),
		}
		for row in rows
	]


def _get_period_order_summary(from_date: str, to_date: str) -> dict:
	"""Count and total the purchase orders placed in the period.

	Args:
		from_date: Start of the window, inclusive.
		to_date: End of the window, inclusive.

	Returns:
		count and value, the latter in company currency.
	"""
	result = frappe.db.sql(
		"""
		SELECT COUNT(*) AS order_count, COALESCE(SUM(base_grand_total), 0) AS order_value
		FROM `tabPurchase Order`
		WHERE docstatus = 1
			AND transaction_date BETWEEN %(from_date)s AND %(to_date)s
		""",
		{"from_date": from_date, "to_date": to_date},
		as_dict=True,
	)

	row = result[0] if result else {}

	return {
		"count": int(row.get("order_count") or 0),
		"value": flt(row.get("order_value")),
	}


def _get_period_onboardings(from_date: str, to_date: str) -> list[dict]:
	"""Return the applications submitted in the period.

	Args:
		from_date: Start of the window, inclusive.
		to_date: End of the window, inclusive.

	Returns:
		Application name, supplier name and current status.
	"""
	return frappe.db.sql(
		"""
		SELECT name, supplier_name, onboarding_status
		FROM `tabVendor Onboarding`
		WHERE docstatus != 2
			AND DATE(creation) BETWEEN %(from_date)s AND %(to_date)s
		ORDER BY creation DESC
		""",
		{"from_date": from_date, "to_date": to_date},
		as_dict=True,
	)


def _get_underperforming_suppliers() -> list[dict]:
	"""Return every rated supplier currently below the configured threshold.

	Not truncated to a top five: this is the section a manager acts on, and
	hiding the sixth-worst vendor because five others were worse defeats the
	purpose.

	Returns:
		Supplier name and rating on the 1-5 scale, worst first.
	"""
	threshold = flt(
		frappe.db.get_single_value("Vendor Portal Settings", "low_rating_threshold")
	)

	if not threshold:
		return []

	rows = frappe.db.sql(
		"""
		SELECT name, custom_vendor_rating
		FROM `tabSupplier`
		WHERE COALESCE(disabled, 0) = 0
			AND COALESCE(custom_total_rating_count, 0) > 0
			AND custom_vendor_rating < %(threshold)s
		ORDER BY custom_vendor_rating ASC
		""",
		{"threshold": threshold / 5.0},
		as_dict=True,
	)

	return [
		{"supplier": row.name, "rating": rating_field_to_scale(row.custom_vendor_rating)}
		for row in rows
	]


def _render_ranking(heading: str, suppliers: list[dict]) -> str:
	"""Render a supplier ranking as an HTML table.

	Args:
		heading: The section heading.
		suppliers: Rows to render.

	Returns:
		An HTML fragment, or a short note when there is nothing to rank.
	"""
	if not suppliers:
		return f"<h3>{heading}</h3><p>{_('No rated suppliers yet.')}</p>"

	rows = "".join(
		f"""<tr>
			<td>{frappe.utils.escape_html(row['supplier'])}</td>
			<td>{round(row['rating'], 2)}</td>
			<td>{row['count']}</td>
		</tr>"""
		for row in suppliers
	)

	return f"""
		<h3>{heading}</h3>
		<table border="1" cellpadding="6" cellspacing="0">
			<tr><th>{_('Supplier')}</th><th>{_('Rating')}</th><th>{_('Ratings')}</th></tr>
			{rows}
		</table>"""


def _render_underperforming(suppliers: list[dict]) -> str:
	"""Render the below-threshold list.

	Args:
		suppliers: Rows to render.

	Returns:
		An HTML fragment, or a note that nothing is below threshold.
	"""
	heading = _("Vendors below the rating threshold")

	if not suppliers:
		return f"<h3>{heading}</h3><p>{_('No vendors are currently below threshold.')}</p>"

	rows = "".join(
		f"""<tr>
			<td>{frappe.utils.escape_html(row['supplier'])}</td>
			<td>{round(row['rating'], 2)}</td>
		</tr>"""
		for row in suppliers
	)

	return f"""
		<h3>{heading}</h3>
		<table border="1" cellpadding="6" cellspacing="0">
			<tr><th>{_('Supplier')}</th><th>{_('Rating')}</th></tr>
			{rows}
		</table>"""


def _render_onboardings(applications: list[dict]) -> str:
	"""Render the applications submitted in the period.

	Args:
		applications: Rows to render.

	Returns:
		An HTML fragment, or a note that none arrived.
	"""
	heading = _("New vendor applications")

	if not applications:

		