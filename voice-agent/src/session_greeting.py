from __future__ import annotations

import logging
import re

from livekit.agents import AgentSession

from client_config import (
    DEFAULT_VOICE_AGENT_GREETING,
    SUPPORTED_VOICE_AGENT_LANGUAGES,
    voice_agent_language_label,
)

logger = logging.getLogger("relaydesk-agent")

GREETING_INSTRUCTIONS = DEFAULT_VOICE_AGENT_GREETING

_INSTRUCTION_MARKERS = (
    "greet the caller",
    "introduce the business",
    "summarize key service",
    "say you can answer",
    "ask what they would like",
    "ask we are offerings",
)

_DEFAULT_GREETING_TEMPLATES = {
    "hi-IN": "नमस्ते, आपने {client_name} पर कॉल किया है। मैं दस्तावेज़ देखकर आपके सवालों में मदद कर सकता हूँ। आप क्या जानना चाहेंगे?",
    "en-IN": "Hello, thank you for calling {client_name}. I can answer questions using the uploaded documents. What would you like to know?",
    "bn-IN": "{client_name}-এ কল করার জন্য ধন্যবাদ। আমি নথি দেখে আপনার প্রশ্নের উত্তর দিতে পারি। আপনি কী জানতে চান?",
    "gu-IN": "{client_name} પર કૉલ કરવા બદલ આભાર. હું દસ્તાવેજો જોઈને તમારા પ્રશ્નોમાં મદદ કરી શકું છું. તમે શું જાણવા માંગો છો?",
    "kn-IN": "{client_name} ಗೆ ಕರೆ ಮಾಡಿದಕ್ಕಾಗಿ ಧನ್ಯವಾದಗಳು. ನಾನು ದಾಖಲೆಗಳನ್ನು ನೋಡಿ ನಿಮ್ಮ ಪ್ರಶ್ನೆಗಳಿಗೆ ಸಹಾಯ ಮಾಡಬಹುದು. ನೀವು ಏನು ತಿಳಿದುಕೊಳ್ಳಲು ಬಯಸುತ್ತೀರಿ?",
    "ml-IN": "{client_name} ലേക്ക് വിളിച്ചതിന് നന്ദി. രേഖകൾ പരിശോധിച്ച് നിങ്ങളുടെ ചോദ്യങ്ങൾക്ക് ഞാൻ സഹായിക്കാം. നിങ്ങൾക്ക് എന്താണ് അറിയേണ്ടത്?",
    "mr-IN": "{client_name} ला कॉल केल्याबद्दल धन्यवाद. मी कागदपत्रे पाहून तुमच्या प्रश्नांमध्ये मदत करू शकतो. तुम्हाला काय जाणून घ्यायचे आहे?",
    "od-IN": "{client_name} କୁ କଲ୍ କରିଥିବାରୁ ଧନ୍ୟବାଦ। ମୁଁ ଡକ୍ୟୁମେଣ୍ଟ ଦେଖି ଆପଣଙ୍କ ପ୍ରଶ୍ନରେ ସହଯୋଗ କରିପାରିବି। ଆପଣ କ'ଣ ଜାଣିବାକୁ ଚାହୁଁଛନ୍ତି?",
    "pa-IN": "{client_name} ਨੂੰ ਕਾਲ ਕਰਨ ਲਈ ਧੰਨਵਾਦ। ਮੈਂ ਦਸਤਾਵੇਜ਼ ਵੇਖ ਕੇ ਤੁਹਾਡੇ ਸਵਾਲਾਂ ਵਿੱਚ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ। ਤੁਸੀਂ ਕੀ ਜਾਣਨਾ ਚਾਹੁੰਦੇ ਹੋ?",
    "ta-IN": "{client_name} க்கு அழைத்ததற்கு நன்றி. ஆவணங்களை பார்த்து உங்கள் கேள்விகளுக்கு நான் உதவ முடியும். நீங்கள் என்ன জানতে விரும்புகிறீர்கள்?",
    "te-IN": "{client_name} కు కాల్ చేసినందుకు ధన్యవాదాలు. పత్రాలను చూసి మీ ప్రశ్నలకు నేను సహాయం చేయగలను. మీరు ఏమి తెలుసుకోవాలనుకుంటున్నారు?",
}


