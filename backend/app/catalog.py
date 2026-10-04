from dataclasses import dataclass


@dataclass(frozen=True)
class Intent:
    key: str
    english: str
    emoji: str
    expression: str
    gesture: str


INTENTS = (
    Intent("greeting", "Hi!", "👋", "cheerful smile", "raising one open hand beside the face and waving hello"),
    Intent("agreement", "Yes!", "👍", "confident happy grin", "giving a clear thumbs up with one hand"),
    Intent("refusal", "Nope", "🙅", "firm disapproving frown", "crossing both forearms in an X in front of the chest"),
    Intent("laughter", "LOL", "😂", "laughing with eyes squeezed shut and a wide open mouth", "one hand on the belly and the other wiping a tear of laughter"),
    Intent("surprise", "OMG!", "😮", "wide eyes and mouth open in surprise", "both open hands raised beside the cheeks"),
    Intent("thanks", "Thanks!", "🙏", "grateful gentle smile", "pressing both palms together in front of the chest"),
    Intent("apology", "Sorry", "😔", "remorseful downcast eyes", "head tilted slightly forward with the eyes still visible, one hand over the heart"),
    Intent("affection", "Miss you", "❤️", "warm affectionate smile", "forming a heart shape with both hands in front of the chest"),
    Intent("waiting", "Wait...", "⏳", "impatient raised eyebrow", "looking at a wristwatch and pointing to it with the other hand"),
    Intent("busy", "Busy!", "💼", "focused slightly stressed expression", "typing on a small laptop held at chest level"),
    Intent("goodnight", "Good night", "🌙", "sleepy closed eyes and a soft smile", "resting the cheek on both hands pressed together like a pillow"),
    Intent("congrats", "Congrats!", "🎉", "joyful beaming smile", "raising both fists beside the head in celebration with a few confetti pieces"),
)
INTENT_BY_KEY = {intent.key: intent for intent in INTENTS}
PREVIEW_INTENTS = {"greeting", "laughter", "surprise"}
STYLES = {
    "realistic": "photorealistic portrait of the real person, retaining the reference's natural skin texture and facial detail",
    "likeness": "portrait illustration with subtle line art and soft natural shading, realistic facial proportions and detailed eyes",
    "cartoon": "clean 2D cartoon illustration with bold smooth outlines and soft cel shading, detailed recognizable face",
    "chibi": "cute chibi illustration with a large head that keeps the person's real facial features, small upper body",
    "comic": "colorful comic-book illustration with ink outlines and cel shading, detailed recognizable face",
}
TONES = {
    "playful": "playful and energetic, expressive but friendly",
    "warm": "warm and friendly, gentle expressive emotions",
    "dramatic": "strong, theatrical emotions while keeping the person's exact face proportions",
}


def artwork_prompt(intent: Intent, style: str, tone: str) -> str:
    action = "Photographically edit these photos to show this exact person" if style == "realistic" else "Draw this exact person"
    return (
        "Image 1 is a close-up photo of a person's face. Image 2 shows the same person's hair, clothes and accessories. "
        f"{action} as a {STYLES[style]}. "
        "The face must be instantly recognizable as the person in image 1: copy the exact face shape, jawline, cheekbones, "
        "eye shape and spacing, eyebrows, nose, lips, teeth, ears and hairline. Preserve the visible mustache, beard, stubble "
        "and skin marks exactly as shown. Do not add or remove facial hair or accessories. "
        "The photos are the only source for the person's appearance. Add no new facial accessories; reproduce an accessory "
        "only when it is actually visible in the photos. Keep the person's apparent age and gender. Do not invent a generic avatar. "
        "Match the skin tone of image 1 exactly. Keep the hairstyle, clothing, colors and accessories from image 2. "
        "Keep the face's viewing angle and natural proportions from image 1. "
        f"Change only the expression and the pose. Expression: {intent.expression}. Pose: {intent.gesture}. Mood: {TONES[tone]}. "
        "Framing: chest-up, the head is large and fills about 40 percent of the image height, the whole face is clearly visible, "
        "hands stay close to the face or chest and fully inside the frame, anatomically plausible hands. "
        "One person only, plain solid white background, no border or outline around the figure, "
        "No text, captions, letters, logos, panels or duplicate people."
    )


# Coherent photo reaction edits; optional experimental animation needs review.
PHOTO_ROUTE = {"realistic", "likeness"}
DRAWN_STYLES = {"cartoon", "chibi", "comic"}


