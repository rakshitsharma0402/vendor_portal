# Copyright (c) 2026, Rakshit Sharma and contributors
# For license information, please see license.txt

"""Filters exposed to the Jinja environment.

Frappe registers every public callable in a module listed under the `jinja`
hook, so pointing it at `utils` handed print formats a function that writes to
the Supplier record. This module re-exports only what a template should be able
to call; the implementations stay where they belong, beside the conversions
they depend on.
"""

from vendor_portal.utils import star_rating

__all__ = ["star_rating"]

