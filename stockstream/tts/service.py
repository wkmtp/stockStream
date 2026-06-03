"""Text-to-speech module using CPU-friendly local synthesis by default."""


class TTSService:
    """Creates speech tasks without loading heavyweight models at startup."""

    async def speak(self, text: str) -> dict[str, str]:
        """Return a queued speech event placeholder."""

        return {"status": "queued", "text": text[:256]}
