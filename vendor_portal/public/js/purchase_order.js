// Copyright (c) 2026, Rakshit Sharma and contributors
// For license information, please see license.txt

// Vendor standing on the Purchase Order form. Everything here is display and
// convenience: the blacklist and rating rules that actually block an order
// live in the Purchase Order controller, and this script never decides
// whether a document may be saved.

// The Rating field stores a 0-1 fraction. Repeated from vendor_portal.utils,
// which cannot be imported client-side — a known duplication, same as the
// Purchase Invoice banner.
const RATING_SCALE_MAX = 5;

frappe.ui.form.on("Purchase Order", {
	refresh: function (frm) {
		render_vendor_standing(frm);
		add_rating_actions(frm);
	},

	supplier: function (frm) {
		// The cached vendor data belongs to the previous supplier; drop it
		// before anything reads it.
		frm.__vendor_info = null;
		render_vendor_standing(frm);
	},
});

function render_vendor_standing(frm) {
	frm.dashboard.clear_comment();

	if (!frm.doc.supplier) {
		frm.dashboard.clear_headline();
		return;
	}

	fetch_vendor_info(frm).then((info) => {
		if (!info) {
			return;
		}

		show_headline(frm, info);
		show_blacklist_banner(frm, info);
	});
}

// One fetch per supplier, shared by the headline, the banner and the rating
// dialog. Three separate calls for the same three fields on every form load
// would be three round trips for one answer.
function fetch_vendor_info(frm) {
	if (frm.__vendor_info) {
		return Promise.resolve(frm.__vendor_info);
	}

	const supplier = frm.doc.supplier;

	return frappe.db
		.get_value("Supplier", supplier, [
			"custom_vendor_category",
			"custom_vendor_rating",
			"custom_total_rating_count",
			"custom_is_blacklisted",
			"custom_blacklist_reason",
		])
		.then((response) => {
			// The user may have changed supplier while this was in flight.
			// Returning null rather than caching keeps the wrong vendor's
			// details off the form.
			if (frm.doc.supplier !== supplier) {
				return null;
			}

			frm.__vendor_info = response.message || {};

			return frm.__vendor_info;
		});
}

function show_headline(frm, info) {
	const category = info.custom_vendor_category || __("Uncategorised");

	let standing;

	if (info.custom_total_rating_count) {
		const rating = ((info.custom_vendor_rating || 0) * RATING_SCALE_MAX).toFixed(1);

		standing = __("{0}/5 from {1} ratings", [rating, info.custom_total_rating_count]);
	} else {
		// A vendor with no history is unrated, not badly rated. Showing 0.0/5
		// would read as the worst possible score.
		standing = __("not yet rated");
	}

	frm.dashboard.set_headline(
		__("Vendor: {0} · {1}", [frappe.utils.escape_html(category), standing])
	);
}

function show_blacklist_banner(frm, info) {
	if (!info.custom_is_blacklisted) {
		return;
	}

	const reason = info.custom_blacklist_reason || __("no reason recorded");

		// A warning, not a gate. The Purchase Order controller refuses the save
	// server-side; hiding or disabling Save here would leave the buyer with a
	// form that does nothing and no explanation of why.
	frm.dashboard.add_comment(
		`<div class="vendor-portal-blacklist-banner">${__(
			"WARNING: This supplier is blacklisted! Reason: {0}",
			[frappe.utils.escape_html(reason)]
		)}</div>`,
		"red",
		true
	);
}

function add_rating_actions(frm) {
	if (!frm.doc.supplier || frm.is_new()) {
		return;
	}

	frm.add_custom_button(
		__("View Vendor Rating History"),
		() => show_rating_history(frm),
		__("Actions")
	);

	// Only while the supplier can still be changed. After submit a comparison
	// is a curiosity rather than a decision, and offering it implies the order
	// can still be moved.
	if (frm.doc.docstatus === 0 && (frm.doc.items || []).length) {
		frm.add_custom_button(
			__("Compare Suppliers"),
			() => show_comparison_matrix(frm),
			__("Actions")
		);
	}

	if (frm.doc.docstatus === 1) {
		frm.add_custom_button(
			__("Rate This Supplier"),
			() => show_rating_dialog(frm),
			__("Actions")
		);
	}
}

function show_rating_history(frm) {
	frappe.call({
		method: "vendor_portal.api.get_vendor_dashboard",
		args: { supplier: frm.doc.supplier },
		freeze: true,
		freeze_message: __("Fetching rating history..."),
		callback: function (response) {
			const data = response.message;

			if (!data) {
				return;
			}

			const dialog = new frappe.ui.Dialog({
				title: __("Rating history: {0}", [frm.doc.supplier_name || frm.doc.supplier]),
				size: "large",
				fields: [{ fieldtype: "HTML", fieldname: "history" }],
			});

			dialog.fields_dict.history.$wrapper.html(build_history_html(data));
			dialog.show();
		},
	});
}

function build_history_html(data) {
	if (!data.recent_ratings || !data.recent_ratings.length) {
		// An empty table reads as a rendering failure; saying so does not.
		return `<p class="text-muted">${__("This supplier has not been rated yet.")}</p>`;
	}

	const rows = data.recent_ratings
		.map(
			(rating) => `
			<tr>
				<td>${frappe.datetime.str_to_user(rating.rating_date) || ""}</td>
				<td>${frappe.utils.escape_html(rating.rating_type || "")}</td>
				<td>${flt(rating.score, 1)}</td>
				<td>${frappe.utils.escape_html(rating.remarks || "")}</td>
			</tr>`
		)
		.join("");

	return `
		<p>${__("Overall: {0}/5 from {1} ratings", [
			flt(data.avg_rating, 2),
			data.recent_ratings.length,
		])}</p>
		<table class="table table-bordered">
			<thead>
				<tr>
					<th>${__("Date")}</th>
					<th>${__("Type")}</th>
					<th>${__("Score")}</th>
					<th>${__("Remarks")}</th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>`;
}

