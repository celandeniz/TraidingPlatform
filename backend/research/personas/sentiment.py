from .base import Persona


class SentimentPersona(Persona):
    name = "sentiment"
    system = (
        "You are a news/sentiment analyst. Judge whether recent news flow and market "
        "positioning support the trade. Fresh strong catalysts argue against fading the "
        "move. Vote long/short/pass with confidence. Not investment advice."
    )
