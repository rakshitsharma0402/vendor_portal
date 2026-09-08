// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

// Vendor performance on the Supplier form. The blacklist button calls a
// whitelisted endpoint rather than writing the field: hiding a button from
// someone is not the same as stopping them, and the role check has to live
// where it cannot be bypassed.

const RATING_SCALE_MAX = 5;

// The score below which the rating badge is tinted. Matches the default
// low_rating_threshold in Vendor Portal Settings; the authoritative check is
// the headline indicator, which reads the setting itself.

const LOW_RATING_BADGE_THRESHOLD = 2.5;

frappe.ui.form.on("Supplier", {
	refresh: function (frm) {
		if (frm.is_new()) {
			return;
		}

		render_vendor_stats(frm);
		render_low_rating_indicator(frm);
		add_blacklist_button(frm);
		add_onboarding_button(frm);
	},
});

function render_vendor_stats(frm) {
	frappe.call({
		method: "vendor_portal.api.get_vendor_dashboard",
		args: { supplier: frm.doc.name },
		callback: function (response) {
			const data = response.message;

			if (!data || frm.doc.name !== data.supplier) {
				return;
			}

			// add_section's return value does not expose html() in v16, so the
			// block is rendered through add_comment, which this form already
			// uses successfully elsewhere.
			frm.dashboard.add_comment(
				`<div class="row">
					${stat_column(__("Purchase Orders"), data.total_pos)}
					${stat_column(__("Total Order Value"), format_currency(data.total_po_value))}
					${stat_column(__("Average Rating"), rating_label(data))}
					${stat_column(__("Total Ratings"), frm.doc.custom_total_rating_count || 0)}
				</div>`,
				"blue",
				true
			);
		},
	});
}

function stat_column(label, value) {
	return `
		<div class="col-sm-3">
			<div class="text-muted small">${label}</div>
			<div class="h6">${value}</div>
		</div>`;
}

function rating_label(data) {
	// An unrated vendor is not a badly rated one, and 0.00/5 would read as
	// the worst possible score rather than as an absence of data.
	if (!data.avg_rating) {
		return `<span class="vendor-portal-rating-badge">${__("Not yet rated")}</span>`;
	}

	// The low modifier is applied from the same figure the indicator uses, so
	// the badge and the headline alert cannot disagree.
	const low = data.avg_rating < LOW_RATING_BADGE_THRESHOLD;
	const modifier = low ? " vendor-portal-rating-badge--low" : "";

	return `<span class="vendor-portal-rating-badge${modifier}">${flt(data.avg_rating, 2)}/5</span>`;
}

function render_low_rating_indicator(frm) {
	if (!frm.doc.custom_total_rating_count) {
		return;
	}

	frappe.db
		.get_single_value("Vendor Portal Settings", "low_rating_threshold")
		.then((threshold) => {
			if (!threshold) {
				return;
			}

			const rating = (frm.doc.custom_vendor_rating || 0) * RATING_SCALE_MAX;

			if (rating >= threshold) {
				return;
			}

			frm.dashboard.set_headline_alert(
				__("Low Rating — Review Required"),
				"orange"
			);
		});
}

function add_blacklist_button(frm) {
	// Drawn for a purchase manager only, but this is convenience: the
	// endpoint refuses anyone else regardless of what the form offers.
	if (!frappe.user.has_role("Purchase Manager")) {
		return;
	}

	if (frm.doc.custom_is_blacklisted) {
		frm.add_custom_button(__("Remove from Blacklist"), () => {
			set_blacklist(frm, 0, null);
		});

		return;
	}

	frm.add_custom_button(__("Blacklist Supplier"), () => {
		frappe.prompt(
			{
				fieldname: "reason",
				label: __("Reason"),
				fieldtype: "Small Text",
				reqd: 1,
			},
			(values) => set_blacklist(frm, 1, values.reason),
			__("Blacklist {0}", [frm.doc.supplier_name || frm.doc.name]),
			__("Blacklist")
		);
	});
}

function set_blacklist(frm, blacklisted, reason) {
	frappe.call({
		method: "vendor_portal.api.set_supplier_blacklist",
		args: { supplier: frm.doc.name, blacklisted: blacklisted, reason: reason },
		freeze: true,
		callback: function (response) {
			if (!response.message) {
				return;
			}

			frappe.show_alert({
				message: blacklisted
					? __("Supplier blacklisted.")
					: __("Supplier removed from blacklist."),
				indicator: blacklisted ? "red" : "green",
			});

			frm.reload_doc();
		},
	});
}

function add_onboarding_button(frm) {
	if (!frm.doc.custom_onboarding_reference) {
		return;
	}

	frm.add_custom_button(__("View Onboarding"), () => {
		frappe.set_route("Form", "Vendor Onboarding", frm.doc.custom_onboarding_reference);
	});
}