function show_rating_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Rate {0}", [frm.doc.supplier_name || frm.doc.supplier]),
		fields: [
			{
				fieldname: "rating_type",
				label: __("Rating Type"),
				fieldtype: "Select",
				options: ["Delivery", "Quality", "Pricing", "Communication"].join("\n"),
				reqd: 1,
				default: "Quality",
			},
			{
				fieldname: "score",
				label: __("Score"),
				fieldtype: "Rating",
				reqd: 1,
			},
			{
				fieldname: "remarks",
				label: __("Remarks"),
				fieldtype: "Small Text",
			},
		],
		primary_action_label: __("Submit Rating"),
		primary_action: (values) => submit_rating(frm, dialog, values),
	});

	dialog.show();
}

function submit_rating(frm, dialog, values) {
	frappe.call({
		method: "vendor_portal.api.submit_vendor_rating",
		args: {
			supplier: frm.doc.supplier,
			rating_type: values.rating_type,
			// The dialog's Rating control yields a 0-1 fraction like the
			// stored field; the API expects a score out of five.
			score: (values.score || 0) * RATING_SCALE_MAX,
			remarks: values.remarks,
			purchase_order: frm.doc.name,
		},
		freeze: true,
		freeze_message: __("Submitting rating..."),
		callback: function (response) {
			if (!response.message) {
				return;
			}

			dialog.hide();

			frappe.show_alert({
				message: __("Rating submitted. {0} now rated {1}/5.", [
					frm.doc.supplier_name || frm.doc.supplier,
					flt(response.message.rating, 1),
				]),
				indicator: "green",
			});

			// The headline is now stale; drop the cache and redraw rather
			// than making the user reload to see the score they just gave.
			frm.__vendor_info = null;
			render_vendor_standing(frm);
		},
	});
}

function show_comparison_matrix(frm) {
	// Opens on the item already on the order rather than an empty picker: the
	// buyer has the line in front of them, and making them retype it turns a
	// tool into a form.
	const first_item = frm.doc.items[0];

	const dialog = new frappe.ui.Dialog({
		title: __("Compare suppliers"),
		size: "extra-large",
		fields: [
			{
				fieldname: "item_code",
				label: __("Item"),
				fieldtype: "Link",
				options: "Item",
				default: first_item.item_code,
				reqd: 1,
				onchange: function () {
					load_comparison(frm, dialog);
				},
			},
			{ fieldtype: "HTML", fieldname: "comparison" },
		],
	});

	dialog.show();

	load_comparison(frm, dialog);
}

function load_comparison(frm, dialog) {
	const item_code = dialog.get_value("item_code");

	if (!item_code) {
		return;
	}

	// The quantity on the matching order line, so estimated cost answers
	// "what would this order cost from them" rather than pricing one unit
	// nobody is buying.
	const line = (frm.doc.items || []).find((row) => row.item_code === item_code);
	const qty = line ? line.qty : 1;

	frappe.call({
		method: "vendor_portal.api.get_supplier_comparison",
		args: { item_code: item_code, qty: qty },
		freeze: true,
		freeze_message: __("Comparing suppliers..."),
		callback: function (response) {
			dialog.fields_dict.comparison.$wrapper.html(
				build_comparison_html(response.message || [], frm.doc.supplier, qty)
			);
		},
	});
}

function build_comparison_html(rows, current_supplier, qty) {
	if (!rows.length) {
		return `<p class="text-muted">${__(
			"No supplier has been ordered this item before."
		)}</p>`;
	}

	const body = rows
		.map((row) => {
			const is_current = row.supplier === current_supplier;

			// The supplier already on the order is marked so a buyer can see
			// where their current choice sits rather than hunting for it.
			const marker = is_current
				? ` <span class="text-muted">(${__("on this order")})</span>`
				: "";

			// A null delivery score means the supplier has never been rated on
			// delivery. Rendering 0.00 would place them below a vendor who has
			// genuinely failed.
			const delivery =
				row.delivery_score === null || row.delivery_score === undefined
					? "—"
					: flt(row.delivery_score, 2);

			return `
				<tr${is_current ? ' style="background: var(--gray-50);"' : ""}>
					<td>${frappe.utils.escape_html(row.supplier_name || row.supplier)}${marker}</td>
					<td class="text-right">${format_currency(row.last_rate)}</td>
					<td class="text-right">${format_currency(row.avg_rate)}</td>
					<td class="text-right">${flt(row.total_supplied_qty, 2)}</td>
					<td class="text-right">${format_currency(row.estimated_cost)}</td>
					<td class="text-right">${flt(row.vendor_rating, 2)}/5</td>
					<td class="text-right">${delivery}</td>
				</tr>`;
		})
		.join("");

	return `
		<p class="text-muted">${__("Estimated cost is for {0} units, ordered best-rated first.", [
			qty,
		])}</p>
		<table class="table table-bordered">
			<thead>
				<tr>
					<th>${__("Supplier")}</th>
					<th class="text-right">${__("Last Rate")}</th>
					<th class="text-right">${__("Avg Rate")}</th>
					<th class="text-right">${__("Supplied Qty")}</th>
					<th class="text-right">${__("Est. Cost")}</th>
					<th class="text-right">${__("Rating")}</th>
					<th class="text-right">${__("Delivery")}</th>
				</tr>
			</thead>
			<tbody>${body}</tbody>
		</table>`;
}