def is_session_closing_error(exc: BaseException) -> bool:
    return isinstance(exc, RuntimeError) and "AgentSession is closing" in str(exc)


def is_greeting_instructions(text: str) -> bool:
    """True when the greeting field holds LLM instructions, not speakable script."""
    normalized = " ".join(text.strip().lower().split())
    if normalized == " ".join(DEFAULT_VOICE_AGENT_GREETING.strip().lower().split()):
        return True
    return any(marker in normalized for marker in _INSTRUCTION_MARKERS)


def build_greeting_reply_instructions(
    *, client_name: str, instructions: str, voice_agent_language: str
) -> str:
    language = voice_agent_language_label(voice_agent_language)
    return (
        f"{instructions.strip()}\n\n"
        "You are speaking on a phone call. "
        f"Greet the caller in {language}. "
        f"Mention the business name as {client_name.strip() or 'our office'}. "
        "Keep it brief and natural, using one or two short sentences. "
        "Do not use markdown or bullet points."
    )


def build_default_spoken_greeting(*, client_name: str, voice_agent_language: str) -> str:
    business_name = client_name.strip() or "our office"
    template = _DEFAULT_GREETING_TEMPLATES.get(
        voice_agent_language,
        _DEFAULT_GREETING_TEMPLATES["en-IN"],
    )
    return template.format(client_name=business_name)


assert set(SUPPORTED_VOICE_AGENT_LANGUAGES).issubset(_DEFAULT_GREETING_TEMPLATES)


def build_instruction_style_spoken_greeting(
    *, client_name: str, instructions: str, voice_agent_language: str
) -> str:
    del instructions
    return build_default_spoken_greeting(
        client_name=client_name,
        voice_agent_language=voice_agent_language,
    )


def normalize_spoken_greeting(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


async def greet_caller(
    session: AgentSession,
    *,
    greeting_instructions: str,
    client_name: str = "",
    voice_agent_language: str = "hi-IN",
) -> bool:
    """Speak the opening greeting. Returns False if the call ended first."""
    instructions = greeting_instructions.strip()
    if not instructions:
        logger.warning("empty greeting instructions; skipping greeting")
        return False

    if normalize_spoken_greeting(instructions) == normalize_spoken_greeting(
        DEFAULT_VOICE_AGENT_GREETING
    ):
        spoken = build_default_spoken_greeting(
            client_name=client_name,
            voice_agent_language=voice_agent_language,
        )
        logger.info(
            "using direct default greeting template (language=%s)",
            voice_agent_language,
        )
    elif is_greeting_instructions(instructions):
        spoken = build_instruction_style_spoken_greeting(
            client_name=client_name,
            instructions=instructions,
            voice_agent_language=voice_agent_language,
        )
        logger.info(
            "using direct spoken greeting for instruction-style config (language=%s)",
            voice_agent_language,
        )
    else:
        spoken = normalize_spoken_greeting(instructions)
        logger.info("using direct TTS greeting (script text from config)")

    try:
        if normalize_spoken_greeting(instructions) == normalize_spoken_greeting(
            DEFAULT_VOICE_AGENT_GREETING
        ):
            await session.say(spoken, allow_interruptions=False)
        elif is_greeting_instructions(instructions):
            await session.say(spoken, allow_interruptions=False)
        else:
            await session.say(spoken, allow_interruptions=False)
        return True
    except RuntimeError as exc:
        if is_session_closing_error(exc):
            logger.info("skipping greeting: session ended before reply could start")
            return False
        raise
