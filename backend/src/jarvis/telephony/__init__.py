"""Phone gateway: provider-independent call handling for JARVIS."""

from .base import CallState, TelephonyError, TelephonyProvider
from .gateway import VoiceGateway, build_provider, normalise_number, spoken_result
from .tool import register_telephony_tool

__all__ = [
    "CallState",
    "TelephonyError",
    "TelephonyProvider",
    "VoiceGateway",
    "build_provider",
    "normalise_number",
    "register_telephony_tool",
    "spoken_result",
]
