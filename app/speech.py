
from faster_whisper import WhisperModel

_model = None


def get_model():
    global _model

    if _model is None:
        _model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8",
        )

    return _model


def transcribe_audio(audio_path: str) -> str:
    model = get_model()

    segments, _ = model.transcribe(
        audio_path,
        beam_size=5,
        vad_filter=True,
    )

    transcript = " ".join(
        segment.text.strip() for segment in segments
    ).strip()

    if not transcript:
        raise ValueError("No speech detected. Please record again.")

    return transcript
