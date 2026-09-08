# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Turn informal supplier comments into structured rating logs.

Before this app existed, judgements about vendors lived as comments on the
Supplier record — invisible to every rating the portal computes. This reads
what can be read confidently and leaves the rest.

The inference is a heuristic and the code treats it as one. Keyword matching
has no understanding of negation, sarcasm or context: "not late for once"
matches "late", and "never a quality problem" matches "problem". Rather than
build a negation detector that works most of the time, a comment carrying a
negation near a keyword is skipped and counted. A gap someone can see beats a
score nobody can trace.
"""

import re

import frappe
from frappe.utils import strip_html

# Scores are kept off the ends of the scale. A keyword match is weak evidence,
# and reserving 1 and 5 for scores a person actually chose means inferred data
# is distinguishable from observed data by looking at it.
INFERRED_NEGATIVE_SCORE = 2.0
INFERRED_POSITIVE_SCORE = 4.0

# Every keyword widens the false-positive surface, so these stay short. A
# patch that misclassifies is worse than one that under-reaches: nobody audits
# data that arrived looking plausible.
KEYWORDS = {
	"Delivery": {
		"negative": ("late delivery", "delayed", "delay", "short delivery", "did not deliver"),
		"positive": ("on time", "prompt delivery", "delivered early"),
	},
	"Quality": {
		"negative": ("poor quality", "defective", "damaged", "rejected batch"),
		"positive": ("good quality", "excellent quality", "no defects"),
	},
	"Pricing": {
		"negative": ("overpriced", "expensive", "price increase"),
		"positive": ("competitive price", "good price", "cheaper"),
	},
	"Communication": {
		"negative": ("unresponsive", "no response", "hard to reach"),
		"positive": ("responsive", "quick response", "easy to reach"),
	},
}

# Words that invert a nearby keyword. Their presence anywhere in the comment
# is enough to disqualify it — a cruder test than proximity parsing, and one
# that fails toward skipping rather than toward inventing.
NEGATIONS = ("not", "never", "no longer", "wasn't", "weren't", "didn't", "isn't", "hasn't")

# Marks a log this patch created, and identifies the comment it came from, so
# a second run recognises its own work. A field on Vendor Rating Log would be
# cleaner, but a permanent schema addition to serve a patch that runs once is
# a poor trade.
REMARK_PREFIX = "Inferred from comment"


def execute():
	"""Create rating logs from supplier comments that read clearly.

	One rating per comment regardless of how many keywords it holds: a comment
	saying "late and poor quality" is one observation, and emitting two
	ratings would double its weight in every average computed afterwards.
	"""
	comments = frappe.db.sql(
		"""
		SELECT c.name, c.reference_name AS supplier, c.content, c.owner, c.creation
		FROM `tabComment` c
		INNER JOIN `tabSupplier` s ON s.name = c.reference_name
		WHERE c.reference_doctype = 'Supplier'
			AND c.comment_type = 'Comment'
		ORDER BY c.creation ASC
		""",
		as_dict=True,
	)

	if not comments:
		print("No supplier comments to migrate.")
		return

	created = 0
	skipped_negation = 0
	skipped_no_match = 0
	skipped_existing = 0

	for comment in comments:
		# Comments are stored as HTML; the keywords are prose.
		text = strip_html(comment.content or "").lower().strip()

		if not text:
			continue

		if _already_migrated(comment.name):
			skipped_existing += 1
			continue

		if _has_negation(text):
			skipped_negation += 1
			continue

		match = _classify(text)

		if not match:
			skipped_no_match += 1
			continue

		rating_type, score = match

		_create_rating(comment, rating_type, score, text)
		created += 1

	_report(created, skipped_negation, skipped_no_match, skipped_existing)

	frappe.db.commit()


def _already_migrated(comment_name: str) -> bool:
	"""Report whether this comment has already produced a rating.

	Args:
		comment_name: Name of the Comment record.

	Returns:
		True when a log created from this comment exists.
	"""
	return bool(
		frappe.db.exists(
			"Vendor Rating Log",
			{"remarks": ("like", f"{REMARK_PREFIX} {comment_name}:%")},
		)
	)


def _has_negation(text: str) -> bool:
	"""Report whether the comment contains a word that could invert a keyword.

	Deliberately crude: any negation anywhere disqualifies the comment. Testing
	proximity would catch more cases correctly and would also start being
	wrong in ways nobody notices.

	Args:
		text: The comment's plain text, lowercased.

	Returns:
		True when a negation is present.
	"""
	return any(re.search(rf"\b{re.escape(word)}\b", text) for word in NEGATIONS)


def _classify(text: str) -> tuple[str, float] | None:
	"""Match a comment against the keyword sets.

	The first rating type with a match wins, so a comment touching two
	dimensions is recorded under one rather than counted twice.

	Args:
		text: The comment's plain text, lowercased.

	Returns:
		The rating type and inferred score, or None when nothing matched.
	"""
	for rating_type, sets in KEYWORDS.items():
		if any(keyword in text for keyword in sets["negative"]):
			return rating_type, INFERRED_NEGATIVE_SCORE

		if any(keyword in text for keyword in sets["positive"]):
			return rating_type, INFERRED_POSITIVE_SCORE

	return None


def _create_rating(comment, rating_type: str, score: float, text: str):
	"""Write the inferred rating, attributed to whoever left the comment.

	The comment's author and date are carried across rather than the patch's
	own: the judgement was theirs, and the row-level permission rule keys on
	that field.

	Args:
		comment: The source comment row.
		rating_type: The matched rating type.
		score: The inferred score.
		text: The comment's plain text, for the remark.
	"""
	log = frappe.get_doc(
		{
			"doctype": "Vendor Rating Log",
			"supplier": comment.supplier,
			"rating_type": rating_type,
			"score": score,
			# The remark states plainly that nobody chose this number, and
			# quotes what it was read from, so a reader can judge it.
			"remarks": f"{REMARK_PREFIX} {comment.name}: {text[:180]}",
		}
	)

	log.insert(ignore_permissions=True)

	# Set after insert: both fields carry defaults that would otherwise
	# overwrite the comment's own author and date with the patch's.
	frappe.db.set_value(
		"Vendor Rating Log",
		log.name,
		{"rated_by": comment.owner, "rating_date": comment.creation.date()},
		update_modified=False,
	)


def _report(created: int, negation: int, no_match: int, existing: int):
	"""Print and log what the patch did and declined to do.

	Args:
		created: Ratings written.
		negation: Comments skipped for containing a negation.
		no_match: Comments matching no keyword.
		existing: Comments already migrated by an earlier run.
	"""
	message = (
		f"Created {created} inferred ratings from supplier comments.\n"
		f"Skipped {negation} comments containing a negation.\n"
		f"Skipped {no_match} comments matching no keyword.\n"
		f"Skipped {existing} comments already migrated."
	)

	print(message)

	if created:
		frappe.log_error(
			title="Supplier comments migrated to rating logs",
			message=message,
		)

        