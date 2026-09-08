app_name = "vendor_portal"
app_title = "Vendor Portal"
app_publisher = "Rakshit Sharma"
app_description = "Vendor Portal and Purchase Automation System"
app_email = "rakshit@test.com"
app_license = "mit"

# Send non-GET requests for this app's endpoints as native `application/json`
# bodies instead of form-encoded, per-key JSON-stringified values.
use_json_request_body = True

# Apps
# ------------------

required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "vendor_portal",
# 		"logo": "/assets/vendor_portal/logo.png",
# 		"title": "Vendor Portal",
# 		"route": "/vendor_portal",
# 		"has_permission": "vendor_portal.api.permission.has_app_permission",
# 	}
# ]

# The dock, the rail down the left of the desk, is a document rather than a hook. Author it in
# Manage Dock on a developer-mode site and press Export to App, and it is written to
# `vendor_portal/dock/vendor_portal/vendor_portal.json` for git to carry. An app that ships none has no
# rail: its sidebar gets a switcher in the header instead.
#
# A companion app, one that extends a host app rather than standing on its own, says so with
# `mount_on` on that same record, and its entries are appended to the host's rail. Mounting keeps
# the companion off the apps screen, so it takes precedence over any add_to_apps_screen above.

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/vendor_portal/css/vendor_portal.css"
# app_include_js = "/assets/vendor_portal/js/vendor_portal.js"

# --- Desk assets -------------------------------------------------------
# app_include_js carries the form scripts, which must load on every desk page.
# The Purchase Order list override is registered separately because
# app_include_js loads before ERPNext's own per-doctype list script, which
# would then assign over it.

app_include_js = "vendor_portal.bundle.js"

app_include_css = "vendor_portal.bundle.css"

