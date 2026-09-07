# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Row-level access rules for the vendor portal.

Role permissions decide what a user may do to a doctype; they cannot say which
records. These hooks answer the second question: whose applications appear in
a list, and whose ratings a user may change.

Deliberately not whitelisted and deliberately not in api.py — the framework
calls these, and putting them beside HTTP endpoints invites someone to call
them directly.
"""

import frappe

from vendor_portal.vendor_portal.doctype.vendor_onboarding.vendor_onboarding import (
	DECISION_ROLES,
)

# Roles that see and edit everything. Built from the decision roles so there
# is one definition of "manager" in this codebase: a user trusted to approve a
# vendor is trusted to read every application behind that decision.
BYPASS_ROLES = (*DECISION_ROLES, "System Manager", "Administrator")


def has_manager_access(user: str | None = None) -> bool:
	"""Report whether a user is exempt from the row-level restrictions.

	Args:
		user: The user to check. Defaults to the session user.

	Returns:
		True when the user holds a managing role.
	"""
	user = user or frappe.session.user

	if user == "Administrator":
		return True

	return bool(set(BYPASS_ROLES) & set(frappe.get_roles(user)))


def vendor_onboarding_query(user: str | None = None) -> str:
	"""Restrict the Vendor Onboarding list to a user's own applications.

	Returned as a SQL fragment appended to the list query's WHERE clause, which
	is how Frappe applies row-level filtering to every list, report and
	`frappe.get_all` call at once — rather than each caller remembering to
	filter.

	Restricted on `owner` because an application has no author field of its
	own: whoever created the record is the team member who submitted it.

	Args:
		user: The user the query is being built for. Defaults to the session
			user.

	Returns:
		An empty string for managers, so no condition is added, or a condition
		restricting to the user's own records. The user is escaped rather than
		interpolated — this string is concatenated into SQL by the framework.
	"""
	user = user or frappe.session.user

	if has_manager_access(user):
		return ""

	return f"""`tabVendor Onboarding`.owner = {frappe.db.escape(user)}"""


def vendor_rating_log_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	"""Allow a user to change only the rating logs they authored.

	Reading is deliberately unrestricted. A team that cannot see each other's
	ratings cannot compare vendors, and the dashboard would report a different
	average to every user — which would make the number meaningless. Only
	authorship is protected, not the performance data itself.

	Args:
		doc: The Vendor Rating Log being accessed.
		user: The user attempting access. Defaults to the session user.
		permission_type: The permission being checked — read, write, delete
			and so on.

	Returns:
		True when access is allowed.
	"""
	user = user or frappe.session.user

	if has_manager_access(user):
		return True

	if permission_type in ("write", "delete", "submit", "cancel"):
		return doc.rated_by == user

	return True

