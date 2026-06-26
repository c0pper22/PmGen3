"""RSDF / DSDF document-feeder feed-roll detection rule.

The document feeder (DF) feed rolls come in two mechanical variants:

* DSDF -> the catalog default, supplied by a DSDF feed-roll kit. The DSDF kit
  code is not universal: some models use ``KIT-ROL-DSDF`` while others use
  ``KIT-ROL-MR-4010`` (and more may appear over time).
* RSDF -> supplied by an RSDF feed-roll kit (e.g. ``DF-KIT-3031``), which also
  can differ per variant.

The catalog defaults every model to its DSDF feed-roll kit. This rule inspects
08 Setting Mode code ``9903`` (sub ``0``) to detect whether a specific serial
is actually an RSDF machine and, **only then**, swaps the selected DSDF
feed-roll kit for its RSDF counterpart:

* RSDF detected  -> replace the DSDF feed-roll kit with the RSDF kit (see
  ``DSDF_TO_RSDF_KIT``) and raise an alert.
* DSDF / Unknown / N/A / fetch failure -> do nothing; keep the DSDF kit.

The 08 Setting Mode CSV is normally already fetched by the caller and supplied
through ``ctx.meta["settings_08_bytes"]`` (optionally with
``ctx.meta["session"]``). When the bytes are not supplied the rule fetches them
itself, falling back to "assume DSDF" on any failure so the pipeline never
breaks.
"""
from __future__ import annotations

import logging
from typing import Optional

from pmgen.rules.base import Context, RuleBase

logger = logging.getLogger(__name__)

# DSDF feed-roll kit -> its RSDF replacement.
#
# The DSDF feed-roll kit is not a single code: some models use KIT-ROL-DSDF
# while others use KIT-ROL-MR-4010 (and more may appear). Likewise the RSDF
# counterpart can differ per variant. This table maps each known DSDF kit to
# the RSDF kit that should be ordered instead. Extend it as new feeder
# variants are introduced.
DSDF_TO_RSDF_KIT = {
    "KIT-ROL-DSDF": "DF-KIT-3031",
    "KIT-ROL-MR-4010": "DF-KIT-3031",
}

# 08 Setting Mode code that identifies the document feeder variant.
DF_VARIANT_CODE = 9903
DF_VARIANT_SUB = 0

# Tables of possible 08-9903 sub-0 results (upper-cased). Can be extended.
DSDF_VALUES = {"DF-13", "DF-31"}
RSDF_VALUES = {"DF-38", "DF-68"}


def detect_df_variant(value: Optional[str]) -> str:
    """Classify a raw 08-9903 sub-0 value as ``"RSDF"``, ``"DSDF"`` or ``"UNKNOWN"``.

    Bare/empty values and anything not in the known tables (e.g. ``"N/A"``,
    ``"DF-"``, ``"DF-32"``) are treated as ``UNKNOWN`` so the caller can fall
    back to the DSDF assumption cleanly.
    """
    v = (value or "").strip().upper()
    if not v:
        return "UNKNOWN"
    if v in RSDF_VALUES:
        return "RSDF"
    if v in DSDF_VALUES:
        return "DSDF"
    return "UNKNOWN"


class RsdfDetectionRule(RuleBase):
    """Detect RSDF feed rolls and, when detected, swap the DSDF kit for the RSDF kit."""

    name = "RsdfDetectionRule"

    def apply(self, ctx: Context) -> None:
        # Unidirectional: only act when RSDF is detected. Anything else
        # (DSDF, N/A, unknown, or a fetch failure) leaves the selection as-is,
        # i.e. the catalog's default DSDF feed-roll kit.
        #
        # Only DSDF feed-roll kits that have a known RSDF replacement are
        # candidates, so first check the selection before doing any 08 fetch.
        swaps = {
            kit: qty
            for kit, qty in ctx.kit_selection.items()
            if kit in DSDF_TO_RSDF_KIT
        }
        if not swaps:
            return

        detection, raw_value = self._detect(ctx)
        if detection != "RSDF":
            return

        for dsdf_kit, qty in swaps.items():
            rsdf_kit = DSDF_TO_RSDF_KIT[dsdf_kit]
            ctx.kit_selection.pop(dsdf_kit, None)
            ctx.kit_selection[rsdf_kit] = ctx.kit_selection.get(rsdf_kit, 0) + qty

        # Keep the findings' kit codes in sync with the selection so that
        # downstream rules (due-source categorisation, part resolution) group
        # the feed rolls under the kit we are actually ordering.
        for finding in ctx.findings.values():
            kc = getattr(finding, "kit_code", None)
            if kc in swaps:
                finding.kit_code = DSDF_TO_RSDF_KIT[kc]

        ctx.optional_alerts.append(
            f"RSDF Detected: Document feeder is RSDF "
            f"(08-9903='{raw_value or 'N/A'}'). "
            f"Substituted RSDF feed-roll kit for DSDF kit(s): "
            f"{', '.join(sorted(swaps))}."
        )

    def _detect(self, ctx: Context) -> tuple[str, str]:
        """Return ``(detection, raw_value)``. Never raises.

        Fetch/parse failures return ``("UNKNOWN", "")`` so the caller leaves
        the machine on its default DSDF kit (no swap).
        """
        blob = ctx.meta.get("settings_08_bytes")
        if blob is None:
            blob = self._fetch_08_bytes(ctx)

        if not blob:
            return "UNKNOWN", ""

        try:
            from pmgen.io.http_client import _parse_code_from_csv_bytes

            raw_value = _parse_code_from_csv_bytes(DF_VARIANT_CODE, DF_VARIANT_SUB, blob)
        except Exception:
            logger.exception("Failed to parse 08-9903 from 08 settings data")
            return "UNKNOWN", ""

        return detect_df_variant(raw_value), raw_value

    def _fetch_08_bytes(self, ctx: Context) -> Optional[bytes]:
        """Fetch the 08 Setting Mode CSV for the report's serial, or None."""
        headers = getattr(ctx.report, "headers", {}) or {}
        serial = str(headers.get("serial", "") or "").strip()
        if not serial or serial.upper() == "UNKNOWN":
            return None
        try:
            from pmgen.io.http_client import get_service_file_bytes

            sess = ctx.meta.get("session")
            return get_service_file_bytes(serial, option="08", sess=sess)
        except Exception:
            logger.warning(
                "Failed to fetch 08 settings for RSDF detection (serial=%s)",
                serial,
                exc_info=True,
            )
            return None
