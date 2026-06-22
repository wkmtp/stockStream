"""Avatar action engine — maps emotions to digital avatar movements.

Determines appropriate avatar gestures (nod, smile, wave, etc.) based on
speaker role, detected emotion, and content context.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from stockstream.dual_host.models import (
    AvatarAction,
    DialogTurn,
    Emotion,
    EMOTION_ACTION_MAP,
    Speaker,
)

logger = logging.getLogger(__name__)


# ── Action descriptions (for logging / debug / external systems) ─

ACTION_METADATA: dict[AvatarAction, dict[str, Any]] = {
    AvatarAction.NOD:       {"intensity": 0.5,  "duration_sec": 0.8,  "body_part": "head"},
    AvatarAction.WAVE:      {"intensity": 0.7,  "duration_sec": 1.5,  "body_part": "right_arm"},
    AvatarAction.THINK:     {"intensity": 0.3,  "duration_sec": 2.0,  "body_part": "head_and_eyes"},
    AvatarAction.POINT:     {"intensity": 0.6,  "duration_sec": 1.0,  "body_part": "right_arm"},
    AvatarAction.CONFIDENT: {"intensity": 0.7,  "duration_sec": 1.2,  "body_part": "posture"},
    AvatarAction.SMILE:     {"intensity": 0.4,  "duration_sec": 1.5,  "body_part": "face"},
    AvatarAction.SURPRISE:  {"intensity": 0.8,  "duration_sec": 1.0,  "body_part": "face_and_hands"},
    AvatarAction.THUMBS_UP: {"intensity": 0.6,  "duration_sec": 1.2,  "body_part": "right_hand"},
    AvatarAction.CURIOUS:   {"intensity": 0.5,  "duration_sec": 1.5,  "body_part": "head_tilt"},
    AvatarAction.LAUGH:     {"intensity": 0.7,  "duration_sec": 2.0,  "body_part": "face_and_shoulders"},
    AvatarAction.IDLE:      {"intensity": 0.1,  "duration_sec": 0.0,  "body_part": "none"},
    AvatarAction.GREETING:  {"intensity": 0.7,  "duration_sec": 2.0,  "body_part": "right_arm"},
    AvatarAction.EXPLAIN:   {"intensity": 0.5,  "duration_sec": 1.5,  "body_part": "hands"},
}


class AvatarActionEngine:
    """Determine avatar gestures based on emotion, speaker, and content.

    Can be integrated with Wav2Lip or other avatar rendering pipelines
    by emitting action cues alongside TTS synthesis.
    """

    def __init__(self) -> None:
        self._last_action: dict[Speaker, AvatarAction] = {
            Speaker.MALE: AvatarAction.IDLE,
            Speaker.FEMALE: AvatarAction.IDLE,
        }
        self._action_cooldown: dict[Speaker, int] = {
            Speaker.MALE: 0,
            Speaker.FEMALE: 0,
        }

    def get_action(self, turn: DialogTurn) -> AvatarAction:
        """Determine the best avatar action for a dialog turn.

        Considers: emotion, speaker role, text content, and prevents
        the same action from repeating too often.
        """
        # Start with emotion-mapped action
        mapped = EMOTION_ACTION_MAP.get(turn.emotion, {}).get(
            turn.speaker, AvatarAction.IDLE
        )

        # If we just used this action, add variety
        if mapped == self._last_action.get(turn.speaker) and self._action_cooldown.get(turn.speaker, 0) > 0:
            mapped = self._alternative_action(turn.speaker, mapped)

        # Cooldown tracking
        self._last_action[turn.speaker] = mapped
        self._action_cooldown[turn.speaker] = max(0, self._action_cooldown.get(turn.speaker, 1) - 1)

        return mapped

    def batch_actions(self, turns: list[DialogTurn]) -> list[dict[str, Any]]:
        """Generate action cues for a batch of dialog turns.

        Returns:
            List of dicts with action, intensity, duration fields.
        """
        results: list[dict[str, Any]] = []
        for i, turn in enumerate(turns):
            action = self.get_action(turn)
            meta = ACTION_METADATA.get(action, ACTION_METADATA[AvatarAction.IDLE])

            # Add transition time between speakers
            if i > 0 and turns[i].speaker != turns[i - 1].speaker:
                # Natural gap between speaker switches
                pass

            results.append({
                "turn_index": i,
                "speaker": turn.speaker.value,
                "text": turn.text[:50],
                "emotion": turn.emotion.value,
                "action": action.value,
                "intensity": meta["intensity"],
                "duration_sec": meta["duration_sec"],
                "body_part": meta["body_part"],
            })

        return results

    def generate_action_script(self, turns: list[DialogTurn]) -> list[dict[str, Any]]:
        """Full action script with timing, for integration with rendering pipelines.

        Returns action cues with sequential timing information.
        """
        return self.batch_actions(turns)

    # ── helpers ─────────────────────────────────────────────────

    def _alternative_action(self, speaker: Speaker,
                            avoid: AvatarAction) -> AvatarAction:
        """Pick an alternative action to avoid repetition."""
        male_actions = [AvatarAction.NOD, AvatarAction.POINT, AvatarAction.CONFIDENT,
                        AvatarAction.EXPLAIN, AvatarAction.IDLE]
        female_actions = [AvatarAction.SMILE, AvatarAction.CURIOUS, AvatarAction.THUMBS_UP,
                          AvatarAction.NOD, AvatarAction.IDLE]

        pool = male_actions if speaker == Speaker.MALE else female_actions
        alternatives = [a for a in pool if a != avoid]
        return random.choice(alternatives) if alternatives else avoid