def photo_reaction_prompt(intent: Intent, tone: str = "playful", intensity: float = 1.0) -> str:
    expression = {
        'surprise': 'gently raised eyebrows, attentive relaxed eyes and slightly parted rounded lips as if quietly saying oh',
        'laughter': 'a natural laughing smile, narrowed eyes and a modestly open mouth',
    }.get(intent.key, intent.expression)
    strength = 'subtle' if intensity < .7 else 'clear' if intensity <= 1.1 else 'more expressive but anatomically natural'
    mood = {'warm': 'gentle and warm', 'playful': 'friendly and lively', 'dramatic': 'emphatic with natural proportions'}[tone]
    return (
        "Edit image 1, a photo of a person. Image 2 is the same person's original face reference. "
        "Keep this exact person's face shape, cheekbones, nose, eye size and spacing, facial hair, hair and skin tone. "
        "Keep the original head viewing angle, head position, head size, clothes and accessories. "
        f"Change the facial expression to {expression}. Expression strength: {strength}. "
        f"Change the arms and hands to {intent.gesture}. Mood: {mood}. "
        "Exactly one person, two arms and at most two hands, hands fully visible and clear of the eyes and mouth. "
        "Natural human eye size, pupils, teeth and restrained jaw movement. "
        "Render one coherent photograph with consistent face, jaw, neck and lighting. "
        "Photorealistic, plain white background, no outline, border, text or extra people."
    )


def gesture_edit_prompt(intent: Intent, tone: str = "playful") -> str:
    return (
        "Edit image 1, a photo of a person. Image 2 is a close-up of the same person's face for reference. "
        "Keep the person's head, face, facial expression, hair, head angle, head size and head position exactly unchanged. "
        "Keep the clothes and accessories exactly as in the photo. "
        f"Change only the arms and hands to {intent.gesture}. Hands fully visible inside the frame and anatomically correct. "
        f"Gesture mood: {TONES[tone]}. Exactly two arms and at most two hands. "
        "Keep hands away from eyes and mouth. Photorealistic photo, same lighting, plain solid white background. No text, no extra people."
    )


def expression_driver_prompt(intent: Intent, tone: str = "playful") -> str:
    """Only the expression of this image is used; the person's own face is animated to match it."""
    return (
        "Edit image 1, a close-up photo of a person. Image 2 is another photo of the same person. "
        f"Change only the facial expression to {intent.expression}; make the expression clear and strong. "
        f"Expression mood: {TONES[tone]}. Keep the same person, head angle, head position and size, hair, lighting, plain white background, "
        "and any hands or fingers exactly as in image 1. Photorealistic photo. No text."
    )


def design_prompt(style: str) -> str:
    return (
        "Image 1 is the person's face photo; image 2 shows their clothes and hair. "
        f"Create a chest-up character design as a {STYLES[style]}. "
        "Preserve the source face shape, eye spacing, nose, skin tone, hairline, facial hair and visible accessories. "
        "Keep the person's apparent age and gender, natural facial proportions and smile lines. "
        "Do not add or remove a mustache, beard or stubble: draw only facial hair actually visible in the photos. "
        "Do not invent a younger generic character. Neutral gentle expression, arms lowered, one person, generous padding, plain white background. "
        "No text, labels, panels, duplicate people or added accessories."
    )


def expression_strength(tone: str, intensity: float = 1.0) -> float:
    return min(1.3, max(0.25, intensity * {"warm": 0.75, "playful": 1.0, "dramatic": 1.15}[tone]))


def face_refine_prompt(intent: Intent, style: str) -> str:
    return (
        "Image 1 is a generated portrait crop. Image 2 is a photo of the real person. "
        "Repaint only the face in image 1 so it is unmistakably the person in image 2: same face shape, jawline, eyes, eyebrows, "
        "nose, lips, teeth, ears and hairline, and the same visible mustache, beard, stubble and skin marks as image 2. "
        "Copy only accessories actually visible in image 2; remove any invented facial accessory from image 1. "
        "Do not add or remove facial hair. Match the skin tone of image 2. "
        f"Keep everything else from image 1: the {STYLES[style]} line art and colors, the expression ({intent.expression}), "
        "head angle, position and size, hair outline, hands and white background. Do not move, rotate or resize the head. No text."
    )