# include js, css files in header of web template
# web_include_css = "/assets/vendor_portal/css/vendor_portal.css"
# web_include_js = "/assets/vendor_portal/js/vendor_portal.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "vendor_portal/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
doctype_list_js = {"Purchase Order": "public/js/purchase_order_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "vendor_portal/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Setup Wizard
# ------------

# open a fresh site's setup in this app's own UI instead of the desk wizard.
# must be a non-desk route (not under /desk or /app); to customize setup within
# desk, use setup_wizard_stages / setup_wizard_complete instead.
# setup_wizard_url = "/vendor_portal/setup"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "vendor_portal.utils.jinja_methods",
# 	"filters": "vendor_portal.utils.jinja_filters"
# }

# Templates get the star filter and nothing else. Registering `utils` here
# would expose every public callable in it, including the rating
# recalculation, which writes to the database — not a capability a print
# format should have.
jinja = {
	"filters": ["vendor_portal.jinja_filters"],
}

# Installation
# ------------

# before_install = "vendor_portal.install.before_install"
# after_install = "vendor_portal.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "vendor_portal.uninstall.before_uninstall"
# after_uninstall = "vendor_portal.uninstall.after_uninstall"

# Disable / Enable
# ----------------
# Called when this app is logically disabled or re-enabled on a site,
# without uninstalling it. Use this to hide/restore fields this app adds
# to other apps' doctypes.

# before_disable = "vendor_portal.uninstall.before_disable"
# after_disable = "vendor_portal.uninstall.after_disable"
# before_enable = "vendor_portal.install.before_enable"
# after_enable = "vendor_portal.install.after_enable"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "vendor_portal.utils.before_app_install"
# after_app_install = "vendor_portal.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "vendor_portal.utils.before_app_uninstall"
# after_app_uninstall = "vendor_portal.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "vendor_portal.build.after_build"

# To hook into the build process of other apps
# The list of apps being built is passed as an argument

# after_app_build = "vendor_portal.build.after_app_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "vendor_portal.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["vendor_portal.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# --- Row-level access --------------------------------------------------
# Role permissions decide what a user may do to a doctype; these decide which
# records. Applied by the framework to every list, report and get_all at once,
# so an API call is restricted the same way the list view is.

permission_query_conditions = {
	"Vendor Onboarding": "vendor_portal.permissions.vendor_onboarding_query",
}

has_permission = {
	"Vendor Rating Log": "vendor_portal.permissions.vendor_rating_log_permission",
}


# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }
doc_events = {
	"Purchase Receipt": {
		"validate": "vendor_portal.overrides.purchase_receipt.validate",
		"on_submit": "vendor_portal.overrides.purchase_receipt.on_submit",
		"on_cancel": "vendor_portal.overrides.purchase_receipt.on_cancel",
	}
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"vendor_portal.tasks.all"
# 	],
# 	"daily": [
# 		"vendor_portal.tasks.daily"
# 	],
# 	"hourly": [
# 		"vendor_portal.tasks.hourly"
# 	],
# 	"weekly": [
# 		"vendor_portal.tasks.weekly"
# 	],
# 	"monthly": [
# 		"vendor_portal.tasks.monthly"
# 	],
# }

# --- Scheduled work ----------------------------------------------------
# Every job here is safe to run twice: each recomputes from source or checks
# whether its work is already done. cron takes a dict of expressions rather
# than a list, unlike the named intervals above it.

scheduler_events = {
	"daily": [
		"vendor_portal.tasks.recalculate_all_vendor_ratings",
	],
	"hourly": [
		"vendor_portal.tasks.rate_pending_deliveries",
	],
	"weekly": [
		"vendor_portal.tasks.send_performance_digest",
	],
	"cron": {
		"0 9 * * *": [
			"vendor_portal.tasks.expire_stale_onboardings",
		],
	},
}

# Testing
# -------

# before_tests = "vendor_portal.install.before_tests"
before_tests = "vendor_portal.tests.utils.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "vendor_portal.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "vendor_portal.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "vendor_portal.task.get_dashboard_data"
# }

# --- ERPNext behaviour -------------------------------------------------
# Deep controller changes go through override_doctype_class; cross-cutting
# observations go through doc_events. The Purchase Order rules decide whether
# an order is valid at all, so they belong inside the controller. A delivery
# rating is an observation about an event the receipt happens to record, and
# is additive — removing it would not change what a Purchase Receipt is.

override_doctype_class = {
	"Purchase Order": "vendor_portal.overrides.purchase_order.CustomPurchaseOrder"
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["vendor_portal.utils.before_request"]
# after_request = ["vendor_portal.utils.after_request"]

# Job Events
# ----------
# before_job = ["vendor_portal.utils.before_job"]
# after_job = ["vendor_portal.utils.after_job"]

# after_file_upload = ["vendor_portal.utils.after_file_upload"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"vendor_portal.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

fixtures = [
	{
		"dt": "Vendor Category",
		"filters": [
			[
				"name",
				"in",
				[
					"Raw Materials",
					"Packaging",
					"IT Services",
					"Office Supplies",
					"Logistics",
				],
			]
		],
	},
	{
		# Filtered by explicit name rather than dt = Supplier: an unfiltered
		# export would also capture ERPNext's regional fields and anything
		# else customised on this bench.
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Supplier-custom_vendor_category",
					"Supplier-custom_vendor_rating",
					"Supplier-custom_total_rating_count",
					"Supplier-custom_onboarding_reference",
					"Supplier-custom_is_blacklisted",
					"Supplier-custom_blacklist_reason",
				],
			]
		],
	},
	{
		"dt": "Workflow",
		"filters": [["name", "in", ["Vendor Onboarding Approval"]]],
	},
	{
		# Standard states are exported alongside the custom one: re-importing
		# an existing state is harmless, while a missing one breaks every
		# transition that references it on a fresh site.
		"dt": "Workflow State",
		"filters": [["name", "in", ["Draft", "Under Review", "Approved", "Rejected"]]],
	},
	{
		"dt": "Workflow Action Master",
		"filters": [["name", "in", ["Submit for Review", "Approve", "Reject", "Resubmit"]]],
	},
    	{
		"dt": "Role",
		"filters": [["name", "in", ["Vendor Manager", "Purchase Team"]]],
	},
    {
		"dt": "Supplier Scorecard Variable",
		"filters": [["name", "in", ["Vendor Portal Rating"]]],
	},
	{
		"dt": "Supplier Scorecard Criteria",
		"filters": [["name", "in", ["Vendor Portal Rating"]]],
	},
]

