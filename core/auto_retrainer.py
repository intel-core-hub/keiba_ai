"""Shadow import path for AutoRetrainer (canonical: core.adaptation.auto_retrainer).

This wrapper previously re-exported the implementation at import-time which
could trigger circular imports. Import the implementation lazily when first
instantiated.
"""

AutoRetrainer = None

def _load_autoretrainer():
	global AutoRetrainer
	if AutoRetrainer is None:
		from core.adaptation.auto_retrainer import AutoRetrainer as _AR
		AutoRetrainer = _AR
	return AutoRetrainer

__all__ = ["AutoRetrainer", "_load_autoretrainer"]
